"""SQLite documents + events for the Renatura data workbench, with daily JSON-lines log files."""
import json, os, sqlite3, threading
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent            # pipeline/workbench
PROJECT = ROOT.parents[1]                          # Renatura project root
DATA = Path(os.environ.get('RENATURA_WORKBENCH_DATA') or os.environ.get('RENATURA_DATA') or PROJECT / 'user-data' / 'workbench')
DATA.mkdir(parents=True, exist_ok=True)
LOGS = DATA / 'logs'
LOGS.mkdir(exist_ok=True)
LOCK = threading.RLock()
_LOG_LOCK = threading.Lock()


def log_file(job, node, level, message):
    """Append one JSON line per event to logs/workbench-YYYY-MM-DD.log (audit trail outside SQLite)."""
    now = datetime.now(timezone.utc)
    line = json.dumps({'at': now.isoformat(), 'job': job, 'node': node, 'level': level, 'message': message}, ensure_ascii=False)
    try:
        with _LOG_LOCK, open(LOGS / f'workbench-{now:%Y-%m-%d}.log', 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass  # logging must never break the pipeline

def connect():
    c = sqlite3.connect(DATA / 'renatura.sqlite', timeout=30)
    c.row_factory = sqlite3.Row
    return c

def init():
    with connect() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS documents(kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id));
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT, node TEXT, level TEXT, message TEXT, at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
        ''')
    # Interrupted processes cannot resume a Python thread after restart.
    for job in all_docs('jobs'):
        if job.get('state') in ('queued','running'):
            job['state']='interrupted'; put('jobs',job['id'],job)
    for batch in all_docs('batches'):
        if batch.get('state') in ('queued','checking','validated'):
            batch['state']='interrupted';put('batches',batch['id'],batch)
    if not all_docs('catalog'):
        for row in json.loads((ROOT/'data/catalog.json').read_text()): put('catalog',row['id'],row)

def put(kind, key, body):
    with LOCK, connect() as c:
        c.execute('INSERT OR REPLACE INTO documents VALUES (?,?,?)',(kind,key,json.dumps(body,ensure_ascii=False,allow_nan=False)))
    return body

def get(kind,key):
    with connect() as c:
        row=c.execute('SELECT body FROM documents WHERE kind=? AND id=?',(kind,key)).fetchone()
    return json.loads(row['body']) if row else None

def all_docs(kind):
    with connect() as c: rows=c.execute('SELECT body FROM documents WHERE kind=? ORDER BY rowid DESC',(kind,)).fetchall()
    return [json.loads(r['body']) for r in rows]

def event(job,node,message,level='info'):
    with connect() as c: c.execute('INSERT INTO events(job,node,level,message) VALUES(?,?,?,?)',(job,node,level,message))
    log_file(job,node,level,message)

def events(job=None,after=0):
    with connect() as c:
        rows=c.execute('SELECT * FROM events WHERE seq>? '+('AND job=? ' if job else '')+'ORDER BY seq LIMIT 1000',([after,job] if job else [after])).fetchall()
    return [dict(r) for r in rows]


def remove(kind,key):
    with LOCK, connect() as c:
        c.execute('DELETE FROM documents WHERE kind=? AND id=?',(kind,key))


def recent_events(limit=300):
    with connect() as c:
        rows=c.execute('SELECT * FROM events ORDER BY seq DESC LIMIT ?', (max(1,min(1000,limit)),)).fetchall()
    return [dict(r) for r in reversed(rows)]
