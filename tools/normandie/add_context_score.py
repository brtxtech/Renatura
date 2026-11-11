#!/usr/bin/env python3
"""Ajoute un indice de contexte documentaire (CTX) à chaque maille régionale.

Ce n'est PAS un score écologique et ne remplace jamais V/D/P/O. C'est exactement
la même information que le panneau « Analyse maille » de l'Atlas régional
(couches intersectées / thèmes représentés), mais reportée sur le maillage fin
de l'explorateur (1 km²) au lieu des mailles atlas (5 × 5 km).

Pourquoi c'est possible sans recalcul géométrique coûteux : l'Atlas a déjà
précalculé, pour 1 354 mailles de 5 × 5 km couvrant toute la Normandie
(dist/data/atlas/zones/*.json), la liste des couches qui l'intersectent et le
nombre d'objets par couche. Ce script réutilise ce calcul existant :
  1. Pour chaque maille de l'explorateur, trouver la maille atlas 5×5 km qui
     la contient (même repère EPSG:2154, pas de nouvelle intersection).
  2. Compter les couches et les thèmes représentés dans cette maille atlas.
  3. Reporter un pourcentage : couches / 354 et thèmes / 14.

« Une absence de résultat ne prouve pas une absence d'enjeu » — même principe
que l'Atlas. Ce n'est qu'une mesure de densité documentaire, pas de priorité
de restauration.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re

import geopandas as gpd


def read_json(path: pathlib.Path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: pathlib.Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--renatura-root', required=True, type=pathlib.Path)
    parser.add_argument('--data-dir', type=pathlib.Path, default=None,
                         help='dist/data/normandie par défaut')
    args = parser.parse_args()

    root = args.renatura_root.expanduser().resolve()
    data_dir = args.data_dir or (root / 'dist/data/normandie')
    atlas = root / 'dist/data/atlas'
    zones_dir = atlas / 'zones'

    catalog = read_json(atlas / 'catalog.json')
    layer_categories = {entry['id']: entry.get('categories', []) for entry in catalog['layers']}
    all_categories = sorted({c for cats in layer_categories.values() for c in cats})
    total_layers = len(catalog['layers'])
    total_themes = len(all_categories)
    print(f'Catalogue : {total_layers} couches, {total_themes} thèmes.')

    zone_files = list(zones_dir.glob('N*.json'))
    zone_coords = {}
    pattern = re.compile(r'N(\d+)_(\d+)\.json$')
    for f in zone_files:
        m = pattern.search(f.name)
        if m:
            zone_coords[(int(m.group(1)), int(m.group(2)))] = f
    print(f'Mailles atlas disponibles : {len(zone_coords)}')

    zone_cache: dict[tuple[int, int], dict] = {}

    def load_zone(zx: int, zy: int):
        key = (zx, zy)
        if key in zone_cache:
            return zone_cache[key]
        path = zone_coords.get(key)
        if path is None:
            zone_cache[key] = None
            return None
        zone = read_json(path)
        layer_ids = [l['id'] for l in zone['layers']]
        themes = sorted({c for lid in layer_ids for c in layer_categories.get(lid, [])})
        result = {
            'layers_intersected': len(layer_ids),
            'themes_represented': len(themes),
            'theme_names': themes,
        }
        zone_cache[key] = result
        return result

    cells_path = data_dir / 'cells.geojson'
    collection = read_json(cells_path)
    frame = gpd.GeoDataFrame.from_features(collection['features'], crs=4326).to_crs(2154)
    centroids = frame.geometry.centroid

    matched = 0
    for feature, centroid in zip(collection['features'], centroids):
        zx = int(centroid.x // 5000 * 5000)
        zy = int(centroid.y // 5000 * 5000)
        zone = load_zone(zx, zy)
        props = feature['properties']
        if zone is None:
            props['context_layers'] = None
            props['context_layers_pct'] = None
            props['context_themes'] = None
            props['context_themes_pct'] = None
            props['context_score'] = None
            continue
        matched += 1
        layers_pct = round(100 * zone['layers_intersected'] / total_layers, 1)
        themes_pct = round(100 * zone['themes_represented'] / total_themes, 1)
        props['context_layers'] = zone['layers_intersected']
        props['context_layers_pct'] = layers_pct
        props['context_themes'] = zone['themes_represented']
        props['context_themes_pct'] = themes_pct
        props['context_score'] = round((layers_pct + themes_pct) / 2, 1)
        props['context_methods'] = ('CTX : densité documentaire, pas un score écologique. '
                                     f'{zone["layers_intersected"]}/{total_layers} couches catalogue, '
                                     f'{zone["themes_represented"]}/{total_themes} thèmes représentés sur la maille atlas 5×5 km '
                                     'contenant cette maille. Une absence de résultat ne prouve pas une absence d\'enjeu.')

    write_json(cells_path, collection)
    print(json.dumps({
        'cells': len(collection['features']),
        'matched_to_an_atlas_zone': matched,
        'total_catalog_layers': total_layers,
        'total_themes': total_themes,
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
