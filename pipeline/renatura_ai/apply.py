"""Apply the three Renatura AI models to real cells (newest observed state) and show what each returns.

  .venv-normandie/bin/python -m pipeline.renatura_ai.apply --commune Caen
  .venv-normandie/bin/python -m pipeline.renatura_ai.apply --cell H1_538_6422 --json

  territory_forecast -> probability that the cell's artificial share rises > 1 point between 2018 and 2024
  eco_vulnerability  -> probability that the cell loses > 1 point of natural habitat between 2018 and 2024
  human_pressure     -> population density estimated from 2018 land cover, next to the INSEE 2017 observation
A model that is blocked (no artefact) returns « Non disponible » and its reason, never a number.
"""
from __future__ import annotations

import argparse
import gzip
import json
import unicodedata
from pathlib import Path

import pandas as pd
import yaml

from .training import load_table, predict

ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path(__file__).with_name('configs') / 'features.yaml'
ARTIFACTS = ROOT / 'datasets/normandie_regional/ml/artifacts'
STATUS = ROOT / 'dist/data/normandie/ml_status.json'
POINTS = ROOT / 'dist/data/normandie/cells_points.json.gz'
MODELS = ('territory_forecast', 'eco_vulnerability', 'human_pressure')


def _norm(s):
    return unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().lower().strip()


def cells_of(commune=None, cells=None):
    p = json.load(gzip.open(POINTS, 'rt'))
    if cells:
        known = set(p['id'])
        return [c for c in cells if c in known], {}
    j = next((k for k, c in enumerate(p['communes']) if _norm(c['name']) == _norm(commune)), None)
    if j is None:
        raise SystemExit(f'commune inconnue : {commune}')
    ids = [cid for cid, c in zip(p['id'], p['commune']) if c == j]
    return ids, {cid: p['communes'][j]['name'] for cid in ids}


def apply(cell_ids, config=CONFIG, artifacts=ARTIFACTS, status_path=STATUS):
    """One record per cell and model, computed by running the trained artefacts on the newest observed rows."""
    cfg = yaml.safe_load(Path(config).read_text(encoding='utf-8'))
    status = json.loads(Path(status_path).read_text()) if Path(status_path).exists() else {'models': {}}
    out = {cid: {} for cid in cell_ids}
    for name in MODELS:
        spec, st = cfg['models'][name], status.get('models', {}).get(name, {})
        path = Path(artifacts) / f'{name}.joblib'
        data = ROOT / spec['data']
        if not path.exists() or not data.exists():
            for cid in cell_ids:
                out[cid][name] = {'statut': 'Non disponible / données insuffisantes', 'raison': st.get('reason', 'modèle non entraîné')}
            continue
        table = load_table(data)
        year = int(table.observation_year.max())
        rows = table[table.observation_year == year].set_index('cell_id').reindex(cell_ids)
        pred = predict(path, rows.reset_index().rename(columns={'index': 'cell_id'}))
        pred.index = cell_ids
        for cid in cell_ids:
            v = pred[cid]
            rec = {'statut': st.get('status', 'trained'), 'etat_utilise': year}
            if spec.get('task') == 'classification':
                rec['probabilite'] = None if pd.isna(v) else round(float(v), 4)
                rec['taux_de_base_test'] = st.get('base_rate')
            else:
                obs = rows.loc[cid, spec['target']]
                rec['estime_hab_km2'] = None if pd.isna(v) else round(10 ** float(v) - 1)
                rec['observe_hab_km2'] = None if pd.isna(obs) else round(10 ** float(obs) - 1)
            out[cid][name] = rec
    return out


def main():
    a = argparse.ArgumentParser()
    a.add_argument('--commune')
    a.add_argument('--cell', action='append')
    a.add_argument('--json', action='store_true')
    x = a.parse_args()
    if not x.commune and not x.cell:
        a.error('--commune ou --cell')
    ids, _ = cells_of(x.commune, x.cell)
    res = apply(ids)
    if x.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return
    status = json.loads(STATUS.read_text()) if STATUS.exists() else {'models': {}}
    print(f"{len(ids)} maille(s){' · ' + x.commune if x.commune else ''}")
    for k, m in status['models'].items():
        b = m.get('baseline') or {}
        if m.get('task') == 'classification':
            print(f"  {k:<19} {m['status']:<12} AUC test {m.get('auc', 0):.3f} (référence {b.get('auc', float('nan')):.3f})")
        elif m.get('status') != 'blocked':
            print(f"  {k:<19} {m['status']:<12} R² test {m.get('r2', 0):.3f} (référence {b.get('r2', float('nan')):.3f})")
    print(f"\n{'maille':<14}{'risque artif.':>14}{'risque habitat':>16}{'hab/km² estimé':>16}{'observé 2017':>14}")
    f = lambda v, pct=True: '—' if v is None else (f'{100 * v:.1f} %' if pct else f'{v:,}'.replace(',', ' '))
    for cid in ids:
        r = res[cid]
        print(f"{cid:<14}{f(r['territory_forecast'].get('probabilite')):>14}{f(r['eco_vulnerability'].get('probabilite')):>16}"
              f"{f(r['human_pressure'].get('estime_hab_km2'), False):>16}{f(r['human_pressure'].get('observe_hab_km2'), False):>14}")


if __name__ == '__main__':
    main()
