#!/usr/bin/env python3
"""Client WFS 2.0 avec pagination réelle. Corrige la cause racine des statuts PARTIAL
du catalogue : l'ingestion existante (pipeline/ingest/api.py) ne récupère qu'une seule
page (COUNT fixe, pas de boucle STARTINDEX). Ce client suit le lien `next` renvoyé par
le serveur (standard WFS 2.0) jusqu'à épuisement, avec un filtre BBOX régional pour éviter
de télécharger des couches nationales entières, et un plafond de sécurité explicite.
"""
from __future__ import annotations

import ssl
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from pipeline.atlas.gml_geometry import GEOMETRIES, read_wrapper, tag  # noqa: E402

try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()

USER_AGENT = 'RenaturaNormandie-ingest/1.0 (pipeline de repopulation, usage interne)'


def public_https(url: str) -> None:
    """Garde-fou minimal, même esprit que pipeline/ingest/api.py:public_url."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https':
        raise ValueError('URL non HTTPS refusée : ' + url)
    query = urllib.parse.parse_qs(parsed.query)
    for key in query:
        if any(bad in key.lower() for bad in ('key', 'token', 'password', 'secret', 'signature')):
            raise ValueError('Paramètre sensible détecté dans l’URL, refusé : ' + key)


def build_request_url(base_url: str, count: int, start_index: int, bbox: tuple[float, float, float, float] | None) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    query = dict(urllib.parse.parse_qsl(parsed.query))
    query['COUNT'] = str(count)
    query['STARTINDEX'] = str(start_index)
    query.setdefault('OUTPUTFORMAT', 'application/gml+xml; version=3.2')
    if bbox is not None:
        minx, miny, maxx, maxy = bbox
        query['BBOX'] = f'{minx},{miny},{maxx},{maxy},EPSG:2154'
    new_query = urllib.parse.urlencode(query)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, ''))


def output_format(url: str) -> str:
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    fmt = (query.get('OUTPUTFORMAT') or '').lower()
    return 'json' if 'json' in fmt else 'gml'


def fetch_page(url: str, timeout: float = 90) -> bytes:
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
        return response.read()


def parse_json_page(raw: bytes) -> tuple[list[dict], int | None, int, str | None]:
    """Renvoie (features_geojson, total_annoncé_ou_none, numberReturned, crs_détectée).
    Pas de lien `next` standard ici : l'appelant pagine via STARTINDEX/numberMatched."""
    import json
    payload = json.loads(raw)
    if 'exceptionText' in payload or payload.get('type') == 'ExceptionReport':
        raise ValueError('Le serveur WFS a renvoyé une exception JSON : ' + str(payload)[:300])
    features = payload.get('features', [])
    total = payload.get('numberMatched') or payload.get('totalFeatures')
    crs = None
    crs_obj = payload.get('crs')
    if isinstance(crs_obj, dict):
        crs = crs_obj.get('properties', {}).get('name')
    returned = payload.get('numberReturned', len(features))
    return features, total, returned, crs


def parse_gml_page(raw: bytes) -> tuple[list[dict], str | None, int, str | None]:
    """Renvoie (features_geojson, next_url_ou_none, nombre_de_membres, crs_détectée)."""
    root = ET.fromstring(raw)
    if 'ExceptionReport' in tag(root) or 'ExceptionReport' in root.tag:
        raise ValueError('Le serveur WFS a renvoyé une ExceptionReport : ' + raw[:300].decode('utf-8', 'replace'))
    next_url = root.attrib.get('next')
    features = []
    detected_crs = None
    for member in root:
        if tag(member) != 'member':
            continue
        feature_el = next(iter(member), None)
        if feature_el is None:
            continue
        geom_el = next((c for c in feature_el.iter() if tag(c) in GEOMETRIES), None)
        properties = {}
        for child in feature_el:
            child_tag = tag(child)
            if child_tag in GEOMETRIES or child_tag in ('boundedBy', 'geometry'):
                continue
            properties[child_tag] = (child.text or '').strip() or None
        if geom_el is None:
            features.append({'type': 'Feature', 'properties': properties, 'geometry': None})
            continue
        geometry, crs = read_wrapper({'gml': ET.tostring(geom_el)})
        detected_crs = detected_crs or crs
        features.append({'type': 'Feature', 'properties': properties, 'geometry': geometry})
    return features, next_url, len(features), detected_crs


def fetch_all(base_url: str, bbox: tuple[float, float, float, float] | None = None,
              count: int = 5000, max_pages: int = 80, delay: float = 0.4,
              max_retries: int = 3, max_bytes: int = 150_000_000, log=print) -> dict:
    """Pagine jusqu'à épuisement (lien `next` en GML, ou numberMatched en JSON), ou jusqu'au
    plafond de sécurité (pages ou octets — certaines couches nationales ont des géométries
    énormes où le nombre de pages seul ne protège pas assez).

    Renvoie {'features': [...], 'pages': n, 'truncated': bool, 'truncation_reason': str|None,
    'errors': [...], 'crs': ...}. `truncated=True` signifie que la récupération s'est arrêtée
    alors que des objets restaient disponibles — l'appelant NE DOIT PAS marquer COMPLETE.
    """
    public_https(base_url)
    fmt = output_format(base_url)
    all_features: list[dict] = []
    errors: list[str] = []
    bytes_read = 0
    start_index = 0
    url = build_request_url(base_url, count, start_index, bbox)
    pages = 0
    crs = None
    total_announced = None
    while url and pages < max_pages and bytes_read < max_bytes:
        attempt = 0
        while True:
            try:
                raw = fetch_page(url)
                break
            except Exception as error:  # noqa: BLE001 - réseau tiers, on retente puis on abandonne proprement
                attempt += 1
                if attempt > max_retries:
                    errors.append(f'page {pages}: {error}')
                    return {'features': all_features, 'pages': pages, 'truncated': True,
                            'truncation_reason': f'Échec réseau après {max_retries} tentatives : {error}',
                            'errors': errors, 'crs': crs}
                time.sleep(delay * attempt)
        bytes_read += len(raw)
        try:
            if fmt == 'json':
                features, total_announced, member_count, page_crs = parse_json_page(raw)
                next_url = None  # calculé plus bas via STARTINDEX
            else:
                features, next_url, member_count, page_crs = parse_gml_page(raw)
        except Exception as error:  # noqa: BLE001
            errors.append(f'page {pages}: parse error: {error}')
            return {'features': all_features, 'pages': pages, 'truncated': True,
                    'truncation_reason': f'Erreur de lecture page {pages} : {error}', 'errors': errors, 'crs': crs}
        crs = crs or page_crs
        all_features.extend(features)
        pages += 1
        log(f'  page {pages} : +{member_count} objets (total {len(all_features)}'
            f'{f"/{total_announced}" if total_announced else ""}, {bytes_read/1e6:.1f} Mo lus)')
        if member_count == 0:
            url = None
            break
        if fmt == 'json':
            start_index += count
            if total_announced is not None and start_index >= total_announced:
                url = None
            else:
                url = build_request_url(base_url, count, start_index, bbox)
        else:
            url = next_url
        if url:
            time.sleep(delay)
    truncated = url is not None
    truncation_reason = None
    if truncated:
        if bytes_read >= max_bytes:
            truncation_reason = f'Plafond de {max_bytes/1e6:.0f} Mo atteint alors que des objets restaient disponibles.'
        else:
            truncation_reason = f'Plafond de {max_pages} pages atteint alors que des objets restaient disponibles.'
    return {'features': all_features, 'pages': pages, 'truncated': truncated,
            'truncation_reason': truncation_reason, 'errors': errors, 'crs': crs,
            'total_announced': total_announced, 'bytes_read': bytes_read}
