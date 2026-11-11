"""Model selection for territory_forecast WITHOUT looking at the test period.

  .venv-normandie/bin/python -m pipeline.renatura_ai.tune

Protocol (no test-set tuning):
  1. selection: train on the 2000->2006 pair, validate on the 2006->2012 pair, on cells outside the final test set;
  2. the best configuration (lowest validation MAE, compared with persistence on the same cells) is written into
     configs/features.yaml (params + target_mode);
  3. run_normandie then retrains on 2000->2012 and evaluates ONCE on 2012->2018 (cells never seen).
Writes datasets/normandie_regional/ml/tuning.json (all candidates and their validation scores).
"""
from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline

from .training import HurdleRegressor, load_table, make_training_table

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'datasets/normandie_regional/ml/features_clc.csv'
CONFIG = Path(__file__).with_name('configs') / 'features.yaml'
OUT = ROOT / 'datasets/normandie_regional/ml/tuning.json'

GRID = {
    'loss': ['squared_error', 'absolute_error'],
    'learning_rate': [0.03, 0.06, 0.1],
    'max_iter': [150, 400],
    'max_leaf_nodes': [15, 31],
    'min_samples_leaf': [20, 80],
}


def held(cells, fraction=.2):  # same hash partition as training.split_spatial_temporal
    return cells.astype(str).map(lambda x: int(hashlib.sha256(x.encode()).hexdigest()[:8], 16) / 0xffffffff < fraction)


def main():
    cfg = yaml.safe_load(CONFIG.read_text(encoding='utf-8'))
    spec = cfg['models']['territory_forecast']
    cfg['models']['territory_forecast'] = {**spec, 'target_mode': 'change'}
    data, spec = make_training_table(load_table(DATA), cfg, 'territory_forecast')
    data = data[~held(data.cell_id)]                     # the final test cells are never used here
    tr, va = data[data.observation_year == 2000], data[data.observation_year == 2006]
    feats = [f for f in spec['features'] if tr[f].notna().any()]
    y_va_level = va['_label'] + va[spec['target']]
    persistence = mean_absolute_error(y_va_level, va[spec['target']])
    results = []
    imp = ColumnTransformer([('n', SimpleImputer(strategy='median', add_indicator=True), feats)]).fit(tr[feats])
    Xtr, Xva = imp.transform(tr[feats]), imp.transform(va[feats])
    base_va = va[spec['target']].to_numpy()
    for loss, lr, it, leaves, msl in itertools.product(*GRID.values()):
        params = dict(loss=loss, learning_rate=lr, max_iter=it, max_leaf_nodes=leaves, min_samples_leaf=msl, l2_regularization=1., random_state=42)
        m = HurdleRegressor(**params).fit(Xtr, tr['_label'].to_numpy())
        p, mag = m.proba(Xva), (m.reg_.predict(Xva) if m.reg_ is not None else np.zeros(len(Xva)))
        for th in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):   # threshold chosen on validation too
            pred = np.clip(base_va + np.where(p >= th, mag, 0.), 0, 1)
            results.append({'estimator': 'hurdle', 'params': {**params, 'threshold': th},
                            'val_mae': float(mean_absolute_error(y_va_level, pred))})
    results.sort(key=lambda r: r['val_mae'])
    best = results[0]
    report = {'protocol': 'train 2000→2006, validation 2006→2012, final test cells excluded',
              'n_train': len(tr), 'n_val': len(va), 'persistence_val_mae': persistence,
              'best': best, 'beats_persistence_on_validation': best['val_mae'] < persistence,
              'candidates': results}
    OUT.write_text(json.dumps(report, indent=1))
    cfg_text = yaml.safe_load(CONFIG.read_text(encoding='utf-8'))
    tf = cfg_text['models']['territory_forecast']
    tf['target_mode'] = 'change'
    tf['estimator'] = best['estimator']
    tf['params'] = {k: v for k, v in best['params'].items() if k != 'random_state'}
    CONFIG.write_text('# Tuned by pipeline/renatura_ai/tune.py (validation 2006→2012, test period untouched).\n'
                      + yaml.safe_dump(cfg_text, sort_keys=False, allow_unicode=True), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'candidates'}, indent=1))
    print('top 5:', [(r['params']['loss'], r['params']['learning_rate'], r['params']['max_iter'], r['params']['threshold'], round(r['val_mae'] * 100, 4)) for r in results[:5]])


if __name__ == '__main__':
    main()
