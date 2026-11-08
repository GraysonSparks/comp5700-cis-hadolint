"""Task-2 tests: one test for each of the three comparator functions."""

import csv

import pytest
import yaml

from cisdiff import comparator

KDES_A = {
    "docker daemon": {"Ensure TLS authentication for Docker daemon is configured"},
    "docker.socket": {"Ensure auditing is configured for Docker files and directories - docker.socket"},
}
KDES_B = {
    "docker daemon": {
        "Ensure TLS authentication for Docker daemon is configured",
        "Ensure devicemapper storage driver is not used",
    },
    "docker.sock": {"Ensure auditing is configured for Docker files and directories - docker.sock"},
}


def _write_yaml(path, kdes):
    data = {
        f"element{i}": {"name": n, "requirements": sorted(r)}
        for i, (n, r) in enumerate(sorted(kdes.items()), start=1)
    }
    path.write_text(yaml.safe_dump(data))
    return path


def test_load_kde_yamls(tmp_path):
    a = _write_yaml(tmp_path / "a-kdes.yaml", KDES_A)
    b = _write_yaml(tmp_path / "b-kdes.yaml", KDES_B)
    loaded_a, loaded_b = comparator.load_kde_yamls(a, b)
    assert loaded_a == KDES_A and loaded_b == KDES_B

    bad = tmp_path / "bad.yaml"
    bad.write_text("element1:\n  requirements: [x]\n")  # no name
    unsafe = tmp_path / "unsafe.yaml"
    unsafe.write_text("!!python/object/apply:os.system ['echo hi']\n")
    for path in [bad, unsafe, tmp_path / "missing.yaml", tmp_path / "a.txt"]:
        with pytest.raises(comparator.KDEFileError):
            comparator.load_kde_yamls(a, path)


def test_compare_element_names(tmp_path):
    out = comparator.compare_element_names(KDES_A, KDES_B, tmp_path / "names.txt")
    assert out.read_text().splitlines() == ["docker.sock", "docker.socket"]

    same = comparator.compare_element_names(KDES_A, KDES_A, tmp_path / "same.txt")
    assert same.read_text().strip() == comparator.NO_NAME_DIFF


def test_compare_element_requirements(tmp_path):
    out = comparator.compare_element_requirements(KDES_A, KDES_B, tmp_path / "reqs.txt")
    rows = list(csv.reader(out.read_text().splitlines()))
    assert rows == [
        ["docker daemon", "Ensure devicemapper storage driver is not used"],
        ["docker.sock", "Ensure auditing is configured for Docker files and directories - docker.sock"],
        ["docker.socket", "Ensure auditing is configured for Docker files and directories - docker.socket"],
    ]

    same = comparator.compare_element_requirements(KDES_B, KDES_B, tmp_path / "same.txt")
    assert same.read_text().strip() == comparator.NO_REQ_DIFF
