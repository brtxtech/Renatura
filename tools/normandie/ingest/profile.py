#!/usr/bin/env python3
"""Analyse les caractéristiques et le schéma d'un ensemble de features déjà récupérées.
Ne décide rien (c'est le rôle de validate.py) ; se limite à décrire ce qui est là."""
from __future__ import annotations

import json
from collections import Counter

import geopandas as gpd
from shapely import make_valid


def infer_type(value) -> str:
    if value is None:
        return 'null'
    try:
        float(value)
        return 'float' if '.' in str(value) else 'int'
    except (TypeError, ValueError):
        pass
    if str(value).lower() in ('true', 'false'):
        return 'bool'
    return 'str'


def profile_features(features: list[dict], source_crs: str | None) -> tuple[dict, list[dict]]:
    """Décrit le schéma (types de géométrie, champs, taux de nullité, emprise, doublons)
    et renvoie aussi les features réparées, reprojetées en EPSG:4326 (prêtes à écrire)."""
    geom_types = Counter()
    field_types: dict[str, Counter] = {}
    field_nulls: dict[str, int] = {}
    n = len(features)
    for feature in features:
        geom = feature.get('geometry')
        geom_types[geom['type'] if geom else 'null'] += 1
        for key, value in (feature.get('properties') or {}).items():
            field_types.setdefault(key, Counter())[infer_type(value)] += 1
            if value is None:
                field_nulls[key] = field_nulls.get(key, 0) + 1

    fields = {
        key: {
            'dominant_type': counts.most_common(1)[0][0] if counts else 'null',
            'null_rate': round(field_nulls.get(key, 0) / n, 3) if n else None,
            'distinct_types': dict(counts),
        }
        for key, counts in field_types.items()
    }

    valid_geoms = [f for f in features if f.get('geometry')]
    frame = None
    bbox = None
    repaired = 0
    invalid_after_repair = 0
    duplicate_count = 0
    repaired_features_4326: list[dict] = []
    if valid_geoms:
        try:
            frame = gpd.GeoDataFrame.from_features(valid_geoms, crs=source_crs or 'EPSG:2154')
            fixed = []
            for geom in frame.geometry:
                if geom is None or geom.is_empty:
                    invalid_after_repair += 1
                    fixed.append(geom)
                    continue
                if not geom.is_valid:
                    repaired += 1
                    geom = make_valid(geom)
                    if geom is None or geom.is_empty or not geom.is_valid:
                        invalid_after_repair += 1
                fixed.append(geom)
            frame.geometry = fixed
            bbox = tuple(round(v, 1) for v in frame.total_bounds)
            duplicate_count = int(frame.geometry.apply(lambda g: g.wkb if g is not None else None).duplicated().sum())
            display = frame[frame.geometry.notna() & ~frame.geometry.is_empty].to_crs(4326)
            repaired_features_4326 = json.loads(display.to_json(drop_id=True))['features']
        except Exception:  # noqa: BLE001 - un échec de profilage géométrique ne doit pas bloquer l'analyse
            pass

    profile = {
        'feature_count': n,
        'geometry_types': dict(geom_types),
        'fields': fields,
        'bbox_2154': bbox,
        'geometry_null_count': geom_types.get('null', 0),
        'geometry_repaired_count': repaired,
        'geometry_invalid_after_repair': invalid_after_repair,
        'duplicate_geometry_count': duplicate_count,
    }
    return profile, repaired_features_4326


def summarize(profile: dict) -> str:
    lines = [
        f"{profile['feature_count']} objets, types de géométrie : {profile['geometry_types']}",
        f"{len(profile['fields'])} champs ; emprise (EPSG:2154) : {profile['bbox_2154']}",
        f"géométries réparées : {profile['geometry_repaired_count']} · "
        f"invalides après réparation : {profile['geometry_invalid_after_repair']} · "
        f"doublons : {profile['duplicate_geometry_count']}",
    ]
    return '\n'.join(lines)
