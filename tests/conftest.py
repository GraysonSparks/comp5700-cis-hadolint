"""Shared test fixtures.

The tests do not use the real CIS PDFs (CIS licenses them, so they are not
in the repository) or the real LLM (too large for CI). Instead:
  * make_pdf() writes a small PDF that has the same structure as a CIS benchmark.
  * FakeLLM gives fixed answers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SAMPLE_LINES = [
    "CIS Docker Benchmark",
    "v9.9.9 - 01-01-2026",
    "1.1.1 Ensure a separate partition for containers has been created",
    "(Manual)",
    "Profile Applicability:",
    "Level 1 - Docker - Linux",
    "Description:",
    "All Docker containers and their data is stored under /var/lib/docker.",
    "Rationale:",
    "This directory could fill up quickly.",
    "4.1 Ensure that a user for the container has been created (Manual)",
    "Profile Applicability:",
    "Level 1 - Docker - Linux",
    "Description:",
    "Containers should run as a non-root user.",
    "Rationale:",
    "Running as root is risky.",
]


def _pdf_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(path: Path, lines: list[str]) -> Path:
    """Write a valid one-page PDF with one text line for each item in `lines`."""
    ops = ["BT", "/F1 10 Tf", "12 TL", "40 780 Td"]
    for line in lines:
        ops.append(f"({_pdf_escape(line)}) Tj T*")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    path.write_bytes(bytes(out))
    return path


class FakeLLM:
    """Stands in for GemmaLLM. Answers by keyword, like a perfect model would."""

    model_id = "fake-gemma"

    def __init__(self):
        self.calls = []

    def generate(self, prompts, max_new_tokens=None):
        prompts = list(prompts)
        self.calls.append(prompts)
        outs = []
        for p in prompts:
            req = p.rsplit("Requirement:", 1)[-1]
            if "partition" in req:
                outs.append("ELEMENT: /var/lib/docker")
            elif "user" in req:
                outs.append("Reasoning line\nELEMENT: Container User")
            else:
                outs.append("ELEMENT: docker daemon")
        return outs


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    return make_pdf(tmp_path / "docker-cis-sample.pdf", SAMPLE_LINES)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()
