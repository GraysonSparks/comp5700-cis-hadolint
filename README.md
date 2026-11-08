# cisdiff: CIS Docker Benchmark change detector

COMP 5700 Secure Software Process, Fall 2026, semester project.

`cisdiff` reads two versions of the CIS Docker Benchmark PDF. It finds the security requirements that changed between them and runs the Hadolint rules that match those changes on a set of Dockerfiles.

## Team

| Name | Banner ID | Auburn email |
|---|---|---|
| Grayson Sparks | `904294398` | `grs0031@auburn.edu` |

## LLM

Task-1 uses **Gemma-3-1B**, instruction-tuned: [`google/gemma-3-1b-it`](https://huggingface.co/google/gemma-3-1b-it).

The Google repository is gated. If your Hugging Face account cannot open it, the tool uses [`unsloth/gemma-3-1b-it`](https://huggingface.co/unsloth/gemma-3-1b-it). That is a public copy of the same weights. The tool writes a warning, and `llm-outputs.txt` records the model that was really used.

## How it works

| Task | Module | What it does |
|---|---|---|
| 1. Extractor | `src/cisdiff/extractor.py` | Validates the two PDFs and splits each one into its numbered recommendations (117–118). Gemma names the key data element (KDE) of each recommendation with a zero-shot, a few-shot and a chain-of-thought prompt. Recommendations with the same KDE are grouped and saved to `<pdf-name>-kdes.yaml`. |
| 2. Comparator | `src/cisdiff/comparator.py` | Compares the two YAML files. Writes the KDE names that are in only one file, and the `NAME,REQU` tuples that are not in both files. |
| 3. Executor | `src/cisdiff/executor.py` | Maps the differences to Hadolint rules with the patterns in `src/cisdiff/data/rule_map.yaml`. Runs Hadolint on the Dockerfiles, and writes `hadolint-results.csv` with `FilePath, DefaultSeverity, RULEID, COUNT`. |
| 4. Repository | this repo | `requirements.txt`, the GitHub Actions workflow, the PyInstaller binary and this README. |

Design decisions:

- **One prompt for each recommendation.** A 280-page PDF is too long for a 1B model. The parser splits the text at each "Profile Applicability:" line, and the prompt holds only one recommendation title and its description.
- **Greedy decoding and a cache.** The same recommendation text always gives the same KDE name, so an unchanged requirement does not show as a false difference. Answers are cached in `~/.cache/cisdiff/llm-cache.json`. Set `CISDIFF_CACHE` to use a different folder.
- **Requirements are titles without numbers.** CIS v1.8.0 added recommendation 2.7, and the numbers of 2.7–2.18 moved down by one. If the YAML used the numbers, each renumbered item would show as a false difference.
- **YAML from the few-shot prompt.** All three prompt types run, and all of their answers are in `llm-outputs.txt`. The YAML files use the few-shot answers, because they gave the most specific KDE names. Use `--prompt-type` to change this.
- **Differences that Hadolint cannot check.** Hadolint reads only Dockerfiles. Many CIS changes (for example `docker.sock` auditing, or the devicemapper storage driver) are about the Docker host or daemon. If no pattern in `rule_map.yaml` matches a difference, the tool selects all DL rules. It does not select zero rules.
- **Safe input handling.** The tool checks the PDF type, size and header bytes. It reads YAML with `yaml.safe_load`. It extracts the zip with checks against path traversal, symlinks and zip bombs. It starts Hadolint without a shell.

## Results on the course PDFs

| Input | Element-name differences | Hadolint rules |
|---|---|---|
| v0 (1.6.0) vs v1 (1.7.0) | none; requirement change `docker.socket` → `docker.sock` | all DL rules |
| v0 vs v2 (1.8.0) | `devicemapper`, `docker data root`, plus the change above | all DL rules |
| v1 vs v2 | `devicemapper` (new 2.7), `docker data root` | all DL rules |
| v1 vs v1 | none | `NO DIFFERENCES FOUND` → all rules |
| v2 vs v2 | none | `NO DIFFERENCES FOUND` → all rules |

## Run from source

Requirements: Linux x86_64, Python 3.12, about 3 GB free disk space. An NVIDIA GPU is optional.

1. Install the dependencies:
   ```bash
   python3.12 -m venv comp5700-venv
   source comp5700-venv/bin/activate
   pip install -r requirements.txt
   pip install --no-deps -e .
   ```
2. Download Hadolint to `bin/hadolint`. The script checks the SHA-256 of the file.
   ```bash
   scripts/get_hadolint.sh
   ```
3. Optional: if you accepted the Gemma license on Hugging Face, set your token.
   ```bash
   export HF_TOKEN=hf_...
   ```
4. Put the CIS PDFs in `inputs/` and the course `dockerfiles.zip` in the repo folder.
5. Run the tool:
   ```bash
   cisdiff inputs/docker-cis-v0.pdf inputs/docker-cis-v1.pdf --dockerfiles dockerfiles.zip
   ```

The outputs go to `outputs/<pdf-a>_vs_<pdf-b>/`:

| File | Task |
|---|---|
| `<pdf>-kdes.yaml` (two files) | 1 |
| `llm-outputs.txt` | 1 |
| `element-name-differences.txt` | 2 |
| `element-requirement-differences.txt` | 2 |
| `hadolint-rules.txt` | 3 |
| `hadolint-results.csv` | 3 |

If you give the same PDF two times, the YAML files get `-1` and `-2` suffixes.

The tool uses the GPU only if at least 4 GB of GPU memory is free. If another program (for example Ollama) uses the GPU, the tool uses the CPU and writes a warning. To choose the device yourself, set `CISDIFF_DEVICE=cpu` or `CISDIFF_DEVICE=cuda`.

## Run the binary (for the TA)

Download `cisdiff` from the latest [GitHub Release](../../releases). Hadolint and the rule data are inside the binary. The model downloads from Hugging Face on the first run (about 2 GB).

1. Make a virtual environment and activate it:
   ```bash
   python3 -m venv comp5700-venv
   source comp5700-venv/bin/activate
   ```
2. Make the binary executable:
   ```bash
   chmod +x cisdiff
   ```
3. Run the five inputs. Put `dockerfiles.zip` in the current folder, or add `--dockerfiles <path>`.
   ```bash
   ./cisdiff docker-cis-v0.pdf docker-cis-v1.pdf   # Input-1
   ./cisdiff docker-cis-v0.pdf docker-cis-v2.pdf   # Input-2
   ./cisdiff docker-cis-v1.pdf docker-cis-v2.pdf   # Input-3
   ./cisdiff docker-cis-v1.pdf docker-cis-v1.pdf   # Input-4
   ./cisdiff docker-cis-v2.pdf docker-cis-v2.pdf   # Input-5
   ```

The binary uses CPU-only torch. Each new PDF takes about 1–3 minutes on a CPU. Repeated PDFs use the cache.

To build the binary again, run `scripts/build_binary.sh`.

## Tests

There is one test case for each of the 13 functions: 6 in Task-1, 3 in Task-2 and 4 in Task-3.

```bash
pytest -v
```

The tests do not need the CIS PDFs or the LLM. `tests/conftest.py` makes a small PDF with the CIS structure and uses a fake LLM. `test_run_hadolint` needs Hadolint. If Hadolint is not installed, the test is skipped on your computer. In CI, the test fails.

GitHub Actions (`.github/workflows/tests.yml`) runs all tests on each push and pull request, also from forks. The spec says the tests must run when a user types `git status`. `git status` is a local command, and GitHub does not know when someone runs it, so push and pull request are the closest events that GitHub can see. The test logs are in each workflow run and in its `test-logs` artifact.

## Files not in this repository

- **CIS PDFs:** CIS licenses the benchmarks, so they are not in this public repo. Get them from Canvas.
- **`dockerfiles.zip`:** the course SharePoint file needs an Auburn login.

## AI disclosure

See [AI_DISCLOSURE.md](AI_DISCLOSURE.md).
