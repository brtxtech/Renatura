"""Honest supervised baselines: missing targets fail; temporal/spatial isolation.

Input: Parquet/CSV with one row per (cell_id, observation_year), canonical columns.
No synthetic targets, no silent zeros for missing geographic observations.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import yaml
from sklearn.compose import ColumnTransformer
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import average_precision_score, mean_absolute_error, mean_squared_error, r2_score, roc_auc_score
from sklearn.pipeline import Pipeline


class HurdleRegressor(BaseEstimator, RegressorMixin):
    """Rare changes: P(change) classifier x magnitude regressor trained on changing rows only.
    Predicts the magnitude where P(change) >= threshold, 0 elsewhere (stable cells stay stable)."""
    def __init__(self, threshold=.5, min_change=.001, learning_rate=.06, max_iter=200, max_leaf_nodes=31,
                 min_samples_leaf=20, l2_regularization=1., loss='squared_error', random_state=42):
        self.threshold, self.min_change, self.learning_rate, self.max_iter = threshold, min_change, learning_rate, max_iter
        self.max_leaf_nodes, self.min_samples_leaf, self.l2_regularization = max_leaf_nodes, min_samples_leaf, l2_regularization
        self.loss, self.random_state = loss, random_state

    def fit(self, X, y):
        y = np.asarray(y, float)
        common = dict(learning_rate=self.learning_rate, max_iter=self.max_iter, max_leaf_nodes=self.max_leaf_nodes,
                      min_samples_leaf=self.min_samples_leaf, l2_regularization=self.l2_regularization, random_state=self.random_state)
        moving = np.abs(y) > self.min_change
        self.clf_ = HistGradientBoostingClassifier(**common).fit(X, moving)
        self.reg_ = HistGradientBoostingRegressor(loss=self.loss, **common).fit(X[moving], y[moving]) if moving.sum() > 20 else None
        return self

    def proba(self, X):
        return self.clf_.predict_proba(X)[:, list(self.clf_.classes_).index(True)] if True in self.clf_.classes_ else np.zeros(len(X))

    def predict(self, X):
        if self.reg_ is None:
            return np.zeros(len(X))
        return np.where(self.proba(X) >= self.threshold, self.reg_.predict(X), 0.)


def load_table(path):
    p = Path(path)
    if p.suffix == '.parquet':
        return pd.read_parquet(p)
    if p.suffix == '.csv':
        return pd.read_csv(p)
    if p.suffix in ('.geojson', '.json'):
        import geopandas as gpd
        return pd.DataFrame(gpd.read_file(p).drop(columns='geometry', errors='ignore'))
    raise ValueError('Input must be .csv, .parquet or .geojson')


def validate(df, cfg, model):
    cell = cfg['cell_id']; year = cfg['year']; spec = cfg['models'][model]
    req = [cell, year] + spec['features']
    missing = [c for c in req if c not in df.columns]
    if missing:
        raise ValueError(f'Missing required columns: {missing}. Map actual layer attributes to canonical columns first.')
    if df.duplicated([cell, year]).any():
        raise ValueError('Duplicate cell/year rows: first aggregate spatial records into one row per cell and observation year.')
    if df[year].isna().any():
        raise ValueError('Missing observation_year (do not substitute dataset publication year).')
    for name in spec['features']:
        df[name] = pd.to_numeric(df[name], errors='coerce')
    available = df[spec['features']].notna().any(axis=1)
    if not available.any():
        raise ValueError('No real feature observations available: not allowed to fill all cells with zeros.')
    return spec


def make_training_table(df, cfg, model):
    spec = validate(df, cfg, model)
    cell, year = cfg['cell_id'], cfg['year']
    if model != 'territory_forecast':
        target = spec['target']
        if target not in df:
            raise ValueError(f'Independent observed target {target!r} is missing. Cannot train supervised model from map score alone.')
        data = df.copy()
        data['_label'] = pd.to_numeric(data[target], errors='coerce')
        data = data.loc[data['_label'].notna()].copy()
        if spec.get('task') == 'classification':  # event: observed value above a threshold
            data['_label'] = (data['_label'] > float(spec.get('positive_above', 0))).astype(float)
        if spec.get('label_years'):  # e.g. evaluate on a period with enough observed events
            data = data[data[cell_year_col(cfg)].isin(spec['label_years'])].copy()
        return data, spec
    # Learn observed future built_fraction from same geographic cell only.
    horizon = int(spec['horizon_years'])
    if horizon < 1:
        raise ValueError('Forecast horizon must be at least 1 observation year.')
    next_year = df[[cell, year, spec['target']]].copy()
    next_year[year] = next_year[year] - horizon
    next_year = next_year.rename(columns={spec['target']: '_label'})
    data = df.merge(next_year, on=[cell, year], how='inner', validate='one_to_one')
    data['_label'] = pd.to_numeric(data['_label'], errors='coerce')
    if spec.get('target_mode') == 'change':
        # learn the change over the horizon (stable cells -> ~0) instead of the future level;
        # predict() adds the current value back, so outputs stay future levels.
        data['_label'] = data['_label'] - pd.to_numeric(data[spec['target']], errors='coerce')
    data = data.loc[data['_label'].notna()].copy()
    if spec.get('task') == 'classification':
        data['_label'] = (data['_label'] > float(spec.get('positive_above', 0))).astype(float)
    if spec.get('label_years'):
        data = data[data[cell_year_col(cfg)].isin(spec['label_years'])].copy()
    return data, spec


def cell_year_col(cfg):
    return cfg['year']


def split_spatial_temporal(data, cfg, *, holdout_fraction=.2):
    """Hold out last label year AND a disjoint set of cells; test is their intersection.
    Spatial groups should eventually be larger geographic blocks to reduce autocorrelation.
    """
    cell, year = cfg['cell_id'], cfg['year']
    unique_years = sorted(data[year].unique())
    if len(unique_years) < 2:
        raise ValueError('Need observations across at least two years for temporal holdout. No validated model yet.')
    latest = unique_years[-1]
    # Deterministic partitions at cell level (not row level).
    import hashlib
    held = data[cell].astype(str).map(lambda x: int(hashlib.sha256(x.encode()).hexdigest()[:8],16)/0xffffffff < holdout_fraction)
    train = data.loc[(data[year] < latest) & ~held]
    test = data.loc[(data[year] == latest) & held]
    if len(train) < 20 or len(test) < 5:
        raise ValueError(f'Insufficient historical/spatial validation samples: train={len(train)}, test={len(test)}. More years/cells or block tuning required.')
    if set(train[cell]).intersection(test[cell]):
        raise AssertionError('Spatial leakage')
    return train, test, str(latest)


def train_model(input_path, config_path, model, outdir):
    cfg = yaml.safe_load(Path(config_path).read_text(encoding='utf-8'))
    if model not in cfg['models']:
        raise ValueError(f'Unknown model: {model}')
    df = load_table(input_path)
    data, spec = make_training_table(df, cfg, model)
    if len(data) == 0:
        raise ValueError(f'No labeled examples for {model}. Training deliberately blocked.')
    train, test, last_year = split_spatial_temporal(data, cfg)
    features = spec['features']
    # Skip completely missing columns in train. Never pretend they contain zero.
    usable = [c for c in features if train[c].notna().any()]
    if not usable:
        raise ValueError('All training features are missing.')
    prep = ColumnTransformer([('numeric', SimpleImputer(strategy='median',add_indicator=True), usable)], remainder='drop')
    params = {'max_iter': 180, 'learning_rate': .06, 'l2_regularization': 1., 'random_state': 42, **(spec.get('params') or {})}
    classification = spec.get('task') == 'classification'
    if classification:
        estimator = HistGradientBoostingClassifier(**{k: v for k, v in params.items() if k not in ('loss', 'threshold')})
    else:
        estimator = HurdleRegressor(**params) if spec.get('estimator') == 'hurdle' else HistGradientBoostingRegressor(**params)
    pipe = Pipeline([('impute',prep),('model',estimator)])
    pipe.fit(train[usable], train['_label'])
    change = spec.get('target_mode') == 'change' and not classification
    report = {'model':model,'status':'trained_baseline_not_scientifically_validated', 'task': 'classification' if classification else 'regression',
              'n_train':len(train),'n_test':len(test),'last_test_observation_year':last_year,
              'features_used':usable,'params':params,'features_unavailable':[c for c in features if c not in usable],
              'warning':'Spatial hash holdout is a baseline, not a geographic block CV. Validate on independent areas and years before public deployment.'}
    y = test['_label']
    base = spec.get('baseline_feature')
    if classification:
        p = pipe.predict_proba(test[usable])[:, 1]
        report.update(auc=float(roc_auc_score(y, p)) if y.nunique() > 1 else None,
                      average_precision=float(average_precision_score(y, p)) if y.sum() else None,
                      base_rate=float(y.mean()), positive_above=float(spec.get('positive_above', 0)))
        if base and base in test:
            rule = pd.to_numeric(test[base], errors='coerce').fillna(0)
            report['baseline'] = {'name': spec.get('baseline_name', base), 'auc': float(roc_auc_score(y, rule)) if y.nunique() > 1 else None,
                                  'average_precision': float(average_precision_score(y, rule)) if y.sum() else None}
    else:
        pred = pipe.predict(test[usable])
        report.update(mae=float(mean_absolute_error(y, pred)), rmse=float(np.sqrt(mean_squared_error(y, pred))),
                      r2=float(r2_score(y, pred)) if len(test) > 1 else None)
        if base and base in train:  # simple reference: linear regression on one variable, fitted on train
            ok_tr, ok_te = train[base].notna(), test[base].notna()
            lin = LinearRegression().fit(train.loc[ok_tr, [base]], train.loc[ok_tr, '_label'])
            bp = pd.Series(lin.predict(test[[base]].fillna(train[base].median())), index=test.index)
            report['baseline'] = {'name': spec.get('baseline_name', base), 'mae': float(mean_absolute_error(y, bp)),
                                  'r2': float(r2_score(y, bp))}
    out = Path(outdir); out.mkdir(parents=True,exist_ok=True)
    report['target_mode'] = 'change' if change else 'level'
    joblib.dump({'pipeline':pipe,'features':usable,'model':model,'report':report,'task':report['task'],
                 'target_mode':report['target_mode'],'base':spec['target'] if change else None},out/f'{model}.joblib')
    (out/f'{model}_metrics.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
    return report


def predict(model_path, df):
    blob = joblib.load(model_path)  # ONLY load files from your own trusted training pipeline.
    cols = blob['features']
    missing = set(cols)-set(df.columns)
    if missing: raise ValueError(f'Missing inference columns: {sorted(missing)}')
    numeric = df[cols].apply(pd.to_numeric,errors='coerce')
    valid = numeric.notna().any(axis=1)
    result = pd.Series(np.nan,index=df.index, name='prediction')
    if valid.any():
        if blob.get('task') == 'classification':  # probability of the event
            result.loc[valid] = blob['pipeline'].predict_proba(numeric.loc[valid])[:, 1]
        else:
            result.loc[valid] = blob['pipeline'].predict(numeric.loc[valid])
    if blob.get('target_mode') == 'change':  # model predicts a change: return the future level
        result = result + pd.to_numeric(df[blob['base']], errors='coerce')
    return result


def main():
    a=argparse.ArgumentParser()
    a.add_argument('--data',required=True);a.add_argument('--config',default='configs/features.yaml')
    a.add_argument('--model',required=True,choices=['human_pressure','eco_vulnerability','territory_forecast'])
    a.add_argument('--output',default='artifacts')
    x=a.parse_args()
    print(json.dumps(train_model(x.data,x.config,x.model,x.output),indent=2,ensure_ascii=False))
if __name__=='__main__': main()
