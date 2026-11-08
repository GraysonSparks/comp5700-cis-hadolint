"""Task-2: Comparator.

Compares the two KDE YAML files from Task-1.

The three graded functions are:
    load_kde_yamls, compare_element_names, compare_element_requirements
"""

from __future__ import annotations

import csv
from pathlib import Path

import yaml

NO_NAME_DIFF = "NO DIFFERENCES IN REGARDS TO ELEMENT NAMES"
NO_REQ_DIFF = "NO DIFFERENCES IN REGARDS TO ELEMENT REQUIREMENTS"
MAX_YAML_BYTES = 10 * 1024 * 1024


class KDEFileError(ValueError):
    """Raised when a YAML input is not a valid KDE file from Task-1."""


def _load_one(path) -> dict[str, set[str]]:
    path = Path(path)
    if not path.is_file():
        raise KDEFileError(f"{path}: file does not exist")
    if path.suffix.lower() not in (".yaml", ".yml"):
        raise KDEFileError(f"{path}: expected a .yaml file")
    if path.stat().st_size > MAX_YAML_BYTES:
        raise KDEFileError(f"{path}: file is too large")
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise KDEFileError(f"{path}: not valid YAML ({exc})") from exc
    if not isinstance(data, dict):
        raise KDEFileError(f"{path}: top level must be a mapping of elements")

    result: dict[str, set[str]] = {}
    for key, entry in data.items():
        if not isinstance(entry, dict) or "name" not in entry:
            raise KDEFileError(f"{path}: {key} must have a 'name' field")
        reqs = entry.get("requirements") or []
        if not isinstance(reqs, list):
            raise KDEFileError(f"{path}: {key}.requirements must be a list")
        name = str(entry["name"]).strip()
        result.setdefault(name, set()).update(str(r).strip() for r in reqs)
    return result


def load_kde_yamls(path_a, path_b) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Load and validate the two YAML files from Task-1.

    Returns two maps of element name -> set of requirements. Uses
    yaml.safe_load, so the files cannot run code.
    """
    return _load_one(path_a), _load_one(path_b)


def compare_element_names(kdes_a: dict, kdes_b: dict, out_path) -> Path:
    """Write the element names that are in only one of the two files.

    One name on each line. If both files have the same names, the file
    holds NO_NAME_DIFF.
    """
    diff = sorted(set(kdes_a) ^ set(kdes_b))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(("\n".join(diff) if diff else NO_NAME_DIFF) + "\n")
    return out_path


def compare_element_requirements(kdes_a: dict, kdes_b: dict, out_path) -> Path:
    """Write NAME,REQU tuples for every requirement that is not in both files.

    This includes:
      * all requirements of an element that is in only one file, and
      * requirements that were added to or removed from a shared element.
    Lines use CSV quoting, so a comma in a requirement does not break the
    tuple. If there are no differences, the file holds NO_REQ_DIFF.
    """
    rows: list[tuple[str, str]] = []
    for name in sorted(set(kdes_a) | set(kdes_b)):
        reqs_a = kdes_a.get(name, set())
        reqs_b = kdes_b.get(name, set())
        for req in sorted(reqs_a ^ reqs_b):
            rows.append((name, req))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as fh:
        if rows:
            csv.writer(fh, lineterminator="\n").writerows(rows)
        else:
            fh.write(NO_REQ_DIFF + "\n")
    return out_path
