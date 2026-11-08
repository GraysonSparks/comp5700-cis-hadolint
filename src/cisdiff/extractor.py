"""Task-1: Extractor.

Reads two CIS Docker Benchmark PDFs, splits them into recommendations, and
uses Gemma-3-1B to name the key data element (KDE) that each recommendation
is about. Recommendations with the same KDE are grouped, and the result goes
into one YAML file for each document.

The six graded functions are:
    load_documents, build_zero_shot_prompt, build_few_shot_prompt,
    build_chain_of_thought_prompt, extract_kdes, dump_llm_outputs
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

PROMPT_TYPES = ("zero-shot", "few-shot", "chain-of-thought")
MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 2000
DESCRIPTION_CHARS = 500

_TITLE_START = re.compile(r"^(\d+(?:\.\d+)+)\s+(\S.*)$")
_ASSESSMENT = re.compile(r"\((Automated|Manual)\)\s*$")
_SECTION_HEAD = re.compile(
    r"^(Description|Rationale|Impact|Audit|Remediation|Default Value|References|"
    r"CIS Controls|Additional Information|Profile Applicability):\s*$"
)
_PAGE_FOOTER = re.compile(r"^(Page \d+|Internal Only - General)$")


class DocumentValidationError(ValueError):
    """Raised when an input file is not a usable CIS benchmark PDF."""


@dataclass
class Recommendation:
    rec_id: str
    title: str  # title text without the "(Automated)" / "(Manual)" mark
    assessment: str
    description: str

    @property
    def requirement(self) -> str:
        return self.title


@dataclass
class Document:
    path: Path
    name: str  # file stem, used in output file names
    benchmark_version: str
    recommendations: list[Recommendation] = field(default_factory=list)


# --------------------------------------------------------------------------
# PDF text helpers
# --------------------------------------------------------------------------
def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise DocumentValidationError(f"{path.name}: encrypted PDFs are not supported")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise DocumentValidationError(f"{path.name}: too many pages ({len(reader.pages)})")
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except PdfReadError as exc:
        raise DocumentValidationError(f"{path.name}: not a readable PDF ({exc})") from exc


def parse_recommendations(text: str) -> list[Recommendation]:
    """Split benchmark text into recommendations.

    Each recommendation in a CIS benchmark has a numbered title that ends in
    "(Automated)" or "(Manual)", and the next line is "Profile Applicability:".
    """
    lines = [ln.strip() for ln in text.splitlines()]
    recs: list[Recommendation] = []
    for i, line in enumerate(lines):
        if not line.startswith("Profile Applicability:"):
            continue
        # The title is on the 1-5 lines above. Walk up to its numbered start.
        for j in range(i - 1, max(i - 6, -1), -1):
            m = _TITLE_START.match(lines[j])
            if m:
                full = " ".join(" ".join(lines[j:i]).split())
                rec_id = m.group(1)
                rest = full[len(rec_id):].strip()
                am = _ASSESSMENT.search(rest)
                assessment = am.group(1) if am else ""
                title = _ASSESSMENT.sub("", rest).strip()
                recs.append(Recommendation(rec_id, title, assessment, _description(lines, i)))
                break
    return recs


def _description(lines: list[str], start: int) -> str:
    out: list[str] = []
    in_desc = False
    for line in lines[start + 1:]:
        if line == "Description:":
            in_desc = True
            continue
        if in_desc:
            if _SECTION_HEAD.match(line):
                break
            if line and not _PAGE_FOOTER.match(line):
                out.append(line)
        if sum(len(x) for x in out) > DESCRIPTION_CHARS * 2:
            break
    text = " ".join(" ".join(out).split())
    return text[:DESCRIPTION_CHARS]


# --------------------------------------------------------------------------
# Function 1: input validation
# --------------------------------------------------------------------------
def _validate_pdf_path(raw) -> Path:
    if not isinstance(raw, (str, Path)) or not str(raw).strip():
        raise DocumentValidationError(f"input path must be a non-empty string, got {raw!r}")
    if "\x00" in str(raw):
        raise DocumentValidationError("input path contains a NUL byte")
    path = Path(raw).expanduser()
    if not path.exists():
        raise DocumentValidationError(f"{path}: file does not exist")
    if not path.is_file():
        raise DocumentValidationError(f"{path}: not a regular file")
    if path.suffix.lower() != ".pdf":
        raise DocumentValidationError(f"{path}: expected a .pdf file")
    size = path.stat().st_size
    if size == 0:
        raise DocumentValidationError(f"{path}: file is empty")
    if size > MAX_PDF_BYTES:
        raise DocumentValidationError(f"{path}: file is larger than {MAX_PDF_BYTES} bytes")
    with path.open("rb") as fh:
        if not fh.read(1024).lstrip().startswith(b"%PDF-"):
            raise DocumentValidationError(f"{path}: file does not start with a PDF header")
    return path.resolve()


def load_documents(path_a, path_b) -> tuple[Document, Document]:
    """Validate the two input PDFs and parse their recommendations.

    Checks: path type, existence, regular file, .pdf extension, size limits,
    PDF header bytes, readable and not encrypted, and at least one
    recommendation found. Raises DocumentValidationError on any failure.
    """
    docs = []
    for raw in (path_a, path_b):
        path = _validate_pdf_path(raw)
        text = _pdf_text(path)
        recs = parse_recommendations(text)
        if not recs:
            raise DocumentValidationError(
                f"{path.name}: no CIS recommendations found; is this a CIS benchmark PDF?"
            )
        vm = re.search(r"\bv(\d+\.\d+\.\d+)\b", text[:2000])
        docs.append(Document(path, path.stem, vm.group(1) if vm else "unknown", recs))
        log.info("%s: CIS v%s, %d recommendations", path.name, docs[-1].benchmark_version, len(recs))
    return docs[0], docs[1]


# --------------------------------------------------------------------------
# Functions 2-4: prompt construction
# --------------------------------------------------------------------------
_TASK = (
    "You read security requirements from the CIS Docker Benchmark. "
    "A key data element (KDE) is the Docker component, resource or setting "
    "that a requirement is about, for example 'docker daemon', 'container', "
    "'image', 'docker.sock' or '/etc/docker'."
)
_FORMAT = "Answer with one line in this format and nothing else:\nELEMENT: <key data element, 1 to 4 words>"


def _rec_block(rec: Recommendation) -> str:
    return f"Requirement: {rec.title}\nDescription: {rec.description}"


FEW_SHOT_EXAMPLES = [
    (
        "Ensure that the Docker socket file ownership is set to root:docker",
        "The Docker socket docker.sock is owned by root and group docker.",
        "docker.sock",
    ),
    (
        "Ensure that containers use only trusted base images",
        "Ensure that the container image is written either from scratch or is based on "
        "another established and trusted base image downloaded over a secure channel.",
        "image",
    ),
    (
        "Ensure that the memory usage for containers is limited",
        "By default, all containers on a Docker host share resources equally.",
        "container",
    ),
]


def build_zero_shot_prompt(rec: Recommendation) -> str:
    """Zero-shot prompt: the task and format only, with no examples."""
    return f"{_TASK}\n\nWhat is the key data element of this requirement?\n\n{_rec_block(rec)}\n\n{_FORMAT}"


def build_few_shot_prompt(rec: Recommendation) -> str:
    """Few-shot prompt: the task, three solved examples, then the requirement."""
    shots = "\n\n".join(
        f"Requirement: {t}\nDescription: {d}\nELEMENT: {e}" for t, d, e in FEW_SHOT_EXAMPLES
    )
    return (
        f"{_TASK}\n\nHere are examples:\n\n{shots}\n\n"
        f"Now do the same for this requirement.\n\n{_rec_block(rec)}\n\n{_FORMAT}"
    )


def build_chain_of_thought_prompt(rec: Recommendation) -> str:
    """Chain-of-thought prompt: the model reasons in steps, then gives the answer."""
    return (
        f"{_TASK}\n\n{_rec_block(rec)}\n\n"
        "Think step by step:\n"
        "1. What does the requirement tell the user to check or change?\n"
        "2. Which Docker component, file or setting holds that check?\n"
        "3. Give the shortest common name for that component.\n\n"
        "Write at most three short reasoning lines, then end with one line in this format:\n"
        "ELEMENT: <key data element, 1 to 4 words>"
    )


PROMPT_BUILDERS = {
    "zero-shot": build_zero_shot_prompt,
    "few-shot": build_few_shot_prompt,
    "chain-of-thought": build_chain_of_thought_prompt,
}
MAX_NEW_TOKENS = {"zero-shot": 24, "few-shot": 24, "chain-of-thought": 128}


# --------------------------------------------------------------------------
# Function 5: KDE extraction with the LLM
# --------------------------------------------------------------------------
_ELEMENT_LINE = re.compile(r"ELEMENT\s*[:\-]\s*(.+)", re.IGNORECASE)


def normalize_element(raw: str) -> str:
    """Take the model's answer and return a clean, lower-case element name."""
    raw = raw or ""
    matches = _ELEMENT_LINE.findall(raw)
    if matches:
        text = matches[-1]
    elif raw.strip() and not re.match(r"^\s*1[.)]", raw):
        # No "ELEMENT:" label: use the first line, unless it is the start of
        # a numbered reasoning list (a chain-of-thought answer that stopped early).
        text = raw.strip().splitlines()[0]
    else:
        text = ""
    text = re.sub(r"[`*\"<>]", "", text).strip().lower()
    text = re.sub(r"^(the|a|an)\s+", "", text)
    text = text.rstrip(" .,:;")
    if len(text) > 1:
        text = text.rstrip("/")  # "/etc/docker/" and "/etc/docker" are one element
    words = text.split()
    if not words:
        return "unclassified"
    return " ".join(words[:6])


def extract_kdes(doc: Document, llm, prompt_type: str, out_dir: Path | None = None):
    """Identify KDEs in one document with one prompt type.

    Returns (kdes, records):
      kdes    -- {"element1": {"name": ..., "requirements": [...]}, ...}
      records -- one dict per LLM call, for dump_llm_outputs()
    If out_dir is given, kdes is also saved as <out_dir>/<doc.name>-kdes.yaml.
    """
    if prompt_type not in PROMPT_BUILDERS:
        raise ValueError(f"unknown prompt type {prompt_type!r}; use one of {PROMPT_TYPES}")
    build = PROMPT_BUILDERS[prompt_type]
    prompts = [build(r) for r in doc.recommendations]
    outputs = llm.generate(prompts, max_new_tokens=MAX_NEW_TOKENS[prompt_type])

    models = getattr(llm, "last_models", None) or [getattr(llm, "model_id", "unknown")] * len(outputs)

    grouped: dict[str, list[str]] = {}
    records = []
    for rec, prompt, output, model in zip(doc.recommendations, prompts, outputs, models):
        name = normalize_element(output)
        reqs = grouped.setdefault(name, [])
        if rec.requirement not in reqs:
            reqs.append(rec.requirement)
        records.append(
            {
                "llm_name": model,
                "document": doc.name,
                "recommendation": rec.rec_id,
                "prompt": prompt,
                "prompt_type": prompt_type,
                "output": output,
            }
        )

    kdes = {
        f"element{i}": {"name": name, "requirements": sorted(grouped[name])}
        for i, name in enumerate(sorted(grouped), start=1)
    }
    if out_dir is not None:
        save_kdes_yaml(kdes, Path(out_dir) / f"{doc.name}-kdes.yaml")
    return kdes, records


def save_kdes_yaml(kdes: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        yaml.safe_dump(kdes, fh, sort_keys=False, allow_unicode=True, width=120)
    return path


# --------------------------------------------------------------------------
# Function 6: LLM output log
# --------------------------------------------------------------------------
def dump_llm_outputs(records: list[dict], path: Path) -> Path:
    """Write every LLM call to a text file in the format the spec asks for."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in records:
            fh.write("*LLM Name*\n")
            fh.write(f"{r['llm_name']}\n")
            fh.write("*Prompt Used*\n")
            fh.write(f"{r['prompt']}\n")
            fh.write("*Prompt Type*\n")
            fh.write(f"{r['prompt_type']}\n")
            fh.write("*LLM Output*\n")
            fh.write(f"{r['output']}\n")
            fh.write("\n" + "-" * 72 + "\n\n")
    return path
