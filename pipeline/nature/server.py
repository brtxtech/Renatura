"""Extension 1 · Nature photos: upload, species recognition, validation, photo-evidence layer.

Run (project venv, port 8090; also serves dist/ so the pages are same-origin):
    .venv-normandie/bin/python -m uvicorn pipeline.nature.server:app --port 8090

Privacy and validation rules
- Upload and validation need a partner key (header X-Partner-Key); keys are stored hashed in
  user-data/nature/partners.json (create with: python -m pipeline.nature.partners add NAME [--expert]).
- The photo is re-encoded from pixels: EXIF (GPS, device, owner) is dropped after reading position/date.
- Faces are blurred (OpenCV Haar cascade) before anything is stored.
- Exact positions are kept in the private database; the public list shows sensitive species
  (protected in France or threatened on the Normandy red list) only at 10 km precision.
- A photo counts in the evidence layer only when 'confirmed': two partners agree, or one expert.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import os
import sqlite3
import threading
import uuid
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import ExifTags, Image, ImageOps
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
STORE = Path(os.getenv('RENATURA_NATURE_STORE', ROOT / 'user-data/nature'))
PHOTOS = STORE / 'photos'
DB = STORE / 'photos.db'
MODEL_DIR = ROOT / 'datasets/normandie_species/model'
LABELS = ROOT / 'datasets/normandie_species/labels/species_labels_full.csv'
CELLS = ROOT / 'dist/data/normandie/cells.geojson.gz'
EVIDENCE_OUT = ROOT / 'dist/data/normandie/photo_evidence.json'
MAX_BYTES = 20 * 1024 * 1024
STORE.mkdir(parents=True, exist_ok=True)
PHOTOS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title='Renatura · Photos nature Normandie', version='1.0')
_lock = threading.Lock()


# ------------------------------------------------------------------ storage
def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute('''CREATE TABLE IF NOT EXISTS photos(
        id TEXT PRIMARY KEY, created_at TEXT, observer TEXT, lat REAL, lon REAL, position_source TEXT,
        cell_id TEXT, taken_at TEXT, top5 TEXT, confidence REAL, status TEXT, species_final TEXT,
        validations TEXT, consent_share INTEGER, licence TEXT, faces_blurred INTEGER, note TEXT)''')
    return con


def partners():
    f = STORE / 'partners.json'
    return json.loads(f.read_text()) if f.exists() else {}


def require_partner(key):
    if not key:
        raise HTTPException(401, 'Clé partenaire requise (en-tête X-Partner-Key).')
    p = partners().get(hashlib.sha256(key.encode()).hexdigest())
    if not p:
        raise HTTPException(403, 'Clé partenaire inconnue.')
    return p


# ------------------------------------------------------------------ species model + labels
class Model:
    def __init__(self):
        self.ready = False
        self.error = None

    def load(self):
        if self.ready:
            return
        if self.error and not (MODEL_DIR / 'model.pt').exists():
            return
        self.error = None  # retry: the model may have been trained since the last attempt
        try:
            import timm
            import torch
            from torchvision import transforms
            ck = torch.load(MODEL_DIR / 'model.pt', map_location='cpu')
            self.torch = torch
            self.net = timm.create_model(ck['arch'], pretrained=False, num_classes=len(ck['classes']))
            self.net.load_state_dict(ck['state_dict'])
            self.net.eval()
            self.tf = transforms.Compose([transforms.Resize(int(ck['size'] * 1.14)), transforms.CenterCrop(ck['size']),
                                          transforms.ToTensor(), transforms.Normalize(ck['mean'], ck['std'])])
            self.classes = json.loads((MODEL_DIR / 'classes.json').read_text(encoding='utf-8'))
            m = json.loads((MODEL_DIR / 'metrics.json').read_text(encoding='utf-8'))
            self.metrics = m
            self.threshold = (m.get('calibration_auto_accept') or {}).get('threshold')
            self.ready = True
        except Exception as e:  # model not trained yet
            self.error = str(e)

    def predict(self, img):
        self.load()
        if not self.ready:
            raise HTTPException(503, f'Modèle indisponible : {self.error}')
        with self.torch.no_grad():
            p = self.torch.softmax(self.net(self.tf(img.convert('RGB')).unsqueeze(0)), 1)[0].numpy()
        top = np.argsort(-p)[:5]
        return [{**self.classes[i], 'probability': round(float(p[i]), 4)} for i in top]


MODEL = Model()


def species_labels():
    if not LABELS.exists():
        return {}
    with open(LABELS, encoding='utf-8') as f:
        return {r['scientific_name']: r for r in csv.DictReader(f)}


SPECIES = species_labels()


def sensitive(name):
    r = SPECIES.get(name or '', {})
    return r.get('protected_france') == 'True' or any(x in (r.get('red_list_normandie') or '') for x in ('VU', 'EN', 'CR'))


# ------------------------------------------------------------------ cells (point -> 1 km² cell)
class Cells:
    def __init__(self):
        self.tree = None

    def load(self):
        if self.tree is not None:
            return
        import shapely
        from shapely.geometry import shape
        fc = json.load(gzip.open(CELLS))
        self.ids = [f['properties']['id'] for f in fc['features']]
        self.geoms = np.array([shape(f['geometry']) for f in fc['features']], dtype=object)
        self.tree = shapely.STRtree(self.geoms)
        self.shapely = shapely

    def find(self, lon, lat):
        self.load()
        hit = self.tree.query(self.shapely.Point(lon, lat), predicate='within')
        return self.ids[int(hit[0])] if len(hit) else None


CELL_INDEX = Cells()


# ------------------------------------------------------------------ image processing
def exif_position_and_date(img):
    exif = img.getexif()
    taken = None
    try:
        sub = exif.get_ifd(0x8769)
        raw = sub.get(36867) or exif.get(306)
        if raw:
            taken = dt.datetime.strptime(str(raw), '%Y:%m:%d %H:%M:%S').isoformat()
    except Exception:
        pass
    try:
        gps = exif.get_ifd(0x8825)
        if gps and 2 in gps and 4 in gps:
            def deg(v):
                return float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
            lat = deg(gps[2]) * (-1 if gps.get(1) == 'S' else 1)
            lon = deg(gps[4]) * (-1 if gps.get(3) == 'W' else 1)
            return lat, lon, taken
    except Exception:
        pass
    return None, None, taken


def blur_faces(img):
    import cv2
    arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    faces = cascade.detectMultiScale(cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY), 1.1, 6, minSize=(40, 40))
    for (x, y, w, h) in faces:
        k = max(31, (w // 3) | 1)
        arr[y:y + h, x:x + w] = cv2.GaussianBlur(arr[y:y + h, x:x + w], (k, k), 0)
    return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)), len(faces)


# ------------------------------------------------------------------ API
@app.get('/api/nature/health')
def health():
    MODEL.load()
    return {'model_ready': MODEL.ready, 'model_error': MODEL.error, 'partners': len(partners()),
            'species_labels': len(SPECIES), 'auto_accept_threshold': getattr(MODEL, 'threshold', None)}


@app.get('/api/nature/model')
def model_metrics():
    MODEL.load()
    if not MODEL.ready:
        raise HTTPException(503, MODEL.error)
    m = MODEL.metrics
    return {k: m.get(k) for k in ('arch', 'classes', 'images', 'test_top1', 'test_top5', 'per_group',
                                  'calibration_auto_accept', 'worst_classes', 'history')}


@app.post('/api/nature/photos')
async def upload(file: UploadFile = File(...), observer: str = Form(''), lat: float | None = Form(None),
                 lon: float | None = Form(None), consent_share: bool = Form(False), licence: str = Form('CC-BY-NC'),
                 note: str = Form(''), x_partner_key: str | None = Header(None)):
    partner = require_partner(x_partner_key)
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, 'Photo trop lourde (20 Mo max).')
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise HTTPException(422, 'Fichier image illisible.')
    elat, elon, taken = exif_position_and_date(img)
    source = 'exif'
    if lat is not None and lon is not None:
        elat, elon, source = lat, lon, 'manual'
    if elat is None:
        raise HTTPException(422, 'Position absente : la photo n’a pas de GPS, indiquer latitude et longitude.')
    cell = CELL_INDEX.find(elon, elat)
    if cell is None:
        raise HTTPException(422, 'Position hors de Normandie (aucune maille régionale).')
    img = ImageOps.exif_transpose(img).convert('RGB')  # orientation, then pixels only (EXIF dropped)
    img.thumbnail((1600, 1600))
    img, faces = blur_faces(img)
    top5 = MODEL.predict(img)
    conf = top5[0]['probability']
    thr = MODEL.threshold
    status = 'auto' if (thr is not None and conf >= thr) else 'pending'
    pid = uuid.uuid4().hex
    img.save(PHOTOS / f'{pid}.jpg', 'JPEG', quality=88)  # no exif argument -> no metadata written
    with _lock, db() as con:
        con.execute('INSERT INTO photos VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (pid, dt.datetime.now(dt.timezone.utc).isoformat(), partner['name'], elat, elon, source, cell,
                     taken, json.dumps(top5, ensure_ascii=False), conf, status, None, '[]', int(consent_share),
                     licence, faces, note[:500]))
    return {'id': pid, 'cell_id': cell, 'status': status, 'top5': top5, 'auto_accept_threshold': thr,
            'faces_blurred': faces, 'position_source': source, 'taken_at': taken}


def public_row(r, partner_view):
    top5 = json.loads(r['top5'])
    name = r['species_final'] or top5[0]['scientific_name']
    lat, lon = r['lat'], r['lon']
    generalised = sensitive(name) and not partner_view
    if generalised:  # 10 km precision for sensitive species
        lat, lon = round(lat / 0.09) * 0.09, round(lon / 0.135) * 0.135
    return {'id': r['id'], 'created_at': r['created_at'], 'status': r['status'], 'species': name,
            'top5': top5, 'confidence': r['confidence'], 'cell_id': None if generalised else r['cell_id'],
            'lat': round(lat, 5), 'lon': round(lon, 5), 'location_generalised': generalised,
            'taken_at': r['taken_at'], 'validations': json.loads(r['validations']),
            'licence': r['licence'], 'faces_blurred': r['faces_blurred'],
            'observer': r['observer'] if partner_view else None, 'image': f'/api/nature/photos/{r["id"]}/image'}


@app.get('/api/nature/photos')
def list_photos(status: str | None = None, limit: int = 200, x_partner_key: str | None = Header(None)):
    partner_view = False
    if x_partner_key:
        require_partner(x_partner_key)
        partner_view = True
    q, args = 'SELECT * FROM photos', []
    if status:
        q += ' WHERE status=?'
        args.append(status)
    elif not partner_view:
        q += " WHERE status='confirmed'"
    q += ' ORDER BY created_at DESC LIMIT ?'
    args.append(min(limit, 1000))
    with db() as con:
        return [public_row(r, partner_view) for r in con.execute(q, args)]


@app.get('/api/nature/photos/{pid}/image')
def image(pid: str):
    f = PHOTOS / f'{pid}.jpg'
    if not f.exists() or not pid.isalnum():
        raise HTTPException(404, 'Photo inconnue')
    return FileResponse(f, media_type='image/jpeg')


class Validation(BaseModel):
    decision: str            # confirm | reject | correct
    species: str | None = None


@app.post('/api/nature/photos/{pid}/validate')
def validate(pid: str, v: Validation, x_partner_key: str | None = Header(None)):
    partner = require_partner(x_partner_key)
    if v.decision not in ('confirm', 'reject', 'correct'):
        raise HTTPException(422, 'decision = confirm | reject | correct')
    with _lock, db() as con:
        r = con.execute('SELECT * FROM photos WHERE id=?', (pid,)).fetchone()
        if not r:
            raise HTTPException(404, 'Photo inconnue')
        top5 = json.loads(r['top5'])
        species = v.species if v.decision == 'correct' else (r['species_final'] or top5[0]['scientific_name'])
        vals = [x for x in json.loads(r['validations']) if x['partner'] != partner['name']]
        vals.append({'partner': partner['name'], 'expert': partner.get('expert', False), 'decision': v.decision,
                     'species': species, 'at': dt.datetime.now(dt.timezone.utc).isoformat()})
        agree = [x for x in vals if x['decision'] in ('confirm', 'correct') and x['species'] == species]
        rejects = [x for x in vals if x['decision'] == 'reject']
        if any(x['expert'] for x in agree) or len(agree) >= 2:
            status = 'confirmed'
        elif any(x['expert'] for x in rejects) or len(rejects) >= 2:
            status = 'rejected'
        else:
            status = 'pending'
        con.execute('UPDATE photos SET validations=?, status=?, species_final=? WHERE id=?',
                    (json.dumps(vals, ensure_ascii=False), status, species, pid))
    return {'id': pid, 'status': status, 'species': species, 'validations': vals}


def evidence():
    """Photo-evidence layer: confirmed photos aggregated per cell (separate indicator, not in V/D/P/O)."""
    with db() as con:
        rows = list(con.execute("SELECT * FROM photos WHERE status='confirmed'"))
    cells = {}
    for r in rows:
        name = r['species_final']
        lab = SPECIES.get(name, {})
        c = cells.setdefault(r['cell_id'], {'photos': 0, 'species': set(), 'protected': set(), 'invasive': set(),
                                            'groups': {}, 'effort': set(), 'months': [0] * 12})
        c['photos'] += 1
        c['species'].add(name)
        if lab.get('protected_france') == 'True':
            c['protected'].add(name)
        if lab.get('is_invasive') == 'True':
            c['invasive'].add(name)
        g = lab.get('group_en') or '?'
        c['groups'][g] = c['groups'].get(g, 0) + 1
        day = (r['taken_at'] or r['created_at'])[:10]
        c['effort'].add((r['observer'], day))
        try:
            c['months'][int(day[5:7]) - 1] += 1
        except ValueError:
            pass
    out = {}
    for cid, c in cells.items():
        effort = len(c['effort'])
        out[cid] = {'photos': c['photos'], 'species': len(c['species']), 'protected_species': sorted(c['protected']),
                    'invasive_species': sorted(c['invasive']), 'groups': c['groups'], 'effort_observer_days': effort,
                    'species_per_effort': round(len(c['species']) / effort, 2) if effort else None, 'months': c['months']}
    result = {'meta': {'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'confirmed_photos': len(rows),
                       'cells': len(out),
                       'rule': 'Photos confirmées seulement (2 partenaires d’accord ou 1 expert). Indicateur séparé : ne modifie pas V/D/P/O. '
                               'Une maille sans photo n’est pas pénalisée. Espèces sensibles : positions précises non publiées.'},
              'cells': out}
    EVIDENCE_OUT.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return result


@app.get('/api/nature/evidence')
def get_evidence():
    return evidence()


@app.post('/api/nature/evidence/export')
def export_evidence(x_partner_key: str | None = Header(None)):
    require_partner(x_partner_key)
    r = evidence()
    return {'written': str(EVIDENCE_OUT.relative_to(ROOT)), **r['meta']}


@app.exception_handler(Exception)
def unexpected(_, exc):
    return JSONResponse(status_code=500, content={'detail': f'{type(exc).__name__}: {exc}'})


# Atelier de données (ex renatura-workbench): reference intake -> validation -> quarantine -> populate,
# logged jobs, served at /workbench (UI) and /workbench/api (API). Mounted before the site catch-all.
try:
    from pipeline.workbench.app import app as workbench_app
    app.mount('/workbench', workbench_app)
except Exception as _error:  # missing optional dependency (jsonschema, pillow…): the rest of the site still works
    print('Atelier de données not mounted:', _error)
# Assistant IA (local open model via Ollama + tools on the regional cells): /api/assistant/*
try:
    from pipeline.assistant.chat import router as assistant_router
    app.include_router(assistant_router)
except Exception as _error:
    print('Assistant not mounted:', _error)
# follow_symlink: dist/data/species-images is a link to datasets/normandie_species/images
app.mount('/', StaticFiles(directory=ROOT / 'dist', html=True, follow_symlink=True), name='site')
