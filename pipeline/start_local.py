"""Start the real local Neo4j service, import Caen once, then serve the UI and APIs."""
import os,secrets,subprocess,sys,time,webbrowser,hashlib
from pathlib import Path
from neo4j import GraphDatabase
ROOT=Path(__file__).resolve().parents[1];os.chdir(ROOT)
envfile=ROOT/'.env'
if not envfile.exists():envfile.write_text('NEO4J_PASSWORD='+secrets.token_urlsafe(24)+'\n');envfile.chmod(0o600)
for line in envfile.read_text().splitlines():
 if '=' in line and not line.startswith('#'):
  k,v=line.split('=',1);os.environ.setdefault(k.strip(),v.strip())
os.environ.setdefault('NEO4J_URI','bolt://127.0.0.1:7687');os.environ.setdefault('NEO4J_USER','neo4j')
try:subprocess.run(['docker','compose','up','-d'],check=True)
except Exception:sys.exit('Démarrer Docker Desktop puis relancer run-renatura.command.')
db=GraphDatabase.driver(os.environ['NEO4J_URI'],auth=(os.environ['NEO4J_USER'],os.environ['NEO4J_PASSWORD']))
print('Attente de Neo4j…',flush=True)
for attempt in range(90):
 try:db.verify_connectivity();break
 except Exception:
  if attempt==89:sys.exit('Neo4j ne répond pas. Vérifier docker compose logs neo4j.')
  time.sleep(2)
with db.session() as session:ready=session.run('MATCH(c:Commune {id:"14118"}) RETURN c.features_imported AS ready,c.catalog_version AS version').single()
db.close()
sys.path.insert(0,str(ROOT))
from pipeline.graph.import_graph import catalog_signature
if not ready or not ready['ready'] or ready['version']!=catalog_signature():
 print('Premier lancement : import réel des données liées à Caen. Cela peut prendre plusieurs minutes.',flush=True)
 subprocess.run([sys.executable,'pipeline/graph/import_graph.py','--city','Caen'],check=True)
print('Renatura : http://localhost:8080/ — Neo4j : http://localhost:7474/ (identifiants locaux dans .env)',flush=True)
webbrowser.open('http://localhost:8080/')
subprocess.run([sys.executable,'-m','uvicorn','pipeline.atlas.server:app','--host','127.0.0.1','--port','8080'],check=True)
