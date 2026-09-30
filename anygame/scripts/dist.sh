#!/usr/bin/env bash
# Build everything that ships: the Python wheel (the CLI / desktop application) and the Chrome extension zip.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pip install -q build
python -m build --wheel --outdir dist/ .
( cd ext && npm ci --silent && npm run zip --silent )
ls -la dist/*.whl ext/anygame-extension.zip
echo "install:  pip install dist/anygame-*.whl'[desktop,stream]'   ·   load ext/anygame-extension.zip unpacked in chrome://extensions"
