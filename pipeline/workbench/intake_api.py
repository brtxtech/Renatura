import json,uuid,hashlib
from datetime import datetime,timezone
from typing import Literal
from fastapi import APIRouter,UploadFile,File,Form,HTTPException
from pydantic import BaseModel,Field
from . import db,workflow
from .calculation import calculate
from .validation import validate
from .publish import publish,unpublish
router=APIRouter(prefix='/api/intake')

def now():return datetime.now(timezone.utc).isoformat()
def found(kind,key):
    d=db.get(kind,key)
    if not d:raise HTTPException(404,'Not found')
    return d

def categories():
    existing=db.all_docs('categories')
    if not existing:
        names=sorted({c['category'] for c in db.all_docs('catalog')}|{'Climat','Foncier','Images et espèces'})
        for i,name in enumerate(names):db.put('categories',f'category-{i+1:02}',{'id':f'category-{i+1:02}','name':name,'description':'Normandie evidence category'})
    return db.all_docs('categories')

def refresh_calculation():
    r=calculate(db.get('config','active') or {'rules':[]});db.put('calculation','latest',r);return r

def compact(b):return {k:v for k,v in b.items() if k!='validation'}

def category_id(d,cs):return d.get('category_id') or next((c['id'] for c in cs if c['name']==d.get('category')),None)

@router.get('/state')
def state():
    cs=categories();datasets=db.all_docs('datasets');batches=db.all_docs('batches');catalog=db.all_docs('catalog')
    for c in cs:
        ds=[d for d in datasets if category_id(d,cs)==c['id']];bs=[b for b in batches if b['category_id']==c['id']]
        c.update(dataset_count=len(ds),element_count=sum(d['valid_count'] for d in ds),quarantined=sum(b.get('rejected_count',0) for b in bs),references=sum(1 for r in catalog if r['category']==c['name']),state='empty' if not ds else ('complete_declared' if all(d['collection_state']=='complete' for d in ds) else 'partial_or_unknown'))
    return {'categories':cs,'datasets':[{k:v for k,v in d.items() if k not in ('data','anomalies')} for d in datasets],'batches':[compact(b) for b in batches],'catalog':catalog,'trash':[{'id':t['id'],'label':t['label'],'kind':t['kind'],'deleted_at':t['deleted_at']} for t in db.all_docs('trash')],'logs':db.recent_events(),'jobs':[{k:v for k,v in j.items() if k not in ('payload','output')} for j in db.all_docs('jobs')[:20]]}
class CategoryInput(BaseModel):
    name:str=Field(min_length=1,max_length=200)
    description:str=Field(default='',max_length=1000)
@router.post('/categories')
def add_category(body:CategoryInput):
    if any(c['name'].casefold()==body.name.strip().casefold() for c in categories()):raise HTTPException(409,'Category already exists')
    key=uuid.uuid4().hex;return db.put('categories',key,{'id':key,'name':body.name.strip(),'description':body.description})

def start_batch(raw,filename,reference,element_type,category_id,source_uri='',catalog_id='',collection_state='unknown',schema_text='',required_fields='',origin='upload'):
    categories();category=found('categories',category_id)
    if not reference.strip():raise HTTPException(422,'A reference name is required')
    if element_type not in ('json','geojson','climate','foncier','image'):raise HTTPException(422,'Choose a supported box type')
    if collection_state not in ('unknown','partial','complete'):raise HTTPException(422,'Unknown collection state')
    if catalog_id and not db.get('catalog',catalog_id):raise HTTPException(422,'Unknown catalogue reference')
    try:schema=json.loads(schema_text) if schema_text.strip() else None
    except ValueError:raise HTTPException(422,'Expected schema is not valid JSON')
    if len(workflow.ACTIVE)>=4:raise HTTPException(429,'Maximum four concurrent jobs')
    if len(raw)>25*1024*1024:raise HTTPException(413,'Maximum upload is 25 MiB')
    key=uuid.uuid4().hex;directory=db.DATA/'uploads';directory.mkdir(exist_ok=True);(directory/(key+'.bin')).write_bytes(raw)
    b={'id':key,'reference':reference.strip()[:200],'filename':filename.split('/')[-1].split('\\')[-1][:200] or 'upload','element_type':element_type,'category_id':category_id,'category_name':category['name'],'catalog_id':catalog_id or None,'source_uri':source_uri[:1000],'origin':origin,'collection_state':collection_state,'expected_schema':schema,'required_fields':[v.strip() for v in required_fields.split(',') if v.strip()],'state':'queued','stored_file':key+'.bin','sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw),'created_at':now(),'accepted_count':0,'rejected_count':0}
    db.put('batches',key,b);db.event(key,'intake',f"{origin} received: {b['reference']} · {b['filename']} · {len(raw)} bytes · sha256 {b['sha256'][:16]}")
    # Species detection only makes sense on a photo: other references go straight from type check to validation.
    order=['reference','type_check']+(['detection'] if element_type=='image' else [])+['validation','routing']
    job=workflow.create({'batch_id':key},order=order)
    # Merge to avoid overwriting a state already advanced by a worker.
    latest=found('batches',key);latest['job_id']=job;db.put('batches',key,latest)
    return {'batch_id':key,'job_id':job}

@router.post('/uploads',status_code=202)
async def upload(file:UploadFile=File(...),reference:str=Form(...),element_type:str=Form(...),category_id:str=Form(...),source_uri:str=Form(''),catalog_id:str=Form(''),collection_state:str=Form('unknown'),schema_text:str=Form(''),required_fields:str=Form('')):
    raw=await file.read(25*1024*1024+1)
    return start_batch(raw,file.filename or 'upload',reference,element_type,category_id,source_uri,catalog_id,collection_state,schema_text,required_fields,'upload')

class FetchInput(BaseModel):
    url:str=Field(min_length=8,max_length=4000)
    reference:str=Field(min_length=1,max_length=200)
    element_type:Literal['json','geojson','climate','foncier','image']='geojson'
    category_id:str
    type_name:str=Field(default='',max_length=300)
    catalog_id:str=''
    collection_state:Literal['unknown','partial','complete']='unknown'
    schema_text:str=''
    required_fields:str=''
    api_key:str=Field(default='',max_length=2000,repr=False)          # used for this request only, never stored
    api_key_header:str=Field(default='Authorization',pattern=r'^[A-Za-z0-9-]{1,60}$')

@router.post('/fetch',status_code=202)
def fetch_url(body:FetchInput):
    """Secure download of a public link / API, then the same validation pipeline as an uploaded file.
    Rules (pipeline/ingest/api.py public_url): HTTPS only, no credentials or secrets in the URL, public
    addresses only (re-checked on every redirect), 25 MB cap, timeouts. WFS services are converted to
    GeoJSON (first 10 000 features; the collection state becomes partial when the total is larger)."""
    from urllib.parse import urlparse,urljoin
    import httpx
    from pipeline.ingest.api import public_url,fetch as ingest_fetch,FetchData
    state=body.collection_state
    if body.api_key_header.lower() in ('host','cookie','content-length','transfer-encoding','connection','proxy-authorization'):
        raise HTTPException(422,'This header cannot carry an API key')
    headers={'User-Agent':'Renatura data workbench/2.0'}
    if body.api_key:headers[body.api_key_header]=body.api_key
    try:
        public_url(body.url)
        is_wfs='service=wfs' in body.url.lower()
        if body.element_type in ('geojson','foncier') and (is_wfs or body.type_name) and not body.api_key:
            r=ingest_fetch(FetchData(url=body.url,type_name=body.type_name))  # WFS / GML -> GeoJSON, completeness check
            raw=json.dumps(r['data'],ensure_ascii=False).encode();state='complete' if r['status']=='COMPLETE' and state!='partial' else 'partial'
        else:
            url=body.url;raw=None;origin_host=urlparse(url).hostname
            with httpx.Client(timeout=60,follow_redirects=False) as client:
                for _ in range(4):
                    public_url(url)
                    # never forward the API key to another host after a redirect
                    send={k:v for k,v in headers.items() if k=="User-Agent" or urlparse(url).hostname==origin_host}
                    with client.stream('GET',url,headers=send) as resp:
                        if resp.is_redirect:url=urljoin(url,resp.headers['location']);continue
                        if resp.status_code in (401,403):raise ValueError(f'Access refused by the API (HTTP {resp.status_code}): check the API key and its header')
                        resp.raise_for_status();parts=[];size=0
                        for chunk in resp.iter_bytes():
                            size+=len(chunk)
                            if size>25*1024*1024:raise ValueError('Response larger than 25 MB: use a paginated extraction')
                            parts.append(chunk)
                        raw=b''.join(parts);break
                else:raise ValueError('Too many redirects')
    except HTTPException as e:raise HTTPException(422,f'Fetch refused: {e.detail}')
    except Exception as e:
        msg=str(e)[:500]
        if body.api_key:msg=msg.replace(body.api_key,'***')  # the key never appears in an error or log
        raise HTTPException(422,f'Fetch refused: {msg}')
    name=urlparse(body.url).path.rsplit('/',1)[-1] or urlparse(body.url).hostname or 'remote'
    out=start_batch(raw,name,body.reference,body.element_type,body.category_id,body.url,body.catalog_id,state,body.schema_text,body.required_fields,'api (clé fournie, non stockée)' if body.api_key else 'url')
    if body.api_key:
        b=found('batches',out['batch_id']);b['auth']=f'clé API fournie dans l’en-tête {body.api_key_header} ; non stockée';db.put('batches',b['id'],b)
    return out

@router.get('/uploads/{key}')
def get_upload(key:str):return found('batches',key)
@router.post('/uploads/{key}/populate',status_code=202)
def populate(key:str):
    b=found('batches',key)
    if b['state'] not in ('ready','partial_ready'):raise HTTPException(409,'Upload is not ready to populate')
    if any(j['payload'].get('batch_id')==key and j['state'] in ('queued','running') for j in db.all_docs('jobs')):raise HTTPException(409,'This reference already has a running job')
    if len(workflow.ACTIVE)>=4:raise HTTPException(429,'Maximum four concurrent jobs')
    return {'job_id':workflow.create({'batch_id':key},order=['populate','datastore'])}
@router.get('/datasets/{key}/records')
def records(key:str,offset:int=0,limit:int=50):
    d=found('datasets',key);rows=d['data']['features'] if d['kind']=='geojson' else d.get('data',[])
    offset=max(0,offset);limit=max(1,min(100,limit))
    return {'revision':d['revision'],'total':len(rows),'rows':[{'index':i,'value':rows[i]} for i in range(offset,min(len(rows),offset+limit))]}
class RemoveRecords(BaseModel):
    expected_revision:str
    indices:list[int]=Field(min_length=1,max_length=1000)
@router.post('/datasets/{key}/remove-records')
def remove_records(key:str,body:RemoveRecords):
    with db.LOCK:
        d=found('datasets',key)
        if d['revision']!=body.expected_revision:raise HTTPException(409,'Dataset changed. Reopen it before removing records.')
        rows=d['data']['features'] if d['kind']=='geojson' else d.get('data',[]);indices=set(body.indices)
        if any(i<0 or i>=len(rows) for i in indices):raise HTTPException(422,'Invalid record index')
        before=json.loads(json.dumps(d));remaining=[r for i,r in enumerate(rows) if i not in indices]
        new_data={'type':'FeatureCollection','features':remaining} if d['kind']=='geojson' else remaining
        v=validate(new_data,d['schema']);d.update(data=new_data,valid_count=len(remaining),profile=v['profile'],revision=uuid.uuid4().hex)
        trash_id=uuid.uuid4().hex
        db.put('dataset_revisions',before['revision'],before);db.put('trash',trash_id,{'id':trash_id,'kind':'records','label':f'{len(indices)} records from '+d['name'],'deleted_at':now(),'dataset':before,'after_revision':d['revision']})
        db.put('datasets',key,d);db.event('workspace','datastore',f'{len(indices)} elements removed from {d["name"]}; recoverable in Trash')
        publish(d)
    return {'removed':len(indices),'trash_id':trash_id,'calculation':refresh_calculation()}
@router.delete('/datasets/{key}')
def remove_dataset(key:str):
    with db.LOCK:
        d=found('datasets',key);trash_id=uuid.uuid4().hex
        db.put('trash',trash_id,{'id':trash_id,'kind':'dataset','label':d['name'],'dataset':d,'deleted_at':now()});db.remove('datasets',key)
        if d.get('batch_id'):
            b=db.get('batches',d['batch_id'])
            if b:b['state']='removed';db.put('batches',b['id'],b)
        db.event('workspace','datastore','Dataset moved to Trash: '+d['name'])
        unpublish(key)
    return {'trash_id':trash_id,'calculation':refresh_calculation()}
@router.post('/trash/{key}/restore')
def restore(key:str):
    with db.LOCK:
        t=found('trash',key);d=t['dataset'];current=db.get('datasets',d['id'])
        if t['kind']=='dataset' and current:raise HTTPException(409,'A dataset with this ID already exists')
        if t['kind']=='records' and (not current or current['revision']!=t['after_revision']):raise HTTPException(409,'Dataset has changed since removal. Restore is blocked to protect newer data.')
        d['revision']=uuid.uuid4().hex;db.put('datasets',d['id'],d)
        if d.get('batch_id'):
            b=db.get('batches',d['batch_id'])
            if b:b['state']='populated';db.put('batches',b['id'],b)
        db.remove('trash',key);db.event('workspace','datastore','Restored: '+t['label'])
        publish(d)
    return {'restored':d['id'],'calculation':refresh_calculation()}

class TargetInput(BaseModel):
    category_id:str
@router.patch('/uploads/{key}/target')
def update_target(key:str,body:TargetInput):
    b=found('batches',key);c=found('categories',body.category_id)
    if b['state'] not in ('ready','partial_ready'):raise HTTPException(409,'Target can only change before population, after validation')
    b['category_id']=c['id'];b['category_name']=c['name'];db.put('batches',key,b);return compact(b)
