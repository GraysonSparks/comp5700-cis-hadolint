"""Command-line entry point: runs Task-1, Task-2 and Task-3 in order.

Example:
    cisdiff inputs/docker-cis-v0.pdf inputs/docker-cis-v1.pdf --dockerfiles dockerfiles.zip
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from . import comparator, executor, extractor

log = logging.getLogger("cisdiff")

DOCKERFILE_DEFAULTS = ["dockerfiles.zip", "dokcerfiles.zip", "inputs/dockerfiles.zip", "inputs/dokcerfiles.zip"]


def _default_dockerfiles() -> Path | None:
    env = os.environ.get("CISDIFF_DOCKERFILES")
    if env:
        return Path(env)
    base_dirs = [Path.cwd()]
    if getattr(sys, "frozen", False):
        base_dirs.append(Path(sys.executable).resolve().parent)
    for base in base_dirs:
        for name in DOCKERFILE_DEFAULTS:
            if (base / name).exists():
                return base / name
    return None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cisdiff",
        description="Find changes between two CIS Docker Benchmark PDFs and run the matching Hadolint rules.",
    )
    p.add_argument("pdf_a", help="first CIS benchmark PDF (older version)")
    p.add_argument("pdf_b", help="second CIS benchmark PDF (newer version)")
    p.add_argument("--dockerfiles", type=Path, default=None,
                   help="zip file or folder of Dockerfiles (default: ./dockerfiles.zip or $CISDIFF_DOCKERFILES)")
    p.add_argument("--out", type=Path, default=None,
                   help="output folder (default: outputs/<a>_vs_<b>)")
    p.add_argument("--prompt-type", choices=extractor.PROMPT_TYPES, default="few-shot",
                   help="prompt type whose answers go into the YAML files (default: few-shot)")
    p.add_argument("--only-yaml-prompt", action="store_true",
                   help="run only --prompt-type, not all three prompt types")
    p.add_argument("--model", default=None, help="Hugging Face model ID (default: google/gemma-3-1b-it)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if not args.verbose else logging.DEBUG,
                        format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "httpcore", "urllib3", "huggingface_hub", "transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # the CIS PDFs have harmless xref errors

    try:
        doc_a, doc_b = extractor.load_documents(args.pdf_a, args.pdf_b)
    except extractor.DocumentValidationError as exc:
        log.error("Input validation failed: %s", exc)
        return 2

    if doc_a.name == doc_b.name:  # same file twice: keep the YAML names apart
        doc_a.name, doc_b.name = f"{doc_a.name}-1", f"{doc_b.name}-2"
    out = args.out or Path("outputs") / f"{doc_a.name}_vs_{doc_b.name}"
    out.mkdir(parents=True, exist_ok=True)

    # ---- Task-1 ----
    from .llm import GemmaLLM

    llm = GemmaLLM(model_id=args.model)
    prompt_types = [args.prompt_type] if args.only_yaml_prompt else list(extractor.PROMPT_TYPES)
    records = []
    yaml_paths = []
    for doc in (doc_a, doc_b):
        for pt in prompt_types:
            save_to = out if pt == args.prompt_type else None
            _, recs = extractor.extract_kdes(doc, llm, pt, out_dir=save_to)
            records += recs
        yaml_paths.append(out / f"{doc.name}-kdes.yaml")
    extractor.dump_llm_outputs(records, out / "llm-outputs.txt")
    log.info("Task-1 done: %s, %s", yaml_paths[0].name, yaml_paths[1].name)

    # ---- Task-2 ----
    kdes_a, kdes_b = comparator.load_kde_yamls(*yaml_paths)
    names_txt = comparator.compare_element_names(kdes_a, kdes_b, out / "element-name-differences.txt")
    reqs_txt = comparator.compare_element_requirements(kdes_a, kdes_b, out / "element-requirement-differences.txt")
    log.info("Task-2 done: %s, %s", names_txt.name, reqs_txt.name)

    # ---- Task-3 ----
    diffs = executor.load_difference_files(names_txt, reqs_txt)
    rules_txt = executor.map_differences_to_rules(diffs, out / "hadolint-rules.txt")
    dockerfiles = args.dockerfiles or _default_dockerfiles()
    if dockerfiles is None or not dockerfiles.exists():
        log.error("Dockerfiles not found. Put dockerfiles.zip in the current folder or pass --dockerfiles.")
        return 3
    scan = executor.run_hadolint(rules_txt, dockerfiles)
    csv_path = executor.write_results_csv(scan, out / "hadolint-results.csv")
    log.info("Task-3 done: %s (%d findings)", csv_path.name, len(scan))
    print(f"Outputs written to {out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
