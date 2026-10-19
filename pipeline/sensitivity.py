"""Monte Carlo weight sensitivity: not ecological measurement uncertainty."""
from __future__ import annotations

import random
import statistics
from .scoring import rank_sites, normalize_weights, DEFAULT_WEIGHTS


def quantile(values, probability):
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def rank_correlation(left, right):
    """Pearson correlation of deterministic ordinal ranks (ties use site ID)."""
    if len(left) < 2:
        return None
    ml, mr = statistics.mean(left), statistics.mean(right)
    numerator = sum((a - ml) * (b - mr) for a, b in zip(left, right))
    denominator = (sum((a - ml) ** 2 for a in left) * sum((b - mr) ** 2 for b in right)) ** 0.5
    return numerator / denominator if denominator else 1.0


def monte_carlo(sites, runs=1000, seed=42, weights=DEFAULT_WEIGHTS, allow_partial=False):
    if runs < 2:
        raise ValueError('At least two runs are required')
    generator = random.Random(seed)
    base = rank_sites(sites, weights, allow_partial)
    if not base:
        return {'runs': 0, 'sites': [], 'reason': 'No eligible observations'}
    base_rank = {row['id']: index + 1 for index, row in enumerate(base)}
    histories = {node: [] for node in base_rank}
    top_counts = {node: 0 for node in base_rank}
    overlaps = []
    correlations = []
    size = min(20, len(base))
    base_top = set(list(base_rank)[:size])
    for _ in range(runs):
        changed = normalize_weights([w * generator.uniform(0.8, 1.2) for w in weights])
        ranking = rank_sites(sites, changed, allow_partial)
        current = {row['id']: index + 1 for index, row in enumerate(ranking)}
        top = set(list(current)[:size])
        overlaps.append(len(top & base_top) / len(top | base_top))
        for node in histories:
            histories[node].append(current[node])
            top_counts[node] += node in top
        correlations.append(rank_correlation(list(base_rank.values()), [current[n] for n in base_rank]))
    return {
        'runs': runs,
        'seed': seed,
        'variation': 0.20,
        'weights': list(weights),
        'allow_partial': allow_partial,
        'top_k': size,
        'mean_top20_jaccard': statistics.mean(overlaps),
        'mean_rank_correlation': statistics.mean(x for x in correlations if x is not None),
        'sites': [
            {'id': node, 'baseline_rank': base_rank[node],
             'top20_frequency': top_counts[node] / runs,
             'median_rank': statistics.median(histories[node]),
             'rank_p05': quantile(histories[node], 0.05),
             'rank_p95': quantile(histories[node], 0.95)}
            for node in base_rank
        ],
        'interpretation': 'Weight sensitivity only; no claim of ecological probability.',
    }
