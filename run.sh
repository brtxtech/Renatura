#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pipeline.build "$@"
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
printf '\nStatic app ready. Serve with: python3 -m http.server 8080 --directory dist\n'
 