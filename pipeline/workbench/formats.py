"""Turn an uploaded file into canonical JSON for the validation gate.

JSON / GeoJSON are parsed strictly; CSV becomes records, or a point FeatureCollection when the box is
geographic (latitude/longitude columns); a ZIP may contain one GeoJSON, JSON, CSV or shapefile and is
extracted defensively (entry count, total size, compression ratio, no absolute / '..' paths, no links).
Shapefiles must carry a .prj and are reprojected to WGS84.
"""
from __future__ import annotations

import csv
import io
import json
import re
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

MAX_ENTRIES = 500
MAX_UNZIPPED = 200 * 1024 * 1024
MAX_RATIO = 200          # uncompressed / compressed, per entry (zip bombs)
MAX_ROWS = 100_000
LAT_NAMES = ('latitude', 'lat', 'lat_wgs84', 'y_wgs84', 'y')
LON_NAMES = ('longitude', 'lon', 'lng', 'long', 'lon_wgs84', 'x_wgs84', 'x')
GEO_TYPES = ('geojson', 'foncier')


def strict_json(text: str):
    return json.loads(text, parse_constant=lambda v: (_ for _ in ()).throw(ValueError('Non-finite JSON constant')))


def sniff(raw: bytes, filename: str) -> str:
    name = filename.lower()
    if raw[:4] == b'PK\x03\x04':
        return 'zip'
    head = raw[:64].lstrip(b'\xef\xbb\xbf \t\r\n')
    if head[:1] in (b'{', b'['):
        return 'json'
    if name.endswith(('.csv', '.tsv', '.txt')):
        return 'csv'
    try:
        sample = raw[:4096].decode('utf-8-sig')
    except UnicodeDecodeError:
        return 'binary'
    first = sample.splitlines()[0] if sample else ''
    return 'csv' if any(d in first for d in (',', ';', '\t')) else 'unknown'


def _number(value: str, decimal_comma: bool):
    v = value.strip()
    if v == '' or v.lower() in ('null', 'na', 'n/a', 'nan'):
        return None
    probe = v.replace(',', '.') if decimal_comma else v
    if re.fullmatch(r'[+-]?\d+', probe):
        try:
            return int(probe)
        except ValueError:
            return v
    if re.fullmatch(r'[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?', probe):
        return float(probe)
    return v


def parse_csv(raw: bytes, geographic: bool):
    text = raw.decode('utf-8-sig')
    first = text.splitlines()[0] if text else ''
    delimiter = max((',', ';', '\t'), key=first.count)
    decimal_comma = delimiter == ';'
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames or len(reader.fieldnames) < 1:
        raise ValueError('CSV without a header row')
    rows = []
    for i, r in enumerate(reader):
        if i >= MAX_ROWS:
            raise ValueError(f'Maximum {MAX_ROWS:,} CSV rows per import; split the file')
        rows.append({(k or f'column_{j}').strip(): _number(v or '', decimal_comma) for j, (k, v) in enumerate(r.items())})
    label = f'csv ({delimiter!r} separator{", decimal comma" if decimal_comma else ""})'
    if not geographic:
        return rows, label
    lower = {k.lower(): k for k in reader.fieldnames if k}
    lat = next((lower[n] for n in LAT_NAMES if n in lower), None)
    lon = next((lower[n] for n in LON_NAMES if n in lower), None)
    if not lat or not lon:
        raise ValueError('A geographic box needs latitude/longitude columns (e.g. "latitude", "longitude") in the CSV')
    feats = []
    for r in rows:
        x, y = r.get(lon), r.get(lat)
        geom = {'type': 'Point', 'coordinates': [x, y]} if isinstance(x, (int, float)) and isinstance(y, (int, float)) else None
        feats.append({'type': 'Feature', 'geometry': geom, 'properties': {k: v for k, v in r.items() if k not in (lat, lon)}})
    return {'type': 'FeatureCollection', 'features': feats}, label + f' → points ({lat}, {lon})'


def _safe_members(z: zipfile.ZipFile):
    infos = z.infolist()
    if len(infos) > MAX_ENTRIES:
        raise ValueError(f'ZIP has {len(infos)} entries (maximum {MAX_ENTRIES})')
    total = 0
    for i in infos:
        p = PurePosixPath(i.filename.replace('\\', '/'))
        if p.is_absolute() or '..' in p.parts or re.match(r'^[A-Za-z]:', i.filename):
            raise ValueError(f'Unsafe path in ZIP: {i.filename}')
        if stat.S_ISLNK(i.external_attr >> 16):
            raise ValueError(f'Symbolic link in ZIP refused: {i.filename}')
        if i.flag_bits & 0x1:
            raise ValueError('Encrypted ZIP refused')
        total += i.file_size
        if total > MAX_UNZIPPED:
            raise ValueError('ZIP expands beyond 200 MB')
        if i.compress_size and i.file_size / i.compress_size > MAX_RATIO:
            raise ValueError(f'Suspicious compression ratio in ZIP ({i.filename}): possible zip bomb')
    return [i for i in infos if not i.is_dir() and not PurePosixPath(i.filename).name.startswith(('.', '__MACOSX'))
            and '__MACOSX' not in i.filename]


def read_zip(raw: bytes, element_type: str):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        members = _safe_members(z)
        by_ext = {}
        for m in members:
            by_ext.setdefault(PurePosixPath(m.filename).suffix.lower(), []).append(m)
        geographic = element_type in GEO_TYPES
        order = ['.shp', '.geojson', '.json', '.csv'] if geographic else ['.json', '.csv', '.geojson']
        for ext in order:
            found = by_ext.get(ext, [])
            if not found:
                continue
            if len(found) > 1:
                raise ValueError(f'ZIP contains {len(found)} {ext} datasets; upload one dataset per reference')
            m = found[0]
            if ext == '.shp':
                return _read_shapefile(z, m, members)
            data = z.read(m)
            if ext == '.csv':
                parsed, label = parse_csv(data, geographic)
                return parsed, f'zip → {PurePosixPath(m.filename).name} · {label}'
            return strict_json(data.decode('utf-8-sig')), f'zip → {PurePosixPath(m.filename).name}'
        raise ValueError('ZIP contains no GeoJSON, JSON, CSV or shapefile')


def _read_shapefile(z: zipfile.ZipFile, shp, members):
    stem = PurePosixPath(shp.filename).with_suffix('')
    parts = {PurePosixPath(m.filename).suffix.lower(): m for m in members if PurePosixPath(m.filename).with_suffix('') == stem}
    missing = [e for e in ('.shx', '.dbf') if e not in parts]
    if missing:
        raise ValueError(f'Incomplete shapefile in ZIP: missing {", ".join(missing)}')
    if '.prj' not in parts:
        raise ValueError('Shapefile without .prj (projection unknown): add the .prj file')
    import geopandas as gpd  # optional dependency, only needed for shapefiles
    with tempfile.TemporaryDirectory(prefix='wb-shp-') as tmp:
        for ext, m in parts.items():
            if ext in ('.shp', '.shx', '.dbf', '.prj', '.cpg'):
                (Path(tmp) / f'layer{ext}').write_bytes(z.read(m))
        g = gpd.read_file(Path(tmp) / 'layer.shp')
    if len(g) > MAX_ROWS:
        raise ValueError(f'Maximum {MAX_ROWS:,} features per import; split the layer')
    if g.crs is None:
        raise ValueError('Shapefile projection unreadable')
    source_crs = g.crs.to_string()
    g = g.to_crs(4326)
    return json.loads(g.to_json(drop_id=True, na='null')), f'zip → {PurePosixPath(shp.filename).name} · shapefile {source_crs} → WGS84'


def normalize(raw: bytes, filename: str, element_type: str):
    """Return (canonical JSON data, human label of the detected format)."""
    kind = sniff(raw, filename)
    if kind == 'zip':
        return read_zip(raw, element_type)
    if kind == 'csv':
        return parse_csv(raw, element_type in GEO_TYPES)
    if kind == 'json':
        return strict_json(raw.decode('utf-8-sig')), 'json'
    raise ValueError('Unsupported file: expected JSON, GeoJSON, CSV or ZIP (or an image for an image box)')
