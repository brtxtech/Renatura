import os,json,uuid,hashlib,io
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI,UploadFile,File,Form,HTTPException,Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from PIL import Image,ImageOps,UnidentifiedImageError
from . import db,workflow
from .validation import validate
from .calculation import calculate
from .models import Config,ChatInput,NodeInput,LabelInput

@asynccontextmanager
async def lifespan(app):
    db.init();yield
app=FastAPI(title='Renatura • Atelier de données',version='2.0.0',lifespan=lifespan)
# Mounted as a sub-application (/workbench) the lifespan of the sub-app does not run: initialise at import.
db.init()

WRITE_METHODS={'POST','PUT','PATCH','DELETE'}

def partner_for(key):
    """Renatura partner keys (same as the nature-photo service), stored hashed in user-data/nature/partners.json."""
    if not key:return None
    store=Path(os.environ.get('RENATURA_NATURE_STORE') or db.PROJECT/'user-data'/'nature')/'partners.json'
    try:partners=json.loads(store.read_text())
    except (OSError,ValueError):return None
    return partners.get(hashlib.sha256(key.encode()).hexdigest())

@app.middleware('http')
async def limits(request:Request,call_next):
    """Access rules: reading and writing are open on the local workbench; every write is written to the audit
    log. For a shared / online deployment set RENATURA_WORKBENCH_REQUIRE_KEY=1: writes then need a Renatura
    partner key (header X-Partner-Key). RENATURA_TOKEN (header X-Workspace-Token) protects everything when set."""
    from fastapi.responses import JSONResponse
    path=request.url.path
    is_api=path.startswith('/api') or '/api/' in path
    token=os.environ.get('RENATURA_TOKEN')
    token_ok=bool(token) and request.headers.get('X-Workspace-Token')==token
    partner=partner_for(request.headers.get('X-Partner-Key'))
    if is_api:
        if token and not token_ok and not partner:
            return JSONResponse({'detail':'Clé partenaire ou jeton d’espace requis'},status_code=401)
        if request.method in WRITE_METHODS and os.environ.get('RENATURA_WORKBENCH_REQUIRE_KEY')=='1' and not (partner or token_ok):
            return JSONResponse({'detail':'Clé partenaire requise pour modifier les données (lecture libre).'},status_code=401)
    length=request.headers.get('content-length')
    if length and int(length)>27*1024*1024:return JSONResponse({'detail':'Request exceeds 27 MiB limit'},status_code=413)
    response=await call_next(request)
    if is_api and request.method in WRITE_METHODS:
        who=(partner or {}).get('name') or ('jeton d’espace' if token_ok else (request.client.host if request.client else 'local'))
        db.event('audit','access',f'{request.method} {path} · {who} · HTTP {response.status_code}','info' if response.status_code<400 else 'warning')
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    return response

@app.get('/api/whoami')
def whoami(request:Request):
    p=partner_for(request.headers.get('X-Partner-Key'))
    return {'partner':p.get('name') if p else None,'expert':bool(p and p.get('expert')),'can_write':bool(p) or os.environ.get('RENATURA_WORKBENCH_REQUIRE_KEY')!='1'}

def found(kind,key):
    value=db.get(kind,key)
    if value is None:raise HTTPException(404,'Not found')
    return value

def strict_json(text):
    return json.loads(text,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Non-finite JSON value: '+x)))

def recalculate():
    cfg=db.get('config','active') or Config().model_dump()
    result=calculate(cfg);db.put('calculation','latest',result);db.event('workspace','calculation','Indicators recalculated from imported valid records');return result

@app.get('/api/state')
def state():
    datasets=db.all_docs('datasets')
    return {'catalog':db.all_docs('catalog'),'datasets':[{k:v for k,v in d.items() if k not in ('data','anomalies')} for d in datasets],'observations':db.all_docs('observations'),'jobs':[{k:v for k,v in j.items() if k not in ('payload','output')} for j in db.all_docs('jobs')[:30]],'calculation':db.get('calculation','latest') or calculate(Config().model_dump()),'config':db.get('config','active') or Config().model_dump(),'model_status':{'alexnet':bool(os.getenv('ALEXNET_WEIGHTS') and os.getenv('ALEXNET_LABELS')),'language_model':bool(os.getenv('LLM_BASE_URL') and os.getenv('LLM_MODEL'))}}
@app.get('/api/catalog/{key}')
def catalog(key:str):return found('catalog',key)
@app.get('/api/datasets/{key}')
def dataset(key:str):
    d=found('datasets',key);return {k:v for k,v in d.items() if k!='data'}
@app.get('/api/datasets/{key}/data')
def dataset_data(key:str):return found('datasets',key)['data']
@app.post('/api/datasets')
async def import_data(file:UploadFile=File(...),name:str=Form(...),category:str=Form('Biodiversité'),catalog_id:str=Form(''),collection_state:str=Form('unknown'),schema_text:str=Form(''),required_fields:str=Form(''),replace_dataset_id:str=Form('')):
    raw=await file.read(25*1024*1024+1)
    if len(raw)>25*1024*1024:raise HTTPException(413,'Maximum JSON upload: 25 MiB; split large layers into batches')
    if collection_state not in ('complete','partial','unknown'):raise HTTPException(422,'Collection state must be complete, partial or unknown')
    if catalog_id and not db.get('catalog',catalog_id):raise HTTPException(422,'Unknown catalogue layer')
    previous=found('datasets',replace_dataset_id) if replace_dataset_id else None
    before=calculate(db.get('config','active') or Config().model_dump())
    try:
        data=strict_json(raw.decode('utf-8-sig'))
        if isinstance(data,dict) and data.get('crs'):raise ValueError('Remove legacy CRS and reproject to WGS84 before importing')
        schema=strict_json(schema_text) if schema_text.strip() else (previous['schema'] if previous else None)
        validated=await run_in_threadpool(validate,data,schema,[v.strip() for v in required_fields.split(',') if v.strip()])
    except Exception as e:raise HTTPException(422,str(e)[:600]) from e
    key=replace_dataset_id or uuid.uuid4().hex
    revision=uuid.uuid4().hex
    doc={'id':key,'name':name[:200],'category':category[:200],'catalog_id':catalog_id or None,'collection_state':collection_state,'kind':'geojson' if validated['is_geojson'] else 'json','source_filename':Path(file.filename or 'upload.json').name,'sha256':hashlib.sha256(raw).hexdigest(),'revision':revision,'schema':validated['schema'],'profile':validated['profile'],'schema_origin':validated['schema_origin'],'valid_count':validated['valid_count'],'rejected_count':validated['rejected_count'],'total_count':validated['total_count'],'anomalies':validated['anomalies'],'data':validated['data']}
    if previous:db.put('dataset_revisions',previous['revision'],previous)
    db.put('datasets',key,doc);db.event('workspace','parsing',f"Imported {doc['name']}: {doc['valid_count']} accepted, {doc['rejected_count']} quarantined")
    calc=recalculate()
    return {'dataset':{k:v for k,v in doc.items() if k not in ('data','anomalies')},'anomalies':doc['anomalies'][:100],'calculation':calc,'previous_calculation':before}
@app.get('/api/config')
def config():return db.get('config','active') or Config().model_dump()
@app.put('/api/config')
def update_config(body:Config):
    db.put('config','active',body.model_dump());return recalculate()
@app.post('/api/calculate')
def preview_config(body:Config):return calculate(body.model_dump())
@app.post('/api/images')
async def image(file:UploadFile=File(...)):
    raw=await file.read(12*1024*1024+1)
    if len(raw)>12*1024*1024:raise HTTPException(413,'Image exceeds 12 MiB')
    try:
        Image.MAX_IMAGE_PIXELS=24_000_000
        with Image.open(io.BytesIO(raw)) as im:
            if im.width*im.height>24_000_000:raise ValueError('Image exceeds 24 megapixels')
            im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((2000,2000))
            key=uuid.uuid4().hex;directory=db.DATA/'images';directory.mkdir(exist_ok=True)
            im.save(directory/(key+'.jpg'),quality=88)
            doc={'id':key,'filename':key+'.jpg','original_name':Path(file.filename or 'camera.jpg').name,'width':im.width,'height':im.height,'url':'api/images/'+key}
    except Exception as e:raise HTTPException(422,'Image could not be decoded; use a JPEG, PNG or WebP within the size limits') from e
    db.put('images',key,doc);return doc
@app.get('/api/images/{key}')
def get_image(key:str):return FileResponse(db.DATA/'images'/found('images',key)['filename'],media_type='image/jpeg')
@app.get('/api/nodes')
def nodes():
    return [{'id':node,'file':node+'.py','source':(db.ROOT/'nodes'/f'{node}.py').read_text()} for node in workflow.OBSERVATION_NODES]
@app.post('/api/chat',status_code=202)
def chat(body:ChatInput):
    if not body.context and not body.image_id:raise HTTPException(422,'Supply an image or context')
    if body.image_id:found('images',body.image_id)
    if len(workflow.ACTIVE)>=4:raise HTTPException(429,'Maximum four concurrent jobs')
    return {'id':workflow.create(body.model_dump()),'state':'queued'}
@app.post('/api/nodes/{node}/run',status_code=202)
def run_node(node:str,body:NodeInput):
    if node not in workflow.NODES:raise HTTPException(404,'Unknown node')
    if len(workflow.ACTIVE)>=4:raise HTTPException(429,'Maximum four concurrent jobs')
    return {'id':workflow.create(body.payload,node)}
@app.get('/api/jobs/{key}')
def job(key:str):return found('jobs',key)
@app.post('/api/jobs/{key}/stop')
def stop_job(key:str):
    found('jobs',key);return {'stop_requested':workflow.stop(key)}
@app.post('/api/jobs/{key}/nodes/{node}/stop')
def stop_node(key:str,node:str):
    found('jobs',key);return {'stop_requested':workflow.stop(key,node)}
@app.get('/api/logs')
def logs(job:str|None=None,after:int=0):return db.events(job,after)
@app.patch('/api/observations/{key}')
def label(key:str,body:LabelInput):
    o=found('observations',key);o['label']=body.label;o['review_status']='user_labelled_unverified';return db.put('observations',key,o)
@app.get('/api/export')
def export():
    # Images are referenced by ID; binary files are in runtime/images and a backup must include them.
    return {'type':'FeatureCollection','features':[{'type':'Feature','geometry':{'type':'Point','coordinates':[o['location']['lon'],o['location']['lat']]} if o.get('location') else None,'properties':o} for o in db.all_docs('observations')]}
from .intake_api import router as intake_router
app.include_router(intake_router)
app.mount('/',StaticFiles(directory=db.PROJECT/'dist'/'workbench',html=True),name='frontend')
