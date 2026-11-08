"""Task-1 tests: one test for each of the six extractor functions."""

import pytest
import yaml

from cisdiff import extractor
from cisdiff.extractor import DocumentValidationError, Recommendation

REC = Recommendation(
    rec_id="4.9",
    title="Ensure that COPY is used instead of ADD in Dockerfiles",
    assessment="Manual",
    description="Use COPY rather than ADD instructions in Dockerfiles.",
)


def test_load_documents(sample_pdf, tmp_path):
    doc_a, doc_b = extractor.load_documents(sample_pdf, str(sample_pdf))
    assert doc_a.name == "docker-cis-sample"
    assert doc_a.benchmark_version == "9.9.9"
    assert [r.rec_id for r in doc_a.recommendations] == ["1.1.1", "4.1"]
    assert doc_a.recommendations[0].title == "Ensure a separate partition for containers has been created"
    assert doc_a.recommendations[0].assessment == "Manual"
    assert "/var/lib/docker" in doc_a.recommendations[0].description
    assert len(doc_b.recommendations) == 2

    # Input validation: each bad input is rejected with a clear error.
    not_pdf = tmp_path / "notes.pdf"
    not_pdf.write_text("hello")
    wrong_ext = tmp_path / "doc.txt"
    wrong_ext.write_bytes(sample_pdf.read_bytes())
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    for bad in [tmp_path / "missing.pdf", tmp_path, not_pdf, wrong_ext, empty, "", None]:
        with pytest.raises(DocumentValidationError):
            extractor.load_documents(sample_pdf, bad)


def test_build_zero_shot_prompt():
    prompt = extractor.build_zero_shot_prompt(REC)
    assert isinstance(prompt, str)
    assert REC.title in prompt and REC.description in prompt
    assert "ELEMENT:" in prompt
    assert "Here are examples" not in prompt  # zero-shot: no examples


def test_build_few_shot_prompt():
    prompt = extractor.build_few_shot_prompt(REC)
    assert isinstance(prompt, str)
    assert REC.title in prompt
    # every example and its answer is in the prompt
    for title, _, element in extractor.FEW_SHOT_EXAMPLES:
        assert title in prompt and f"ELEMENT: {element}" in prompt
    # the requirement to classify comes after the examples
    assert prompt.index(REC.title) > prompt.index(extractor.FEW_SHOT_EXAMPLES[-1][0])


def test_build_chain_of_thought_prompt():
    prompt = extractor.build_chain_of_thought_prompt(REC)
    assert isinstance(prompt, str)
    assert REC.title in prompt
    assert "step by step" in prompt.lower()
    assert "1." in prompt and "2." in prompt and "3." in prompt
    assert prompt.rstrip().endswith("ELEMENT: <key data element, 1 to 4 words>")


def test_extract_kdes(sample_pdf, tmp_path, fake_llm):
    doc, _ = extractor.load_documents(sample_pdf, sample_pdf)
    kdes, records = extractor.extract_kdes(doc, fake_llm, "chain-of-thought", out_dir=tmp_path)

    names = {v["name"]: v["requirements"] for v in kdes.values()}
    assert names == {
        "/var/lib/docker": ["Ensure a separate partition for containers has been created"],
        "container user": ["Ensure that a user for the container has been created"],
    }
    assert list(kdes) == ["element1", "element2"]
    assert len(records) == 2 and records[0]["prompt_type"] == "chain-of-thought"

    saved = tmp_path / "docker-cis-sample-kdes.yaml"
    assert yaml.safe_load(saved.read_text()) == kdes

    with pytest.raises(ValueError):
        extractor.extract_kdes(doc, fake_llm, "one-shot")


def test_dump_llm_outputs(tmp_path):
    records = [
        {"llm_name": "google/gemma-3-1b-it", "prompt": "P1", "prompt_type": "zero-shot", "output": "ELEMENT: image"},
        {"llm_name": "google/gemma-3-1b-it", "prompt": "P2", "prompt_type": "few-shot", "output": "ELEMENT: container"},
    ]
    path = extractor.dump_llm_outputs(records, tmp_path / "llm-outputs.txt")
    text = path.read_text()
    assert text.count("*LLM Name*") == 2
    first = text.split("-" * 72)[0].strip().splitlines()
    assert first == [
        "*LLM Name*", "google/gemma-3-1b-it",
        "*Prompt Used*", "P1",
        "*Prompt Type*", "zero-shot",
        "*LLM Output*", "ELEMENT: image",
    ]
