"""One-command pilot build. Nothing depends on a runtime data server."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import hashlib
import re
from pathlib import Path
import sys

import duckdb
import geopandas as gpd
from shapely.geometry import LineString

from .io import download, extract, digest, write_json, manifest
from .geo import prepare, to_features
from .connectivity import build_graph, evaluate_graph
from .optimisation import solve
from .sensitivity import monte_carlo

ROOT = Path(__file__).resolve().parent.parent
PILOT_URL = 'https://atom.geo-ide.developpement-durable.gouv.fr/atomArchive/GetResource?id=fr-120066022-orphan-01add05c-fed6-4238-84fb-662ff75a8b75&dataType=datasetAggregate'
NATURA_URL = 'https://atom.geo-ide.developpement-durable.gouv.fr/atomArchive/GetResource?id=c1e85290-a56f-4b8d-930b-5726a532eb29&dataType=dataset'
COMMUNES_URL = 'https://geo.api.gouv.fr/departements/61/communes?format=geojson&geometry=contour'


def catalogue(raw):
    entries = [
        {
            'id': 'pilot-bocage',
            'title': 'Haies et zones boisées du site Natura 2000 FR2502014',
            'producer': 'DREAL Normandie',
            'url': 'https://www.data.gouv.fr/datasets/haies-et-zones-boisees-du-site-natura-2000-fr2502014-bocages-et-vergers-du-sud-pays-dauge-normandie',
            'download_url': PILOT_URL,
            'years': [1947, 2010, 2016],
            'resolution': 'Digitised hedgerows and woodland; positional precision not independently verified',
            'crs': 'IGNF:LAMB93 → EPSG:2154 → EPSG:4326',
            'licence': 'Licence Ouverte 2.0',
            'processing': 'Exact-geometry deduplication, valid geometry repair, Nature=haie, official-boundary clipping, 1 km² hex aggregation',
            'status': 'used',
            'sha256': digest(raw / 'pilot.zip'),
        },
        {
            'id': 'natura-boundary',
            'title': 'Natura 2000 Directive Habitats — Normandie',
            'producer': 'DREAL Normandie / MNHN',
            'url': 'https://www.data.gouv.fr/datasets/natura-2000-directive-habitats-zsc-sic-psic-normandie',
            'download_url': NATURA_URL,
            'years': [],
            'resolution': 'Regulatory boundary; source reference year requires metadata review',
            'crs': 'Source CRS read from file; processed EPSG:2154',
            'licence': 'Licence Ouverte 2.0',
            'processing': 'Filter SITECODE=FR2502014, dissolve, clip analysis cells',
            'status': 'used',
            'sha256': digest(raw / 'natura.zip'),
        },
        {
            'id': 'communes',
            'title': 'API Découpage administratif — communes de l’Orne',
            'producer': 'Service public / geo.api.gouv.fr',
            'url': 'https://geo.api.gouv.fr/decoupage-administratif/communes',
            'download_url': COMMUNES_URL,
            'years': [],
            'resolution': 'Commune contours, live API snapshot',
            'crs': 'EPSG:4326',
            'licence': 'Licence Ouverte 2.0',
            'processing': 'Spatial overlap lookup; main commune by largest overlap',
            'status': 'used',
            'sha256': digest(raw / 'communes.geojson'),
        },
    ]
    for id, title, reason in [
        ('pressure', 'Pression humaine / MOS / RPG / CCF', 'No pressure layer validated in this release; P remains null.'),
        ('opportunity', 'Disponibilité foncière / friches EPFN', 'API returned 503 during audit; land availability is unknown; O remains null.'),
        ('species', 'Observations naturalistes', 'No licensed aggregate ingested; no precise species locations exposed.'),
        ('srce', 'SRCE corridors', 'Catalogue located; not yet ingested. Pilot graph is a structural model.'),
        ('water', 'Mares / qualité de l’eau', 'No compatible open extraction validated in this release.'),
    ]:
        entries.append({'id': id, 'title': title, 'status': 'unavailable', 'issue': reason,
                        'producer': None, 'url': None, 'years': [], 'resolution': None,
                        'crs': None, 'licence': None, 'processing': None})
    return entries


def run(config_path):
    config = json.loads(Path(config_path).read_text())
    raw = ROOT / 'raw'
    output = ROOT / 'dist' / 'data'
    derived = ROOT / 'derived'
    derived.mkdir(exist_ok=True)
    for url, name in [(PILOT_URL, 'pilot.zip'), (NATURA_URL, 'natura.zip'),
                      (COMMUNES_URL, 'communes.geojson')]:
        print('INPUT', name, flush=True)
        download(url, raw / name)
    extract(raw / 'pilot.zip', raw / 'pilot')
    extract(raw / 'natura.zip', raw / 'natura')
    print('SPATIAL aggregations', flush=True)
    cells, boundary, hedges, woods, selected = prepare(raw, config['analysis_area_m2'])
    frame = gpd.GeoDataFrame(cells, crs=2154).drop(columns=['center'])
    frame.to_parquet(derived / 'cells.parquet', index=False)
    # GeoParquet remains the geometry authority. DuckDB provides lightweight QA.
    database = duckdb.connect()
    checks = database.execute(
        'SELECT count(*), count(DISTINCT id), sum(area_ha), min(coverage), max(coverage) FROM read_parquet(?)',
        [str(derived / 'cells.parquet')]).fetchone()
    if checks[0] != checks[1]:
        raise AssertionError('Duplicate cell IDs')
    print('GRAPH', len(cells), 'cells', flush=True)
    graph, patches, centrality, paths = build_graph(cells)
    for cell in cells:
        cell['betweenness'] = centrality[cell['id']]
    presets = []
    for preset in config['presets']:
        print('SOLVE', preset['id'], flush=True)
        result = solve(cells, paths, mode=preset['mode'], budget=preset['budget'],
                       weights=config['weights'], allow_partial=config['allow_partial'],
                       connectivity_weight=config['connectivity_weight'])
        result.update({'id': preset['id'], 'name': preset['name']})
        result['graph_analysis'] = evaluate_graph(graph, result['selected'], paths)
        presets.append(result)
    print('SENSITIVITY', config['monte_carlo_runs'], flush=True)
    sensitivity = monte_carlo(cells, runs=config['monte_carlo_runs'], seed=config['seed'],
                              weights=config['weights'], allow_partial=config['allow_partial'])
    write_json(output / 'cells.geojson', to_features(cells))
    write_json(output / 'boundary.geojson', selected.to_crs(4326).__geo_interface__)
    for year in (1947, 2010, 2016):
        layer = hedges[year].copy()
        layer.geometry = layer.geometry.intersection(boundary).simplify(8)
        layer = layer[~layer.geometry.is_empty]
        write_json(output / f'hedges-{year}.geojson', layer[['geometry']].to_crs(4326).__geo_interface__)
    wood = woods[2016].copy()
    wood.geometry = wood.geometry.intersection(boundary).simplify(8)
    wood = wood[~wood.geometry.is_empty]
    write_json(output / 'woodland.geojson', wood[['geometry']].to_crs(4326).__geo_interface__)
    centers = {c['id']: c['center'] for c in cells}
    routes = gpd.GeoDataFrame([
        {'id': p['id'], 'gain': p['gain'], 'geometry': LineString([centers[n] for n in p['route']])}
        for p in paths], geometry='geometry', crs=2154) if paths else None
    write_json(output / 'routes.geojson', routes.to_crs(4326).__geo_interface__ if routes is not None
               else {'type': 'FeatureCollection', 'features': []})
    write_json(output / 'connectivity.json', {'paths': paths, 'patches': [sorted(p) for p in patches],
               'assumption': 'Habitat cores V≥60; adjacent hexagons; resistance=d×(1+4×(1−mean V/100)); twelve largest patches.'})
    write_json(output / 'scenarios.json', presets)
    write_json(output / 'sensitivity.json', sensitivity)
    write_json(output / 'data_catalog.json', catalogue(raw))
    write_json(output / 'summary.json', {
        'title': config['title'], 'site': config['site'],
        'built_at': datetime.now(timezone.utc).isoformat(),
        'cell_count': len(cells), 'area_ha': sum(c['area_ha'] for c in cells),
        'boundary_area_ha': boundary.area / 10000,
        'omitted_slivers_ha': (boundary.area - sum(c['geometry'].area for c in cells)) / 10000,
        'hedge_2010_km': sum(c['hedge_2010_m'] for c in cells) / 1000,
        'hedge_2016_km': sum(c['hedge_2016_m'] for c in cells) / 1000,
        'patch_count': len(patches), 'connection_count': len(paths),
        'weights': config['weights'], 'coverage_min': checks[3], 'coverage_max': checks[4],
        'status': 'exploratory_partial', 'missing': ['P', 'O'],
        'limits': ['Pilot only; not all Normandy.', 'P and O unavailable; partial RP renormalises V and D.',
                   'No protection score without neighbouring pressure.', '2016 observations do not describe present conditions.',
                   'Connectivity and costs are proxies, not measured ecological gains or euros.',
                   'Analysis cells are planning units, not verified restoration parcels.'],
    })
    write_json(output / 'manifest.json', manifest(output))
    # An input/model/app change creates a new coherent offline cache.
    cache_inputs = [digest(p) for p in sorted((ROOT / 'dist').glob('*.js')) if p.name != 'sw.js']
    cache_inputs += [digest(output / name) for name in ('cells.geojson', 'scenarios.json', 'manifest.json')]
    version = hashlib.sha256(''.join(cache_inputs).encode()).hexdigest()[:16]
    service_worker = ROOT / 'dist' / 'sw.js'
    if service_worker.exists():
        service_worker.write_text(re.sub(r"const VERSION = '[^']+';", f"const VERSION = 'renatura-{version}';", service_worker.read_text()))
    print('DONE', len(cells), 'real-data cells;', len(paths), 'candidate connections', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(ROOT / 'configs/pays-auge.json'))
    args = parser.parse_args()
    try:
        run(args.config)
    except Exception as error:
        print(f'BUILD FAILED: {error}. No fabricated substitute was generated.', file=sys.stderr)
        raise


if __name__ == '__main__':
    main()
