"""Task-3: Executor.

Reads the Task-2 difference files, maps the differences to Hadolint rules,
runs Hadolint on the course Dockerfiles, and writes a CSV summary.

The four graded functions are:
    load_difference_files, map_differences_to_rules, run_hadolint,
    write_results_csv
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import pandas as pd
import yaml

from .comparator import NO_NAME_DIFF, NO_REQ_DIFF

log = logging.getLogger(__name__)

NO_DIFFERENCES = "NO DIFFERENCES FOUND"
CSV_HEADERS = ["FilePath", "DefaultSeverity", "RULEID", "COUNT"]
SCAN_COLUMNS = ["FilePath", "RULEID", "Level", "DefaultSeverity", "Line", "Message"]
_RULE_ID = re.compile(r"^(DL|SC)\d{4}$")

MAX_ZIP_MEMBERS = 200_000
MAX_ZIP_BYTES = 4 * 1024**3  # 4 GiB uncompressed
MAX_DOCKERFILE_BYTES = 1024**2
HADOLINT_BATCH = 400


@dataclass
class Differences:
    names: list[str]
    requirements: list[tuple[str, str]]

    @property
    def any(self) -> bool:
        return bool(self.names or self.requirements)


# --------------------------------------------------------------------------
# Data files shipped inside the package
# --------------------------------------------------------------------------
def _data_path(name: str) -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller binary
        return Path(sys._MEIPASS) / "cisdiff" / "data" / name
    return Path(resources.files("cisdiff") / "data" / name)


def fallback_dockerfiles() -> Path:
    """Return the folder of public Dockerfiles that ships with the tool.

    The CLI uses it only when the course dockerfiles.zip is not available.
    See data/sample-dockerfiles/SOURCES.md for the sources and licenses.
    """
    return _data_path("sample-dockerfiles")


def load_rule_catalog() -> dict[str, str]:
    """Return {rule_id: default severity} for every rule in the Hadolint README."""
    with _data_path("hadolint_rules.csv").open() as fh:
        return {row["rule_id"]: row["default_severity"] for row in csv.DictReader(fh)}


def load_rule_map() -> list[dict]:
    return yaml.safe_load(_data_path("rule_map.yaml").read_text())["mappings"]


# --------------------------------------------------------------------------
# Function 1: read the Task-2 outputs
# --------------------------------------------------------------------------
def _read_text(path) -> str:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"{path}: file does not exist")
    if path.stat().st_size > 50 * 1024**2:
        raise ValueError(f"{path}: file is too large")
    return path.read_text()


def load_difference_files(name_diff_path, req_diff_path) -> Differences:
    """Read the element-name and element-requirement difference files from Task-2."""
    name_text = _read_text(name_diff_path).strip()
    names = [] if name_text == NO_NAME_DIFF else [ln.strip() for ln in name_text.splitlines() if ln.strip()]

    req_text = _read_text(req_diff_path).strip()
    reqs: list[tuple[str, str]] = []
    if req_text != NO_REQ_DIFF:
        for row in csv.reader(req_text.splitlines()):
            if not row:
                continue
            if len(row) != 2:
                raise ValueError(f"{req_diff_path}: expected NAME,REQU but got {row!r}")
            reqs.append((row[0].strip(), row[1].strip()))
    return Differences(names, reqs)


# --------------------------------------------------------------------------
# Function 2: differences -> Hadolint rules
# --------------------------------------------------------------------------
def map_differences_to_rules(diffs: Differences, out_path, rule_map=None, catalog=None) -> Path:
    """Write NO_DIFFERENCES, or the Hadolint rule IDs that map to the differences.

    The mapping uses the regex patterns in data/rule_map.yaml. If there are
    differences but no pattern matches them, the file lists every DL rule.
    The CIS change is then outside what Hadolint checks, so the full scan
    is the safe default.
    """
    rule_map = rule_map if rule_map is not None else load_rule_map()
    catalog = catalog if catalog is not None else load_rule_catalog()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not diffs.any:
        out_path.write_text(NO_DIFFERENCES + "\n")
        return out_path

    texts = [n.lower() for n in diffs.names] + [f"{n} {r}".lower() for n, r in diffs.requirements]
    rules: set[str] = set()
    for entry in rule_map:
        pat = re.compile(entry["pattern"], re.IGNORECASE)
        if any(pat.search(t) for t in texts):
            rules.update(entry["rules"])

    if not rules:
        log.warning("Differences found, but none map to a Hadolint rule; selecting all DL rules.")
        rules = {r for r in catalog if r.startswith("DL")}

    unknown = sorted(r for r in rules if r not in catalog)
    if unknown:
        raise ValueError(f"rule_map.yaml names rules that are not in the catalog: {unknown}")
    out_path.write_text("\n".join(sorted(rules)) + "\n")
    return out_path


# --------------------------------------------------------------------------
# Function 3: run Hadolint
# --------------------------------------------------------------------------
def find_hadolint() -> list[str]:
    """Return the command that starts Hadolint.

    Search order: $HADOLINT_BIN, `hadolint` on PATH, the copy bundled in the
    PyInstaller binary, ./bin/hadolint, then the Docker image.
    """
    candidates = [os.environ.get("HADOLINT_BIN"), shutil.which("hadolint")]
    if getattr(sys, "frozen", False):
        candidates.append(str(Path(sys._MEIPASS) / "bin" / "hadolint"))
    candidates.append(str(Path(__file__).resolve().parents[2] / "bin" / "hadolint"))
    for c in candidates:
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return [c]
    if shutil.which("docker") and _docker_usable():
        return ["docker", "run", "--rm", "-i", "hadolint/hadolint:v2.15.1", "hadolint"]
    raise FileNotFoundError(
        "Hadolint not found. Install it (see README) or set HADOLINT_BIN to its path."
    )


def _docker_usable() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _safe_extract(zip_path: Path, dest: Path) -> None:
    """Extract a zip file with checks against path traversal and zip bombs."""
    dest = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        members = zf.infolist()
        if len(members) > MAX_ZIP_MEMBERS:
            raise ValueError(f"{zip_path}: too many entries ({len(members)})")
        if sum(m.file_size for m in members) > MAX_ZIP_BYTES:
            raise ValueError(f"{zip_path}: uncompressed size is too large")
        for m in members:
            target = (dest / m.filename).resolve()
            if not target.is_relative_to(dest):
                raise ValueError(f"{zip_path}: unsafe path in archive: {m.filename}")
            is_symlink = (m.external_attr >> 16) & 0o170000 == 0o120000
            if is_symlink:
                log.warning("Skipped symlink in archive: %s", m.filename)
                continue
            zf.extract(m, dest)


def _collect_dockerfiles(root: Path) -> list[Path]:
    files = [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
    files = [p for p in files if "__MACOSX" not in p.parts and not p.name.startswith(".")]
    named = [p for p in files if "dockerfile" in p.name.lower()]
    chosen = named or files
    return sorted(p for p in chosen if p.stat().st_size <= MAX_DOCKERFILE_BYTES)


def _read_selected_rules(rules_path) -> list[str] | None:
    """Return None for "all rules", else the rule IDs in the file."""
    text = _read_text(rules_path).strip()
    if text == NO_DIFFERENCES:
        return None
    rules = [ln.strip() for ln in text.splitlines() if ln.strip()]
    bad = [r for r in rules if not _RULE_ID.match(r)]
    if bad:
        raise ValueError(f"{rules_path}: not Hadolint rule IDs: {bad}")
    return rules


def run_hadolint(rules_path, dockerfiles, catalog=None, hadolint_cmd=None) -> pd.DataFrame:
    """Run Hadolint on a .zip or folder of Dockerfiles and return the findings.

    If the rules file holds NO_DIFFERENCES, all rules run (including rules
    that are off by default, such as DL3057). Otherwise only the listed
    rules run: every other catalog rule gets --ignore, and the results are
    also filtered, because Hadolint can report ShellCheck codes that are
    not in the catalog.
    """
    catalog = catalog if catalog is not None else load_rule_catalog()
    selected = _read_selected_rules(rules_path)
    cmd = list(hadolint_cmd or find_hadolint())
    uses_docker = cmd[0] == "docker"

    args = ["--format", "json", "--no-fail"]
    enabled = set(catalog) if selected is None else set(selected)
    # Rules with "Ignore" as default severity are off unless we raise them.
    for rule in sorted(enabled):
        if catalog.get(rule) == "Ignore":
            args += ["--info", rule]
    if selected is not None:
        for rule in sorted(set(catalog) - enabled):
            args += ["--ignore", rule]

    source = Path(dockerfiles)
    if not source.exists():
        raise FileNotFoundError(f"{source}: Dockerfile archive or folder does not exist")

    with tempfile.TemporaryDirectory(prefix="cisdiff-") as tmp:
        tmp_path = Path(tmp)
        if source.is_file():
            if not zipfile.is_zipfile(source):
                raise ValueError(f"{source}: expected a .zip file or a folder")
            root = tmp_path / "dockerfiles"
            _safe_extract(source, root)
        else:
            root = source.resolve()
        files = _collect_dockerfiles(root)
        if not files:
            raise ValueError(f"{source}: no Dockerfiles found")
        log.info("Running Hadolint on %d files (%s rules)", len(files),
                 "all" if selected is None else len(selected))

        env = dict(os.environ, XDG_CONFIG_HOME=str(tmp_path))  # ignore user config
        rows = []
        for start in range(0, len(files), HADOLINT_BATCH):
            batch = files[start:start + HADOLINT_BATCH]
            rows += _run_batch(cmd, args, batch, root, uses_docker, env, tmp_path)

    df = pd.DataFrame(rows, columns=SCAN_COLUMNS)
    df["DefaultSeverity"] = [
        catalog.get(rule) or str(level).capitalize()
        for rule, level in zip(df["RULEID"], df["Level"])
    ]
    if selected is not None:
        df = df[df["RULEID"].isin(selected)].reset_index(drop=True)
    return df


def _run_batch(cmd, args, files, root, uses_docker, env, cwd) -> list[dict]:
    if uses_docker:
        rel = [str(f.relative_to(root)) for f in files]
        full = cmd[:3] + ["-v", f"{root}:/work:ro", "-w", "/work"] + cmd[3:] + args + rel
    else:
        full = cmd + args + [str(f) for f in files]
    proc = subprocess.run(full, capture_output=True, text=True, env=env, cwd=cwd, timeout=1800)
    if proc.returncode != 0 and not proc.stdout.strip():
        raise RuntimeError(f"Hadolint failed (exit {proc.returncode}): {proc.stderr.strip()[:500]}")
    try:
        findings = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Hadolint output is not JSON: {proc.stderr[:500]}") from exc

    rows = []
    for f in findings:
        path = Path(f["file"])
        try:
            rel = str(path.relative_to(root)) if path.is_absolute() else str(path)
        except ValueError:
            rel = str(path)
        rows.append({
            "FilePath": rel,
            "RULEID": f["code"],
            "Level": f.get("level", ""),
            "Line": f.get("line"),
            "Message": f.get("message", ""),
        })
    return rows


# --------------------------------------------------------------------------
# Function 4: CSV summary
# --------------------------------------------------------------------------
def write_results_csv(scan: pd.DataFrame, out_path, catalog=None) -> Path:
    """Write FilePath, DefaultSeverity, RULEID, COUNT (one row per file and rule).

    DefaultSeverity comes from the Hadolint rule table. ShellCheck rules have
    no default in that table, so they use the level that Hadolint reported.
    """
    catalog = catalog if catalog is not None else load_rule_catalog()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if scan.empty:
        pd.DataFrame(columns=CSV_HEADERS).to_csv(out_path, index=False)
        return out_path

    df = scan.copy()
    if "DefaultSeverity" not in df or df["DefaultSeverity"].isna().any():
        df["DefaultSeverity"] = [
            catalog.get(rule) or str(level).capitalize()
            for rule, level in zip(df["RULEID"], df["Level"])
        ]
    summary = (
        df.groupby(["FilePath", "DefaultSeverity", "RULEID"], as_index=False)
        .size()
        .rename(columns={"size": "COUNT"})
        .sort_values(["FilePath", "RULEID"])
    )
    summary[CSV_HEADERS].to_csv(out_path, index=False)
    return out_path
