#!/usr/bin/env bash
# Download the Hadolint binary to ./bin/hadolint and check its SHA-256.
set -euo pipefail
VERSION="v2.15.1"
SHA256="c7187db94eeeeca956519a6af171adc31453941a1e777961f6e680f697c8c507"
URL="https://github.com/hadolint/hadolint/releases/download/${VERSION}/hadolint-linux-x86_64"

cd "$(dirname "$0")/.."
mkdir -p bin
curl -fsSL -o bin/hadolint.tmp "$URL"
echo "${SHA256}  bin/hadolint.tmp" | sha256sum -c -
chmod +x bin/hadolint.tmp
mv bin/hadolint.tmp bin/hadolint
bin/hadolint --version
