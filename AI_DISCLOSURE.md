## Generative AI Disclosure

The author would like to acknowledge the use of Claude (Opus 5.5), a language
model developed by Anthropic, in the preparation of this project. Claude was
used in the following way(s) in this project:

- Reading the CIS Docker Benchmark PDFs to find their structure, and writing
  the parser that splits each PDF into its numbered recommendations
- Writing the first version of the code for Task-1 (prompt builders, the
  Gemma-3-1B wrapper, KDE grouping and the LLM output log), Task-2 (YAML
  comparison) and Task-3 (the CIS-to-Hadolint rule map, the Hadolint runner
  and the CSV summary)
- Writing the 13 test cases, the GitHub Actions workflow, the PyInstaller
  build script and the README
- Choosing and downloading the 19 public Dockerfiles in the fallback set,
  and checking their licenses (`src/cisdiff/data/sample-dockerfiles/SOURCES.md`)
- Running the full pipeline on the five required input pairs and checking
  the detected differences against a manual diff of the recommendation titles

Gemma-3-1B (`google/gemma-3-1b-it`) is the LLM that the tool itself uses to
extract key data elements, as the project specification requires. Its
prompts are in `PROMPT.md` and all of its outputs are in `llm-outputs.txt`.

The author did the following work:

- Made the design decisions for the project, including working alone, the
  fallback set of public Dockerfiles when `dockerfiles.zip` is not
  available, and the automatic CPU fallback for Gemma-3-1B
- Ran the full pipeline and the PyInstaller binary, and checked the
  outputs for each of the five input pairs
