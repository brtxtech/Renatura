"""Transparent partial scoring, shared semantics with the browser worker."""
from __future__ import annotations

import math
from typing import Iterable

KEYS = ('V', 'D', 'P', 'O')
DEFAULT_WEIGHTS = (0.30, 0.30, 0.15, 0.25)


def finite(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def normalize_weights(weights: Iterable[float]) -> list[float]:
    values = list(weights)
    if len(values) != 4:
        raise ValueError('Exactly four weights are required')
    if not all(finite(x) and x >= 0 for x in values):
        raise ValueError('Weights must be finite and nonnegative')
    total = sum(values)
    if total <= 0:
        raise ValueError('At least one weight must be positive')
    return [x / total for x in values]


def percentile_scores(values: list[float | None]) -> list[float | None]:
    """Midrank percentile; constant positive arrays get 50, true zeros stay 0."""
    observed = sorted(x for x in values if finite(x))
    if not observed:
        return [None] * len(values)
    result = []
    for value in values:
        if not finite(value):
            result.append(None)
            continue
        if value == 0:
            result.append(0.0)
            continue
        below = sum(x < value for x in observed)
        equal = sum(x == value for x in observed)
        result.append(100 * (below + equal / 2) / len(observed))
    return result


def score_site(site, weights=DEFAULT_WEIGHTS, allow_partial=False, minimum_v=10):
    weights = normalize_weights(weights)
    available = [finite(site.get(key)) for key in KEYS]
    coverage = 100 * sum(available) / len(KEYS)
    weighted_coverage = sum(w for w, ok in zip(weights, available) if ok)
    complete = all(ok or w == 0 for ok, w in zip(available, weights))
    eligible = finite(site.get('V')) and site['V'] >= minimum_v
    if not eligible or weighted_coverage == 0 or (not complete and not allow_partial):
        return {'score': None, 'coverage': coverage, 'partial': not complete,
                'eligible': False, 'weight_coverage': weighted_coverage}
    total = sum(site[key] * weight for key, weight, ok in zip(KEYS, weights, available) if ok)
    return {'score': total / weighted_coverage, 'coverage': coverage,
            'partial': not complete, 'eligible': True,
            'weight_coverage': weighted_coverage}


def rank_sites(sites, weights=DEFAULT_WEIGHTS, allow_partial=False, minimum_v=10):
    ranked = []
    for site in sites:
        result = score_site(site, weights, allow_partial, minimum_v)
        if result['score'] is not None:
            ranked.append({**site, **result})
    return sorted(ranked, key=lambda x: (-x['score'], x['id']))


def protection_score(site, neighbouring_pressure):
    """No pressure coverage means no protection score, rather than zero."""
    values = [site.get('V'), site.get('D'), neighbouring_pressure]
    if not all(finite(x) for x in values):
        return None
    v, d, pressure = values
    return v * (1 - d / 100) * pressure / 100
