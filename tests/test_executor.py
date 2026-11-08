"""Task-3 tests: one test for each of the four executor functions."""

import os
import zipfile

import pandas as pd
import pytest

from cisdiff import comparator, executor
from cisdiff.executor import Differences

DOCKERFILE = """FROM ubuntu:latest
RUN apt-get update && apt-get install curl
ADD app.py /app/app.py
USER root
"""


@pytest.fixture
def dockerfiles_zip(tmp_path):
    path = tmp_path / "dockerfiles.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("repo1/Dockerfile", DOCKERFILE)
        zf.writestr("repo2/Dockerfile.dev", "FROM python:3.12-slim\nUSER app\n")
    return path


def test_load_difference_files(tmp_path):
    names = tmp_path / "names.txt"
    reqs = tmp_path / "reqs.txt"
    names.write_text("docker.sock\ndocker.socket\n")
    reqs.write_text('docker daemon,"Ensure X, Y and Z"\ncontainer,Ensure that a user for the container has been created\n')
    diffs = executor.load_difference_files(names, reqs)
    assert diffs.names == ["docker.sock", "docker.socket"]
    assert diffs.requirements[0] == ("docker daemon", "Ensure X, Y and Z")
    assert diffs.any

    names.write_text(comparator.NO_NAME_DIFF + "\n")
    reqs.write_text(comparator.NO_REQ_DIFF + "\n")
    assert not executor.load_difference_files(names, reqs).any


def test_map_differences_to_rules(tmp_path):
    out = tmp_path / "rules.txt"
    executor.map_differences_to_rules(Differences([], []), out)
    assert out.read_text().strip() == executor.NO_DIFFERENCES

    diffs = Differences(["container user"], [("image", "Ensure that COPY is used instead of ADD in Dockerfiles")])
    rules = executor.map_differences_to_rules(diffs, out).read_text().split()
    assert {"DL3002", "DL3020"} <= set(rules)
    assert rules == sorted(rules)

    # A daemon-only change has no Dockerfile rule, so every DL rule is selected.
    daemon = Differences(["docker.sock"], [])
    rules = executor.map_differences_to_rules(daemon, out).read_text().split()
    assert len(rules) > 60 and all(r.startswith("DL") for r in rules)


def test_run_hadolint(tmp_path, dockerfiles_zip):
    try:
        executor.find_hadolint()
    except FileNotFoundError:
        if os.environ.get("CISDIFF_REQUIRE_HADOLINT"):
            raise  # in CI a missing Hadolint is a failure, not a skip
        pytest.skip("Hadolint is not installed")

    all_rules = tmp_path / "all.txt"
    all_rules.write_text(executor.NO_DIFFERENCES + "\n")
    df = executor.run_hadolint(all_rules, dockerfiles_zip)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == executor.SCAN_COLUMNS
    found = set(df.loc[df.FilePath == "repo1/Dockerfile", "RULEID"])
    assert {"DL3007", "DL3020", "DL3002", "DL3008"} <= found
    assert "DL3057" in found  # off by default, but "all rules" turns it on

    some_rules = tmp_path / "some.txt"
    some_rules.write_text("DL3020\n")
    df = executor.run_hadolint(some_rules, dockerfiles_zip)
    assert set(df.RULEID) == {"DL3020"}

    # A zip with a path-traversal entry is rejected.
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../escape/Dockerfile", "FROM scratch\n")
    with pytest.raises(ValueError):
        executor.run_hadolint(all_rules, evil)


def test_write_results_csv(tmp_path):
    scan = pd.DataFrame(
        [
            ["a/Dockerfile", "DL3020", "error", None, 3, "Use COPY"],
            ["a/Dockerfile", "DL3020", "error", None, 7, "Use COPY"],
            ["a/Dockerfile", "SC2086", "info", None, 2, "Double quote"],
            ["b/Dockerfile", "DL3007", "warning", None, 1, "latest"],
        ],
        columns=executor.SCAN_COLUMNS,
    )
    out = executor.write_results_csv(scan, tmp_path / "results.csv")
    df = pd.read_csv(out)
    assert list(df.columns) == executor.CSV_HEADERS
    rows = df.values.tolist()
    assert ["a/Dockerfile", "Error", "DL3020", 2] in rows
    assert ["a/Dockerfile", "Info", "SC2086", 1] in rows  # ShellCheck: reported level
    assert ["b/Dockerfile", "Warning", "DL3007", 1] in rows

    empty = executor.write_results_csv(pd.DataFrame(columns=executor.SCAN_COLUMNS), tmp_path / "e.csv")
    assert empty.read_text().strip() == ",".join(executor.CSV_HEADERS)
