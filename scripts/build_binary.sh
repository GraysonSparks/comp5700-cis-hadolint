#!/usr/bin/env bash
# Build the single-file `cisdiff` binary with PyInstaller (Task-4).
#
# The build uses a separate venv (.venv-build) with the CPU-only build of
# torch. The CUDA build would make the binary several GB larger. Gemma-3-1B
# is small, so it runs on CPU in about 1-3 minutes for each PDF pair.
#
# Output: dist/cisdiff  (Hadolint and the rule data are inside it)
set -euo pipefail
cd "$(dirname "$0")/.."

[ -x bin/hadolint ] || scripts/get_hadolint.sh

uv venv --quiet --allow-existing --python 3.12 .venv-build
grep -vE '^(nvidia-|cuda-|triton==)' requirements.txt > .venv-build/requirements-cpu.txt
uv pip install --quiet --python .venv-build/bin/python \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple \
    --index-strategy unsafe-best-match \
    -r .venv-build/requirements-cpu.txt
uv pip install --quiet --python .venv-build/bin/python --no-deps .

.venv-build/bin/pyinstaller --noconfirm --clean --onefile --name cisdiff \
    --add-data "src/cisdiff/data:cisdiff/data" \
    --add-binary "bin/hadolint:bin" \
    --collect-submodules transformers.models.gemma3 \
    --collect-data transformers \
    --exclude-module matplotlib --exclude-module tkinter \
    cisdiff_main.py

ls -lh dist/cisdiff
dist/cisdiff --help
