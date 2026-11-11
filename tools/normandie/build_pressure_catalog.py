#!/usr/bin/env python3
"""Compose l'indice de pression anthropique (P) à partir de sources déjà collectées localement.

Aucun téléchargement : les cinq couches ci-dessous existent déjà, complètes, dans ce
dépôt à la date d'écriture de ce script :
  - Tâche du bâti 2025      (atlas/catalog.json : file_96dc83a7d1807f4bc3, FILE_VERIFIED)
  - Établissements ICPE     (atlas/catalog.json : api_e58404c3d33a2099,    COMPLETE, 3227/3227)
  - Voies ferrées SRCE      (atlas/catalog.json : api_6cbcf22950edfbec,    COMPLETE, 1729/1731)
  - Réseau routier OSM      (orientation/roads.geojson.gz, 80 092 tronçons, Overpass, pas de
                              pagination WFS — remplace la source DREAL api_52f60ce350d2f59f,
                              tronquée à 9998/? par une limite de pages)
  - Arrêts de transport OSM (orientation/stops.geojson.gz, 20 966 points : gares, haltes,
                              arrêts de bus, terminaux de ferry — proxy de densité de lieux
                              fréquentés / activité humaine)

Pourquoi la source DREAL "Réseau routier" (api_52f60ce350d2f59f) n'est PAS utilisée : son
statut est PARTIAL, raison documentée « Limite de pages atteinte ; extraction partielle ».
L'ordre de pagination WFS n'est pas garanti géographiquement représentatif ; l'inclure aurait
biaisé la carte selon un artefact de collecte. La couche OSM équivalente (motorway→secondary)
est complète sur l'emprise régionale (bbox Overpass, aucune limite de pages) et est utilisée
à la place, avec sa propre provenance (sha256, horodatage OSM) dans dist/data/orientation/provenance.json.

CORINE Land Cover, les indicateurs de fragilité pavillonnaire et les ressources géologiques du
catalogue 193-couches ont été examinés et exclus pour la même raison que l'ancien réseau
routier DREAL : toutes leurs variantes sont PARTIAL avec la même cause (limite de pages /
timeout), donc non représentatives géographiquement. Aucune couche de boisement/végétation
régionale complète n'existe actuellement dans le catalogue (seules les observations du pilote
FR2502014 sont validées) ; l'indice ne les intègre donc pas pour rester honnête.

Ce script écrit :
  - <output>/{built,icpe,rail,roads,stops}.gpkg   (couches extraites localement)
  - <output>/metrics_catalog.json                 (déclaration criterion V/D/P pour prepare.py)
  - <output>/project.json                         (config attendue par build_normandie.py --project)
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import json
import pathlib

import geopandas as gpd
from shapely import make_valid

ATLAS_SOURCES = [
    {
        'metric': 'built',
        'catalog_id': 'file_96dc83a7d1807f4bc3',
        'label': 'Tâche du bâti · 2025',
        'layer': 'built',
        'year': 2025,
        'weight': 0.35,
        'geom_types': ['Polygon', 'MultiPolygon'],
        'usage': 'P (bâti) : proportion de surface bâtie par maille — proxy d’artificialisation/urbanisation, '
                 'pas une mesure d’émission ni de densité de population.',
    },
    {
        'metric': 'icpe',
        'catalog_id': 'api_e58404c3d33a2099',
        'label': 'Établissements ICPE · Normandie',
        'layer': 'icpe',
        'year': 2026,
        'weight': 0.20,
        'geom_types': ['Point', 'MultiPoint'],
        'usage': 'P (ICPE) : densité d’établissements classés (installations industrielles/polluantes) '
                 'par hectare — proxy de pression industrielle, pas une mesure de rejet réel.',
    },
    {
        'metric': 'rail',
        'catalog_id': 'api_6cbcf22950edfbec',
        'label': 'Voies ferrées · SRCE Normandie',
        'layer': 'rail',
        'year': 2026,
        'weight': 0.05,
        'geom_types': ['LineString', 'MultiLineString'],
        'usage': 'P (rail) : densité linéaire de voies ferrées par maille — proxy de fragmentation '
                 'par infrastructure lourde, signal mineur dans le composite.',
    },
]

ORIENTATION_SOURCES = [
    {
        'metric': 'roads',
        'file': 'roads.geojson.gz',
        'label': 'Réseau routier principal · OSM (motorway→secondary)',
        'layer': 'roads',
        'year': 2026,
        'weight': 0.30,
        'geom_types': ['LineString', 'MultiLineString'],
        'usage': 'P (routes) : densité de voirie principale (autoroutes, nationales, départementales) '
                 'par maille — proxy de fragmentation et de trafic, pas un comptage de véhicules.',
    },
    {
        'metric': 'stops',
        'file': 'stops.geojson.gz',
        'label': 'Arrêts de transport · OSM (gares, haltes, bus, ferries)',
        'layer': 'stops',
        'year': 2026,
        'weight': 0.10,
        'geom_types': ['Point', 'MultiPoint'],
        'usage': 'P (lieux fréquentés) : densité de points d’arrêt de transport par maille — proxy '
                 'de concentration de lieux fréquentés / activité humaine, pas une fréquentation réelle.',
    },
]

EXCLUDED_NOTE = (
    'Réseau routier DREAL (api_52f60ce350d2f59f) remplacé par le réseau OSM (roads.geojson.gz, '
    'complet, 80 092 tronçons) : la source DREAL était PARTIAL « Limite de pages atteinte ». '
    'CORINE Land Cover, fragilités pavillonnaires et ressources géologiques exclus : toutes leurs '
    'variantes du catalogue 193-couches sont PARTIAL (même cause de troncature WFS). Aucune '
    'couche de boisement/végétation régionale complète disponible pour l’instant — seul le '
    'pilote FR2502014 a des observations validées, non extrapolées.'
)


def read_json(path: pathlib.Path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: pathlib.Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def clean(frame: gpd.GeoDataFrame, metric: str, geom_types: list[str]) -> gpd.GeoDataFrame:
    frame = frame[['geometry']].copy()
    frame.geometry = frame.geometry.map(lambda g: make_valid(g) if g is not None else None)
    frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty]
    before = len(frame)
    frame = frame[frame.geom_type.isin(geom_types)]
    dropped = before - len(frame)
    if dropped:
        print(json.dumps({'metric': metric, 'dropped_non_matching_geometry_type': dropped}, ensure_ascii=False))
    return frame.reset_index(drop=True)


def load_atlas_chunks(atlas_dir: pathlib.Path, entry: dict, metric: str, geom_types: list[str]) -> gpd.GeoDataFrame:
    features = []
    for chunk in entry['chunks']:
        with gzip.open(atlas_dir / chunk, 'rt', encoding='utf-8') as handle:
            features.extend(json.load(handle)['features'])
    frame = gpd.GeoDataFrame.from_features(features, crs=4326)
    return clean(frame, metric, geom_types)


def load_orientation_file(orientation_dir: pathlib.Path, filename: str, metric: str, geom_types: list[str]) -> gpd.GeoDataFrame:
    with gzip.open(orientation_dir / filename, 'rt', encoding='utf-8') as handle:
        collection = json.load(handle)
    frame = gpd.GeoDataFrame.from_features(collection['features'], crs=4326)
    return clean(frame, metric, geom_types)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--renatura-root', required=True, type=pathlib.Path)
    parser.add_argument('--output', required=True, type=pathlib.Path,
                         help='Répertoire de sortie pour les .gpkg, metrics_catalog.json et project.json')
    parser.add_argument('--hex-area-km2', type=float, default=1)
    args = parser.parse_args()

    root = args.renatura_root.expanduser().resolve()
    atlas = root / 'dist/data/atlas'
    orientation = root / 'dist/data/orientation'
    catalog = read_json(atlas / 'catalog.json')
    by_id = {entry['id']: entry for entry in catalog['layers']}
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    collected_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    boundary_path = atlas / 'normandie.geojson'
    if not boundary_path.exists():
        raise SystemExit(f'Contour régional absent : {boundary_path}')
    provenance = read_json(orientation / 'provenance.json')
    provenance_by_id = {s['id']: s for s in provenance['sources']}

    pressure_layers = []
    for metric, filename, year in [
        ('hedges_before', 'hedges-2010.geojson', 2010),
        ('hedges_after', 'hedges-2016.geojson', 2016),
        ('woodland', 'woodland.geojson', 2016),
    ]:
        pressure_layers.append({
            'id': 'pilot-' + metric, 'canonical_id': 'FR2502014-' + metric,
            'label': 'FR2502014 · ' + metric + ' · ' + str(year), 'metric': metric, 'year': year,
            'role': 'criterion', 'enabled': True, 'validated': True,
            'local_path': str(root / 'dist/data' / filename),
            'coverage_path': str(root / 'dist/data/boundary.geojson'),
            'feature_semantics': 'hedge_only', 'status': 'COMPLETE',
            'source': 'https://www.data.gouv.fr/datasets/haies-et-zones-boisees-du-site-natura-2000-fr2502014-bocages-et-vergers-du-sud-pays-dauge-normandie',
            'usage': 'V/D : observations uniquement dans FR2502014, jamais extrapolées à toute la région.',
        })

    for source in ATLAS_SOURCES:
        entry = by_id.get(source['catalog_id'])
        if entry is None:
            raise SystemExit(f'Source introuvable dans catalog.json : {source["catalog_id"]}')
        if entry.get('status') not in ('COMPLETE', 'FILE_VERIFIED'):
            raise SystemExit(f'Source {source["catalog_id"]} n\'est pas complète ({entry.get("status")}) ; '
                              'vérifier avant de l\'inclure dans P.')
        frame = load_atlas_chunks(atlas, entry, source['metric'], source['geom_types'])
        gpkg_path = output / f'{source["metric"]}.gpkg'
        frame.to_file(gpkg_path, driver='GPKG', layer=source['layer'])
        print(json.dumps({'metric': source['metric'], 'features': len(frame), 'path': str(gpkg_path)},
                          ensure_ascii=False))
        pressure_layers.append({
            'id': f'pressure-{source["metric"]}', 'canonical_id': f'pressure-{source["metric"]}',
            'label': source['label'], 'metric': source['metric'], 'role': 'criterion',
            'category': 'pression_anthropique', 'year': source['year'], 'enabled': True, 'validated': True,
            'local_path': str(gpkg_path), 'file_layer': source['layer'], 'coverage_path': str(boundary_path),
            'coverage_complete': False, 'status': entry.get('status'), 'source': entry.get('url'),
            'validation': {
                'evidence': f'{entry.get("status")} dans le catalogue atlas ({source["catalog_id"]}), '
                            f'{entry.get("map_count")} objets cartographiés sur {entry.get("records")} ; '
                            'relu le ' + collected_at + '.',
                'method': 'Extraction directe des chunks locaux dist/data/atlas, aucune ré-interrogation réseau.',
                'reviewer': 'pipeline normandie · indice de pression composite',
            },
            'usage': source['usage'],
        })

    for source in ORIENTATION_SOURCES:
        prov = provenance_by_id.get(source['metric'])
        if prov is None:
            raise SystemExit(f'Provenance OSM introuvable pour : {source["metric"]}')
        frame = load_orientation_file(orientation, source['file'], source['metric'], source['geom_types'])
        gpkg_path = output / f'{source["metric"]}.gpkg'
        frame.to_file(gpkg_path, driver='GPKG', layer=source['layer'])
        print(json.dumps({'metric': source['metric'], 'features': len(frame), 'path': str(gpkg_path)},
                          ensure_ascii=False))
        pressure_layers.append({
            'id': f'pressure-{source["metric"]}', 'canonical_id': f'pressure-{source["metric"]}',
            'label': source['label'], 'metric': source['metric'], 'role': 'criterion',
            'category': 'pression_anthropique', 'year': source['year'], 'enabled': True, 'validated': True,
            'local_path': str(gpkg_path), 'file_layer': source['layer'], 'coverage_path': str(boundary_path),
            'coverage_complete': False, 'status': 'FILE_VERIFIED', 'source': prov.get('url'),
            'validation': {
                'evidence': f'OpenStreetMap Overpass, {prov.get("feature_count")} objets collectés le '
                            f'{prov.get("osm_timestamp")}, sha256={prov.get("raw_sha256")} ; '
                            'aucune limite de pages (requête Overpass unique sur l’emprise régionale), '
                            'relu le ' + collected_at + '.',
                'method': 'Extraction directe de dist/data/orientation (déjà collecté), aucune ré-interrogation réseau.',
                'reviewer': 'pipeline normandie · indice de pression composite',
            },
            'usage': source['usage'],
        })

    metrics_catalog = {'layers': pressure_layers, 'excluded_sources': [EXCLUDED_NOTE]}
    write_json(output / 'metrics_catalog.json', metrics_catalog)

    all_sources = ATLAS_SOURCES + ORIENTATION_SOURCES
    pressure_weights = {source['metric']: source['weight'] for source in all_sources}
    assert abs(sum(pressure_weights.values()) - 1.0) < 1e-9, pressure_weights
    project = {
        'before_year': 2010,
        'after_year': 2016,
        'hex_area_km2': args.hex_area_km2,
        'min_fragment_ha': 1,
        'normalization_reference': f'Normandie / composite de pression (bâti+routes+ICPE+arrêts+rail) / {datetime.date.today().isoformat()}',
        'allow_pressure_proxy': True,
        'pressure_weights': pressure_weights,
        'boundary': str(boundary_path),
        'catalog': 'metrics_catalog.json',
        'output': 'prepared.geojson',
    }
    write_json(output / 'project.json', project)
    print(json.dumps({'output': str(output), 'layers': [l['metric'] for l in pressure_layers],
                      'weights': pressure_weights, 'excluded': EXCLUDED_NOTE}, ensure_ascii=False))


if __name__ == '__main__':
    main()
