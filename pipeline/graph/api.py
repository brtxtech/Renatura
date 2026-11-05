import json,os,re,threading,uuid,subprocess,sys
from pathlib import Path
from fastapi import APIRouter,HTTPException,BackgroundTasks
from pydantic import BaseModel,Field
from neo4j import GraphDatabase,Query,READ_ACCESS,unit_of_work
from neo4j.graph import Node,Relationship,Path as GraphPath
router=APIRouter(prefix='/api/neo4j');ROOT=Path(__file__).resolve().parents[2];jobs={};lock=threading.Lock()
def connection():
 if not os.getenv('NEO4J_URI'):raise HTTPException(503,'Neo4j non configuré. Lancez run-renatura.command dans le ZIP.')
 pw=os.getenv('NEO4J_PASSWORD');return GraphDatabase.driver(os.environ['NEO4J_URI'],auth=(os.getenv('NEO4J_USER','neo4j'),pw) if pw else None,connection_timeout=5)
def serial(v):
 if isinstance(v,Node):return {'kind':'node','id':v.element_id,'labels':list(v.labels),'properties':{k:serial(x) for k,x in dict(v).items() if k!='geometry_json'}}
 if isinstance(v,Relationship):return {'kind':'relationship','id':v.element_id,'type':v.type,'start':v.start_node.element_id,'end':v.end_node.element_id,'properties':dict(v)}
 if isinstance(v,GraphPath):return {'kind':'path','nodes':[serial(n) for n in v.nodes],'relationships':[serial(r) for r in v.relationships]}
 if isinstance(v,dict):return {k:serial(x) for k,x in v.items()}
 if isinstance(v,(list,tuple)):return [serial(x) for x in v]
 return v if v is None or isinstance(v,(str,int,float,bool)) else str(v)
def validate_read_query(query):
 # EXPLAIN below is authoritative for query type; prohibit external I/O and procedures too.
 clean=re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|`[^`]*`",' ',query)
 clean=re.sub(r'/\*.*?\*/|//[^\n]*',' ',clean,flags=re.S)
 if ';' in clean.rstrip().rstrip(';') or re.search(r'\b(CALL|LOAD|CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|ALTER|GRANT|DENY|REVOKE|FOREACH|INSERT)\b',clean,re.I):raise ValueError('Une seule requête de lecture, sans procédure ni accès externe, est autorisée.')
 if not re.match(r'^\s*(MATCH|OPTIONAL|WITH|RETURN|UNWIND|SHOW)\b',clean,re.I):raise ValueError('Commencer par MATCH, OPTIONAL MATCH, WITH, RETURN, UNWIND ou SHOW.')
class ReadQuery(BaseModel):
 query:str=Field(min_length=1,max_length=20000)
 parameters:dict=Field(default_factory=dict)
 limit:int=Field(default=500,ge=1,le=1000)
@router.get('/health')
def health():
 if not os.getenv('NEO4J_URI'):return {'connected':False,'reason':'Neo4j non configuré. Lancez le service local fourni.'}
 try:
  with connection() as db:
   db.verify_connectivity()
   with db.session(database=os.getenv('NEO4J_DATABASE','neo4j')) as s:
    cities=s.run('MATCH(c:Commune) WHERE c.features_imported=true RETURN c.code AS code,c.name AS name,c.imported_at AS imported_at,c.catalog_version AS catalog_version').data()
   from pipeline.graph.import_graph import catalog_signature
   signature=catalog_signature()
   for city in cities:city['catalog_current']=city.get('catalog_version')==signature
   return {'connected':True,'engine':'Neo4j','imported_cities':cities,'relation':'INTERSECTS_DISPLAY','approximation':'Géométries d’affichage simplifiées à 30 m ; pas une intersection cadastrale.'}
 except Exception as e:return {'connected':False,'reason':type(e).__name__+': connexion Neo4j indisponible'}
@router.post('/query')
def query(data:ReadQuery):
 try:validate_read_query(data.query)
 except ValueError as e:raise HTTPException(422,str(e))
 try:
  with connection() as db,db.session(database=os.getenv('NEO4J_DATABASE','neo4j'),default_access_mode=READ_ACCESS) as session:
   summary=session.run(Query('EXPLAIN '+data.query,timeout=10),data.parameters).consume()
   if summary.query_type!='r':raise HTTPException(422,'La requête doit être strictement en lecture.')
   @unit_of_work(timeout=20)
   def read(tx):
    result=tx.run(data.query,data.parameters);columns=result.keys();rows=[serial(dict(r)) for r in result.fetch(data.limit+1)];return columns,rows
   columns,rows=session.execute_read(read)
   return {'engine':'Neo4j','columns':list(columns),'rows':rows[:data.limit],'truncated':len(rows)>data.limit,'limit':data.limit}
 except HTTPException:raise
 except Exception as e:raise HTTPException(400,type(e).__name__+': '+str(e)[:1200])
class ImportCity(BaseModel):city:str=Field(min_length=1,max_length=100)
@router.post('/import')
def import_city(data:ImportCity,background:BackgroundTasks):
 if not os.getenv('NEO4J_URI'):raise HTTPException(503,'Configurer Neo4j dans le service local.')
 if not lock.acquire(blocking=False):raise HTTPException(409,'Un import est déjà en cours.')
 ident=uuid.uuid4().hex;jobs[ident]={'status':'running','city':data.city}
 def work():
  try:
   r=subprocess.run([sys.executable,str(ROOT/'pipeline/graph/import_graph.py'),'--city',data.city],cwd=ROOT,capture_output=True,text=True,timeout=3600);jobs[ident].update(status='succeeded' if r.returncode==0 else 'failed',log=(r.stdout+r.stderr)[-4000:])
  except Exception as e:jobs[ident].update(status='failed',log=type(e).__name__)
  finally:lock.release()
 background.add_task(work);return {'id':ident,**jobs[ident]}
@router.get('/jobs/{ident}')
def job(ident:str):
 if ident not in jobs:raise HTTPException(404,'Import inconnu')
 return jobs[ident]
