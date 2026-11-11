#!/usr/bin/env python3
"""Pipeline de repopulation : lire → analyser (schéma/caractéristiques) → valider → peupler.

Cible par défaut : les sources du catalogue dont le statut est PARTIAL/ERROR et dont la
raison documentée est une troncature de pagination WFS ("Limite de pages atteinte",
"TimeoutError", "Collecte interrompue"). Ce pipeline ne les corrige QUE si la nouvelle
récupération, elle, est réellement complète et valide — sinon il laisse le statut existant
et explique pourquoi (jamais de statut fabriqué).

Usage :
  python3 repopulate.py --renatura-root <root> --ids api_52f60ce350d2f59f --dry-run
  python3 repopulate.py --renatura-root <root> --ids api_52f60ce350d2f59f,api_15a339ea6bde51cb --apply
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from wfs_client import fetch_all  # noqa: E402
from profile import profile_features, summarize  # noqa: E402
from validate import validate_source  # noqa: E402
from populate import update_catalog_entry, write_chunks  # noqa: E402

DEFAULT_BBOX = (340000.0, 6787000.0, 615000.0, 7000000.0)  # EPSG:2154, Normandie + marge 2 km


def candidates(catalog: dict) -> list[str]:
    truncation_markers = ('Limite de pages atteinte', 'TimeoutError', 'Collecte interrompue')
    return [l['id'] for l in catalog['layers']
            if l.get('kind') == 'WFS' and l.get('status') in ('PARTIAL', 'ERROR')
            and any(marker in (l.get('reason') or '') for marker in truncation_markers)]


def run_one(source_id: str, catalog: dict, atlas_dir: pathlib.Path, catalog_path: pathlib.Path,
            bbox, count: int, max_pages: int, apply: bool, max_bytes: int = 150_000_000) -> dict:
    entry = next((l for l in catalog['layers'] if l['id'] == source_id), None)
    if entry is None:
        return {'id': source_id, 'error': 'introuvable dans catalog.json'}
    print(f'\n=== {source_id} · {entry.get("name")} ===')
    print(f'avant : status={entry.get("status")} map_count={entry.get("map_count")} reason={entry.get("reason")}')

    print('1. lecture (pagination WFS réelle)…')
    fetch_result = fetch_all(entry['url'], bbox=bbox, count=count, max_pages=max_pages, max_bytes=max_bytes)
    print(f'   {fetch_result["pages"]} pages, {len(fetch_result["features"])} objets, '
          f'tronqué={fetch_result["truncated"]}')

    print('2. analyse (schéma/caractéristiques)…')
    profile, repaired_features = profile_features(fetch_result['features'], source_crs=fetch_result.get('crs'))
    print('   ' + summarize(profile).replace('\n', '\n   '))

    print('3. validation…')
    verdict = validate_source(fetch_result, profile)
    print(f'   statut proposé : {verdict["status"]}')
    for reason in verdict['blocking_reasons']:
        print(f'   [bloquant] {reason}')
    for warning in verdict['warnings']:
        print(f'   [avertissement] {warning}')

    print('4. population…' if apply else '4. population (dry-run, rien écrit)…')
    chunks = []
    if verdict['status'] == 'COMPLETE':
        if apply:
            chunks = write_chunks(atlas_dir, source_id, repaired_features)
        else:
            chunks = [f'{source_id}/{i // 5000:04d}.geojson.gz' for i in range(0, max(len(repaired_features), 1), 5000)]
        result = update_catalog_entry(
            catalog_path, source_id, status=verdict['status'], map_count=len(repaired_features),
            chunks=chunks, reasons=verdict['blocking_reasons'], warnings=verdict['warnings'],
            profile=profile, apply=apply)
        print(f'   {"appliqué" if apply else "simulé"} : {result["before"]} -> status=COMPLETE, '
              f'map_count={len(repaired_features)}')
    else:
        print(f'   non modifié : la récupération ne satisfait pas les critères de validation '
              f'(statut resterait {entry.get("status")}).')
        result = {'applied': False, 'reason': 'validation failed'}

    return {'id': source_id, 'fetch': {'pages': fetch_result['pages'], 'features': len(fetch_result['features']),
            'truncated': fetch_result['truncated']}, 'profile': profile, 'verdict': verdict, 'populate': result}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--renatura-root', required=True, type=pathlib.Path)
    parser.add_argument('--ids', help='Liste séparée par des virgules. Par défaut : auto-détection des sources PARTIAL/ERROR tronquées par pagination.')
    parser.add_argument('--count', type=int, default=5000, help='Objets par page WFS (défaut 5000).')
    parser.add_argument('--max-pages', type=int, default=80, help='Plafond de sécurité de pages par source (défaut 80).')
    parser.add_argument('--max-bytes', type=int, default=150_000_000, help='Plafond de sécurité en octets par source (défaut 150 Mo).')
    parser.add_argument('--apply', action='store_true', help='Écrit réellement les chunks et met à jour catalog.json. Sans ce flag : dry-run.')
    parser.add_argument('--report', type=pathlib.Path, help='Chemin où écrire un rapport JSON détaillé.')
    args = parser.parse_args()

    root = args.renatura_root.expanduser().resolve()
    atlas_dir = root / 'dist/data/atlas'
    catalog_path = atlas_dir / 'catalog.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))

    ids = args.ids.split(',') if args.ids else candidates(catalog)
    if not ids:
        print('Aucune source candidate trouvée (ou --ids vide).')
        return
    print(f'{len(ids)} source(s) à traiter : {ids}')

    results = []
    for source_id in ids:
        # Relire le catalogue à chaque itération : une mise à jour appliquée doit être visible
        # immédiatement si --apply est utilisé sur plusieurs sources dans la même exécution.
        catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
        results.append(run_one(source_id.strip(), catalog, atlas_dir, catalog_path,
                                DEFAULT_BBOX, args.count, args.max_pages, args.apply, args.max_bytes))

    improved = sum(1 for r in results if r.get('verdict', {}).get('status') == 'COMPLETE')
    print(f'\n=== Résumé : {improved}/{len(results)} source(s) validées COMPLETE ({"appliqué" if args.apply else "dry-run, rien écrit"}) ===')
    if args.report:
        args.report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Rapport détaillé : {args.report}')


if __name__ == '__main__':
    main()
