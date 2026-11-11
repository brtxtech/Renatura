#!/usr/bin/env python3
"""Écrit les chunks locaux et met à jour l'entrée du catalogue — seulement si la
validation l'autorise. N'écrit jamais silencieusement : chaque mise à jour du
catalogue porte sa date, son statut et la raison associée."""
from __future__ import annotations

import datetime
import gzip
import json
from pathlib import Path

CHUNK_SIZE = 5000


def write_chunks(atlas_dir: Path, source_id: str, features: list[dict]) -> list[str]:
    out_dir = atlas_dir / source_id
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob('*.geojson.gz'):
        old.unlink()
    chunks = []
    for index in range(0, max(len(features), 1), CHUNK_SIZE):
        piece = features[index:index + CHUNK_SIZE]
        name = f'{index // CHUNK_SIZE:04d}.geojson.gz'
        path = out_dir / name
        with gzip.open(path, 'wt', encoding='utf-8', compresslevel=7) as handle:
            json.dump({'type': 'FeatureCollection', 'features': piece}, handle, ensure_ascii=False, separators=(',', ':'))
        chunks.append(f'{source_id}/{name}')
    return chunks


def update_catalog_entry(catalog_path: Path, source_id: str, *, status: str, map_count: int,
                          chunks: list[str], reasons: list[str], warnings: list[str],
                          profile: dict, apply: bool) -> dict:
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    entry = next((l for l in catalog['layers'] if l['id'] == source_id), None)
    if entry is None:
        raise SystemExit(f'Source absente du catalogue : {source_id}')

    before = {'status': entry.get('status'), 'map_count': entry.get('map_count'), 'reason': entry.get('reason')}
    patch = {
        'status': status,
        'complete': status == 'COMPLETE',
        'map_count': map_count,
        'records': map_count,
        'chunks': chunks,
        'reason': '; '.join(reasons) if reasons else 'Repopulation réussie : pagination complète via le lien WFS `next`.',
        'repopulation_warnings': warnings,
        'repopulated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'geometry_null_count': profile['geometry_null_count'],
        'repaired_count': profile['geometry_repaired_count'],
        'invalid_count': profile['geometry_invalid_after_repair'],
        'duplicates': profile['duplicate_geometry_count'],
    }
    if apply:
        entry.update(patch)
        catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'before': before, 'after': patch, 'applied': apply}
