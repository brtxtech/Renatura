#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v docker >/dev/null 2>&1; then echo "Installez et démarrez Docker Desktop, puis relancez ce fichier."; exit 1; fi
if [ ! -d .venv-local ]; then python3 -m venv .venv-local; fi
.venv-local/bin/python -m pip install -r requirements-local.txt
exec .venv-local/bin/python pipeline/start_local.py
