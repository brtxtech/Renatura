"""Publish populated workbench datasets to the Renatura views.

A populated GeoJSON / land dataset is written to user-data/datasets/wb_<dataset id>.json, the
registry read by the atlas (pipeline/ingest/api.py GET /api/datasets). Only accepted (validated)
features are published; removal and restoration in the workbench update or delete the file.
Non-geographic datasets (JSON records, climate records, images) stay in the workbench datastore.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import db

STORE = Path(os.environ.get('RENATURA_PUBLISH_DIR') or db.PROJECT / 'user-data' / 'datasets')  # tests override it
THEMES = {  # workbench category name -> atlas theme id (dist/data/atlas/catalog-v2.json)
    'Biodiversité et continuités écologiques': 'biodiversity', 'Eau': 'water',
    'Occupation du sol et urbanisme': 'landuse', 'Paysages et patrimoine': 'landscape',
    'Littoral et DTA ES': 'coast', 'Énergie et climat': 'energy', 'Risques et nuisances': 'risks',
    'Carrières et géologie': 'geology', 'Mobilité et logement': 'mobility', 'Réglementation': 'regulation',
    'Climat': 'energy', 'Foncier': 'landuse', 'Images et espèces': 'biodiversity',
}


def path_for(dataset_id: str):
    return STORE / f'wb_{dataset_id}.json'


def publish(doc: dict) -> str | None:
    """Write the dataset for the atlas; returns the file name, or None for non-geographic data."""
    if doc.get('kind') != 'geojson':
        return None
    ident = f'wb_{doc["id"]}'
    features = []
    for i, f in enumerate((doc.get('data') or {}).get('features', [])):
        features.append({'type': 'Feature', 'id': f'{ident}:{i}', 'geometry': f.get('geometry'),
                         'properties': {**(f.get('properties') or {}), '_id': f'{ident}:{i}', '_layer': ident}})
    meta = {'id': ident, 'display_name': doc.get('reference') or doc.get('name'),
            'theme': THEMES.get(doc.get('category'), 'biodiversity'), 'group': doc.get('category') or 'Atelier de données',
            'source': doc.get('source_uri') or f'Atelier de données · {doc.get("source_filename")}',
            'status': 'COMPLETE' if doc.get('collection_state') == 'complete' else 'PARTIAL',
            'updated': datetime.now(timezone.utc).isoformat(), 'license': doc.get('license') or 'Voir la source',
            'description': (f'Importé par l’atelier de données : {doc.get("valid_count", 0)} éléments validés, '
                            f'{doc.get("rejected_count", 0)} mis en quarantaine. SHA-256 {doc.get("sha256", "")[:12]}…'),
            'workbench_dataset': doc['id'], 'revision': doc.get('revision')}
    STORE.mkdir(parents=True, exist_ok=True)
    tmp = path_for(doc['id']).with_suffix('.tmp')
    tmp.write_text(json.dumps({'metadata': meta, 'data': {'type': 'FeatureCollection', 'features': features}}, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path_for(doc['id']))  # atomic: the atlas never reads a half-written file
    db.event('workspace', 'publish', f'Publié dans l’atlas : {meta["display_name"]} ({len(features)} éléments) → {path_for(doc["id"]).name}')
    return path_for(doc['id']).name


def unpublish(dataset_id: str) -> None:
    p = path_for(dataset_id)
    if p.exists():
        p.unlink()
        db.event('workspace', 'publish', f'Retiré de l’atlas : {p.name}')
