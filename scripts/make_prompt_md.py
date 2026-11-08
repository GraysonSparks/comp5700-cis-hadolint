"""Write PROMPT.md from the prompt builders in src/cisdiff/extractor.py."""

from pathlib import Path

from cisdiff.extractor import (
    Recommendation,
    build_chain_of_thought_prompt,
    build_few_shot_prompt,
    build_zero_shot_prompt,
)

REC = Recommendation("{id}", "{requirement title}", "Manual", "{description, first 500 characters}")

lines = [
    "# Prompts used in Task-1",
    "",
    "The extractor sends one prompt for each CIS recommendation to Gemma-3-1B (`google/gemma-3-1b-it`, chat template, greedy decoding).",
    "In each template, `{requirement title}` and `{description, first 500 characters}` are replaced with text from the PDF.",
    "The model answers with a line `ELEMENT: <name>`. `normalize_element()` in `src/cisdiff/extractor.py` reads that line.",
    "",
    "Run `uv run python scripts/make_prompt_md.py` to make this file again after a prompt change.",
    "",
]
for section, build in [
    ("zero-shot", build_zero_shot_prompt),
    ("few-shot", build_few_shot_prompt),
    ("chain-of-thought", build_chain_of_thought_prompt),
]:
    lines += [f"## {section}", "", "```text", build(REC), "```", ""]

Path(__file__).resolve().parents[1].joinpath("PROMPT.md").write_text("\n".join(lines))
print("wrote PROMPT.md")
