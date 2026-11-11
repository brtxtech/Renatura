#!/usr/bin/env python3
"""Porte de validation formelle. Produit un statut et les raisons — jamais un verdict muet.
Les critères reprennent ceux déjà appliqués implicitement ailleurs dans le projet
(verify_atlas.py, build_atlas.py) mais explicités et réutilisables pour n'importe quelle
source, pas seulement les 354 déjà cataloguées."""
from __future__ import annotations

MAX_INVALID_RATE = 0.01          # ≤1% de géométries invalides après réparation
MAX_NULL_GEOMETRY_RATE = 0.02    # ≤2% d'objets sans géométrie
MIN_FEATURES_FOR_CONFIDENCE = 3  # un résultat à 1-2 objets est suspect, pas une couche


def validate_source(fetch_result: dict, profile: dict) -> dict:
    reasons: list[str] = []
    warnings: list[str] = []
    n = profile['feature_count']

    if fetch_result.get('errors'):
        reasons.append('Erreurs réseau/parsing pendant la récupération : ' + '; '.join(fetch_result['errors'][:5]))
    if fetch_result.get('truncated'):
        reasons.append(fetch_result.get('truncation_reason') or 'Récupération tronquée, cause non précisée.')
    if n == 0:
        reasons.append('Aucun objet retourné — vérifier le TYPENAME, le filtre BBOX ou les droits d’accès.')
    elif n < MIN_FEATURES_FOR_CONFIDENCE:
        warnings.append(f'Seulement {n} objets retournés : résultat plausible mais à vérifier manuellement.')

    null_rate = profile['geometry_null_count'] / n if n else 1
    if null_rate > MAX_NULL_GEOMETRY_RATE:
        reasons.append(f'{profile["geometry_null_count"]}/{n} objets sans géométrie ({null_rate:.1%} > '
                        f'{MAX_NULL_GEOMETRY_RATE:.0%} toléré).')

    invalid_rate = profile['geometry_invalid_after_repair'] / n if n else 1
    if invalid_rate > MAX_INVALID_RATE:
        reasons.append(f'{profile["geometry_invalid_after_repair"]}/{n} géométries restent invalides après '
                        f'réparation ({invalid_rate:.1%} > {MAX_INVALID_RATE:.0%} toléré).')

    if profile['bbox_2154'] is None and n > 0:
        reasons.append('Impossible de déterminer l’emprise géométrique (toutes les géométries ont échoué).')

    if profile['duplicate_geometry_count'] > 0:
        warnings.append(f'{profile["duplicate_geometry_count"]} géométries dupliquées détectées '
                         '(conservées, signalées — non déduites automatiquement).')

    status = 'ERROR' if (n == 0 or fetch_result.get('errors')) else ('PARTIAL' if reasons else 'COMPLETE')
    return {'status': status, 'blocking_reasons': reasons, 'warnings': warnings,
            'criteria': {'max_invalid_rate': MAX_INVALID_RATE, 'max_null_geometry_rate': MAX_NULL_GEOMETRY_RATE,
                         'min_features_for_confidence': MIN_FEATURES_FOR_CONFIDENCE}}
