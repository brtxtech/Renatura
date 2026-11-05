#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv-atlas ]; then python3 -m venv .venv-atlas; fi
.venv-atlas/bin/python -m pip install -r requirements-atlas.txt
exec .venv-atlas/bin/python -m uvicorn pipeline.atlas.server:app --host 127.0.0.1 --port 8080
