#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def resolve_python(root: Path) -> Path:
    candidate = root / '.venv' / 'bin' / 'python'
    if candidate.exists():
        return candidate
    return Path(sys.executable)


def main() -> int:
    parser = argparse.ArgumentParser(description='Build the static Renatura data bundle for the Normandy explorer.')
    parser.add_argument('--renatura-root', required=True, type=Path, help='Absolute path to the Renatura project root.')
    parser.add_argument('--config', default='configs/pays-auge.json', help='Build config path, relative to the project root.')
    args = parser.parse_args()

    root = args.renatura_root.expanduser().resolve()
    if not root.exists():
        raise SystemExit(f'Project root not found: {root}')

    config = (root / args.config).resolve()
    if not config.exists():
        raise SystemExit(f'Config file not found: {config}')

    python_exec = resolve_python(root)
    requirements = root / 'requirements.txt'
    if requirements.exists():
        subprocess.run([str(python_exec), '-m', 'pip', 'install', '-r', str(requirements)], cwd=root, check=True)

    subprocess.run([str(python_exec), '-m', 'pipeline.build', '--config', str(config)], cwd=root, check=True)
    print(f'Build complete. Data ready under {root / "dist" / "data"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
