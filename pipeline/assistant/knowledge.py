"""Renatura knowledge base (RAG): documents you can inspect, add, disable and delete; semantic search with a
Hugging Face sentence-embedding model, lexical fallback when the model is not available.

  .venv-normandie/bin/python -m pipeline.assistant.knowledge build      # import corpus + method docs, embed
  .venv-normandie/bin/python -m pipeline.assistant.knowledge search "haies du Pays d'Auge"

Storage (git-ignored): user-data/knowledge/knowledge.db (SQLite: documents, chunks, float16 embeddings).
Config (environment):
  RENATURA_EMBED_MODEL   Hugging Face model id (default dangvantuan/sentence-camembert-base, French)
  RENATURA_KNOWLEDGE_DIR storage folder (default user-data/knowledge)
  HF_HUB_OFFLINE=1       never download, use the local Hugging Face cache only
Sources imported by `build`:
  datasets/normandie_species/rag/corpus.jsonl   species, ecosystems, regional and topic sheets (pre-chunked)
  docs/METHODOLOGY.md, PLAN_REGIONAL_SCORING.md, EXTENSIONS.md, VALIDATION.md, pipeline/renatura_ai/README.md
"""
from __future__ import annotations

import datetime as dt
import io
import json
import math
import os
import re
import sqlite3
import sys
import threading
import unicodedata
import uuid
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
STORE = Path(os.getenv('RENATURA_KNOWLEDGE_DIR', ROOT / 'user-data/knowledge'))
DB = STORE / 'knowledge.db'
MODEL = os.getenv('RENATURA_EMBED_MODEL', 'dangvantuan/sentence-camembert-base')
CORPUS = ROOT / 'datasets/normandie_species/rag/corpus.jsonl'
METHOD_DOCS = ['docs/METHODOLOGY.md', 'docs/PLAN_REGIONAL_SCORING.md', 'docs/EXTENSIONS.md', 'docs/VALIDATION.md',
               'pipeline/renatura_ai/README.md']
MAX_TEXT = 400_000
_lock = threading.RLock()
_cache = {'version': None, 'ids': None, 'matrix': None, 'lexical': None}
_embedder = {'model': None, 'error': None}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def connect():
    STORE.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript("""
      CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, title TEXT, source TEXT, origin TEXT, category TEXT,
        enabled INTEGER DEFAULT 1, created_at TEXT, n_chunks INTEGER DEFAULT 0, chars INTEGER DEFAULT 0);
      CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY, doc_id TEXT, idx INTEGER, text TEXT, embedding BLOB);
      CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
      CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);""")
    return c


def _bump(c):
    c.execute("INSERT INTO meta(key,value) VALUES('version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (uuid.uuid4().hex,))


# ---------------------------------------------------------------- embeddings (Hugging Face)

def embedder():
    """sentence-transformers model from the Hugging Face hub / local cache; None -> lexical search."""
    with _lock:
        if _embedder['model'] is None and _embedder['error'] is None:
            try:
                from sentence_transformers import SentenceTransformer
                device = 'mps' if __import__('torch').backends.mps.is_available() else 'cpu'
                try:
                    _embedder['model'] = SentenceTransformer(MODEL, device=device, local_files_only=True)
                except Exception:
                    if os.getenv('HF_HUB_OFFLINE') == '1':
                        raise
                    _embedder['model'] = SentenceTransformer(MODEL, device=device)  # first use: download from the hub
            except Exception as e:
                _embedder['error'] = f'{type(e).__name__}: {str(e)[:200]}'
        return _embedder['model']


def embed(texts):
    m = embedder()
    if m is None:
        return None
    v = m.encode(list(texts), batch_size=32, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(v, dtype=np.float16)


# ---------------------------------------------------------------- chunking & text extraction

def chunk_text(text, size=1100, overlap=150):
    """Split on headings / paragraphs, then pack into ~size-character chunks."""
    text = re.sub(r'\r\n?', '\n', text).strip()
    parts = [p.strip() for p in re.split(r'\n(?=#{1,4} )|\n\s*\n', text) if p.strip()]
    chunks, cur = [], ''
    for p in parts:
        while len(p) > size:  # very long paragraph
            chunks.append((cur + '\n\n' + p[:size]).strip() if cur else p[:size])
            cur, p = '', p[size - overlap:]
        if len(cur) + len(p) + 2 > size and cur:
            chunks.append(cur)
            cur = cur[-overlap:] + '\n\n' + p if overlap else p
        else:
            cur = (cur + '\n\n' + p).strip()
    if cur:
        chunks.append(cur)
    return chunks


def extract_text(filename, raw):
    name = filename.lower()
    if name.endswith('.pdf'):
        from pypdf import PdfReader
        return '\n\n'.join((p.extract_text() or '') for p in PdfReader(io.BytesIO(raw)).pages)
    if name.endswith(('.json', '.geojson')):  # indented so that passages stay readable and searchable
        text = raw.decode('utf-8-sig', errors='replace')
        try:
            return json.dumps(json.loads(text), ensure_ascii=False, indent=1)
        except ValueError:
            return text
    if name.endswith(('.md', '.txt', '.csv')):
        return raw.decode('utf-8', errors='replace')
    raise ValueError('formats acceptés : .md, .txt, .pdf, .csv, .json, .geojson')


# ---------------------------------------------------------------- documents

def add_document(title, text, source='', origin='user', category='ajout', chunks=None, c=None, embed_now=True):
    title = (title or '').strip()[:200]
    text = (text or '').strip()
    if not title:
        raise ValueError('titre obligatoire')
    if len(text) < 20 and not chunks:
        raise ValueError('texte trop court (20 caractères minimum)')
    if len(text) > MAX_TEXT:
        raise ValueError(f'texte trop long ({MAX_TEXT:,} caractères maximum)')
    own = c is None
    c = c or connect()
    parts = chunks or chunk_text(text)
    vec = embed(parts) if embed_now else None
    did = uuid.uuid4().hex[:16]
    c.execute('INSERT INTO documents VALUES(?,?,?,?,?,1,?,?,?)',
              (did, title, (source or '')[:500], origin, category, now(), len(parts), sum(map(len, parts))))
    c.executemany('INSERT INTO chunks VALUES(?,?,?,?,?)',
                  [(f'{did}:{i}', did, i, t, None if vec is None else vec[i].tobytes()) for i, t in enumerate(parts)])
    _bump(c)
    if own:
        c.commit()
        c.close()
    return did


def list_documents(q='', origin='', limit=200, offset=0):
    c = connect()
    sql, args = 'SELECT * FROM documents WHERE 1=1', []
    if q:
        sql += ' AND (title LIKE ? OR source LIKE ?)'
        args += [f'%{q}%', f'%{q}%']
    if origin:
        sql += ' AND origin = ?'
        args.append(origin)
    total = c.execute(sql.replace('SELECT *', 'SELECT COUNT(*)'), args).fetchone()[0]
    rows = [dict(r) for r in c.execute(sql + ' ORDER BY origin, category, title LIMIT ? OFFSET ?', args + [int(limit), int(offset)])]
    c.close()
    return {'total': total, 'documents': rows}


def get_document(did):
    c = connect()
    d = c.execute('SELECT * FROM documents WHERE id=?', (did,)).fetchone()
    if d is None:
        c.close()
        return None
    ch = [r['text'] for r in c.execute('SELECT text FROM chunks WHERE doc_id=? ORDER BY idx', (did,))]
    c.close()
    return {**dict(d), 'chunks': ch}


def set_enabled(did, enabled):
    c = connect()
    n = c.execute('UPDATE documents SET enabled=? WHERE id=?', (1 if enabled else 0, did)).rowcount
    _bump(c); c.commit(); c.close()
    return n > 0


def delete_document(did):
    c = connect()
    n = c.execute('DELETE FROM documents WHERE id=?', (did,)).rowcount
    c.execute('DELETE FROM chunks WHERE doc_id=?', (did,))
    _bump(c); c.commit(); c.close()
    return n > 0


def stats():
    c = connect()
    by = {r['origin']: {'documents': r['n'], 'actifs': r['on'], 'passages': r['ch']} for r in c.execute(
        'SELECT origin, COUNT(*) n, SUM(enabled) on_, SUM(n_chunks) ch FROM documents GROUP BY origin'.replace('on_', '"on"'))}
    missing = c.execute('SELECT COUNT(*) FROM chunks WHERE embedding IS NULL').fetchone()[0]
    c.close()
    m = embedder()
    return {'model': MODEL, 'mode': 'semantique (Hugging Face)' if m is not None else 'lexical (modèle indisponible)',
            'model_error': _embedder['error'], 'store': str(DB.relative_to(ROOT)) if DB.is_relative_to(ROOT) else str(DB),
            'origins': by, 'chunks_without_embedding': missing}


# ---------------------------------------------------------------- search

def _norm(s):
    return unicodedata.normalize('NFKD', s.lower()).encode('ascii', 'ignore').decode()


def _tokens(s):
    return [t for t in re.findall(r'[a-z0-9]{3,}', _norm(s))]


def _load_index(c):
    version = (c.execute("SELECT value FROM meta WHERE key='version'").fetchone() or [None])[0]
    if _cache['version'] == version and _cache['ids'] is not None:
        return
    rows = c.execute('SELECT ch.id, ch.text, ch.embedding, d.title FROM chunks ch JOIN documents d ON d.id = ch.doc_id WHERE d.enabled = 1').fetchall()
    ids = [r['id'] for r in rows]
    emb = [np.frombuffer(r['embedding'], dtype=np.float16) if r['embedding'] else None for r in rows]
    dim = next((len(e) for e in emb if e is not None), 0)
    matrix = np.stack([e if e is not None else np.zeros(dim, np.float16) for e in emb]).astype(np.float32) if dim else None
    # lexical index (BM25-like) for the fallback and to re-rank exact names
    docs = [Counter(_tokens(r['text']) + 2 * _tokens(r['title'] or '')) for r in rows]   # title counts in every chunk
    df = Counter(t for d in docs for t in d)
    _cache.update(version=version, ids=ids, matrix=matrix, lexical=(docs, df, np.mean([sum(d.values()) for d in docs]) if docs else 1))


def search(query, k=5, origin=None):
    query = (query or '').strip()
    if not query:
        return []
    c = connect()
    with _lock:
        _load_index(c)
        ids, matrix, (docs, df, avg) = _cache['ids'], _cache['matrix'], _cache['lexical']
    if not ids:
        c.close()
        return []
    n = len(ids)
    q = _tokens(query)
    lex = np.array([sum((math.log(1 + (n - df[t] + .5) / (df[t] + .5)) * d[t] * 2.2) / (d[t] + 1.2 * (.25 + .75 * sum(d.values()) / avg))
                        for t in q if t in d) for d in docs]) if q else np.zeros(n)
    qv = embed([query]) if matrix is not None else None
    if qv is not None:
        sem = matrix @ qv[0].astype(np.float32)
        score = sem + 0.35 * lex / (lex.max() + 1e-9)          # hybrid: meaning + exact words (technical terms, names)
        mode = 'semantique'
    else:
        score, mode = lex, 'lexical'
    order = np.argsort(-score)[: max(1, min(int(k), 20)) * 3]
    out, seen = [], Counter()
    for i in order:
        cid = ids[i]
        r = c.execute('SELECT ch.text, d.id doc_id, d.title, d.source, d.origin, d.category FROM chunks ch JOIN documents d ON d.id=ch.doc_id WHERE ch.id=?', (cid,)).fetchone()
        if r is None or (origin and r['origin'] != origin) or seen[r['doc_id']] >= 2:
            continue
        seen[r['doc_id']] += 1
        out.append({'titre': r['title'], 'source': r['source'], 'origine': r['origin'], 'categorie': r['category'],
                    'doc_id': r['doc_id'], 'passage': r['text'][:1200], 'score': round(float(score[i]), 3), 'mode': mode})
        if len(out) >= k:
            break
    c.close()
    return out


# ---------------------------------------------------------------- build

def method_sheet_fr():
    """French description of how the map is computed, from the same definitions the assistant tools use."""
    from . import tools
    scoring = json.load(open(ROOT / 'dist/data/normandie/layer_scoring.json'))
    lines = ['# Méthode de calcul Renatura', '',
             'Renatura découpe la Normandie en 30 850 mailles hexagonales de 1 km² et calcule pour chacune quatre critères, '
             'puis la priorité de restauration (RP).', '']
    for k in ['V', 'D', 'P', 'O', 'RP']:
        lines += [f'## {k} · {tools.NAMES[k]}', tools.METHODS[k], '']
        layers = sorted([l for l in scoring['layers'] if l['c'] == k], key=lambda l: -l['w'])
        if layers:
            lines.append('Couches et poids : ' + ' ; '.join(f"{l['label']} (poids {l['w']})" for l in layers) + '.')
            lines.append('')
    lines += ['## Formule et règles de calcul de la priorité de restauration'] + tools.FORMULA['etapes'] + [
        f"Couverture minimale : {int(100 * scoring.get('min_weight_coverage', .3))} % du poids d'un critère, sinon donnée absente.",
        'Une valeur absente est une donnée absente, jamais 0. Une couche partielle ne peut que relever un score.', '']
    try:
        st = json.load(open(ROOT / 'dist/data/normandie/ml_status.json'))
        lines += ['## Modèles IA Renatura (prédictions)']
        for name, m in st['models'].items():
            lines.append(f"{m.get('title', name)} : {m.get('question', '')} Cible observée : {m.get('target_label', '')}. "
                         f"Apprentissage : {m.get('train', '')}. Test : {m.get('test', '')}. Statut : {m.get('status')}.")
    except (OSError, ValueError):
        pass
    return '\n'.join(lines)




def build(rebuild=False):
    c = connect()
    if rebuild:
        c.execute("DELETE FROM chunks WHERE doc_id IN (SELECT id FROM documents WHERE origin IN ('corpus','methode'))")
        c.execute("DELETE FROM documents WHERE origin IN ('corpus','methode')")
    have = {r['source'] for r in c.execute("SELECT source FROM documents WHERE origin IN ('corpus','methode')")}
    added = 0
    if CORPUS.exists():
        groups = {}
        for line in open(CORPUS, encoding='utf-8'):
            r = json.loads(line)
            groups.setdefault(r.get('doc_path') or r['id'], []).append(r)
        for path, rows in groups.items():
            src = f'corpus:{path}'
            if src in have:
                continue
            first = rows[0]['text'].lstrip()
            title = re.sub(r'^#+\s*', '', first.splitlines()[0])[:200] if first else path
            cat = path.split('/')[0] if '/' in path else (rows[0].get('metadata') or {}).get('type', 'corpus')
            add_document(title, '\n\n'.join(r['text'] for r in rows), src, 'corpus', cat,
                         chunks=[r['text'] for r in rows], c=c, embed_now=False)
            added += 1
    if 'methode:fiche-fr' not in have:  # French method sheet (the docs/*.md files are in English)
        add_document('Méthode de calcul Renatura : V, D, P, O, priorité de restauration et modèles IA', method_sheet_fr(),
                     'methode:fiche-fr', 'methode', 'méthode Renatura', c=c, embed_now=False)
        added += 1
    for rel in METHOD_DOCS:
        p = ROOT / rel
        if p.exists() and f'methode:{rel}' not in have:
            text = p.read_text(encoding='utf-8')
            title = next((re.sub(r'^#+\s*', '', l) for l in text.splitlines() if l.startswith('#')), p.stem)
            add_document(title, text, f'methode:{rel}', 'methode', 'méthode Renatura', c=c, embed_now=False)
            added += 1
    c.commit()
    # embed in batches (resumable)
    todo = c.execute('SELECT id, text FROM chunks WHERE embedding IS NULL').fetchall()
    if todo and embedder() is not None:
        for s in range(0, len(todo), 256):
            batch = todo[s:s + 256]
            vec = embed([r['text'] for r in batch])
            c.executemany('UPDATE chunks SET embedding=? WHERE id=?', [(vec[i].tobytes(), r['id']) for i, r in enumerate(batch)])
            c.commit()
            print(f'  embedded {min(s + 256, len(todo))}/{len(todo)}', flush=True)
    _bump(c); c.commit(); c.close()
    st = stats()
    print(json.dumps({'documents_added': added, **st}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'build':
        build(rebuild='--rebuild' in sys.argv)
    elif len(sys.argv) > 2 and sys.argv[1] == 'search':
        for r in search(' '.join(sys.argv[2:])):
            print(f"{r['score']:.3f} [{r['origine']}/{r['categorie']}] {r['titre']}\n    {r['passage'][:160].replace(chr(10), ' ')}")
    else:
        print(__doc__)
