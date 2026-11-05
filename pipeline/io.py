"""Bounded downloads, safe archives, checksums and deterministic JSON."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import urllib.request
import zipfile


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def download(url, destination, max_bytes=150_000_000):
    destination = Path(destination)
    if destination.exists():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + '.part')
    request = urllib.request.Request(url, headers={'User-Agent': 'RenaturaResearch/1.0'})
    try:
        with urllib.request.urlopen(request, timeout=90) as response, open(temporary, 'wb') as target:
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > max_bytes:
                    raise ValueError('Download exceeds the configured size limit')
                target.write(block)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def extract(archive, destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        if sum(info.file_size for info in z.infolist()) > 1_000_000_000:
            raise ValueError('Uncompressed archive exceeds size limit')
        for info in z.infolist():
            path = (destination / info.filename).resolve()
            if not path.is_relative_to(destination):
                raise ValueError('Unsafe ZIP member')
        z.extractall(destination)
    return destination


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False,
                                   separators=(',', ':')), encoding='utf-8')
    temporary.replace(path)


def manifest(directory):
    directory = Path(directory)
    return {str(path.relative_to(directory)): {'sha256': digest(path), 'bytes': path.stat().st_size}
            for path in sorted(directory.rglob('*'))
            if path.is_file() and path.name != 'manifest.json'}
