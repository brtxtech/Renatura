"""Local public-API ingestion and durable user dataset registry; credentials are never stored in metadata."""
import datetime,ipaddress,json,re,socket,uuid,xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse,parse_qs,urlencode,urlunparse,urljoin
import httpx
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
from shapely.geometry import shape,mapping
from shapely.ops import transform
from pyproj import Transformer
from pipeline.atlas.gml_geometry import read_wrapper,GEOMETRIES,tag
router=APIRouter(prefix='/api');ROOT=Path(__file__).resolve().parents[2];STORE=ROOT/'user-data/datasets';MAX_BYTES=25_000_000
class FetchData(BaseModel):url:str=Field(max_length=4000);type_name:str=Field(default='',max_length=300)
def public_url(url):
 p=urlparse(url)
 if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):raise ValueError('URL HTTPS publique attendue, sans identifiants.')
 if any(re.search(r'(?i)(key|token|password|secret|signature)',k) for k in parse_qs(p.query)):raise ValueError('Ne pas placer de secret dans une URL enregistrée au catalogue.')
 for info in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM):
  if not ipaddress.ip_address(info[4][0]).is_global:raise ValueError('Les adresses privées et locales sont interdites pour les API distantes.')
 return url
@router.post('/ingest/fetch')
def fetch(data:FetchData):
 try:
  url=public_url(data.url);p=urlparse(url);q=parse_qs(p.query);is_wfs=any(k.lower()=='service' and str(v[0]).upper()=='WFS' for k,v in q.items())
  if is_wfs:
   q={k:v[0] for k,v in q.items() if k.upper() not in {'SERVICE','REQUEST','VERSION','COUNT','MAXFEATURES','OUTPUTFORMAT','SRSNAME','TYPENAME','TYPENAMES','STARTINDEX'}}
   if not data.type_name:raise ValueError('Renseigner le nom de couche WFS (TYPENAMES).')
   q.update(SERVICE='WFS',REQUEST='GetFeature',VERSION='2.0.0',COUNT='10000',TYPENAMES=data.type_name,SRSNAME='EPSG:4326',OUTPUTFORMAT='application/json');url=urlunparse(p._replace(query=urlencode(q)))
  with httpx.Client(timeout=60,follow_redirects=False) as client:
   for _ in range(4):
    public_url(url)
    with client.stream('GET',url,headers={'User-Agent':'Renatura public data ingestion/1.0'}) as r:
     if r.is_redirect:url=urljoin(url,r.headers['location']);continue
     if is_wfs and r.status_code>=400 and 'application%2Fjson' in url:
      params=parse_qs(urlparse(url).query);params['OUTPUTFORMAT']=['application/gml+xml; version=3.2'];url=urlunparse(urlparse(url)._replace(query=urlencode({k:v[0] for k,v in params.items()})));continue
     r.raise_for_status();parts=[];size=0
     for chunk in r.iter_bytes():
      size+=len(chunk)
      if size>MAX_BYTES:raise ValueError('Réponse supérieure à 25 Mo. Utiliser une extraction paginée hors navigateur.')
      parts.append(chunk)
     body=b''.join(parts)
     if is_wfs and b'exceptionreport' in body[:3000].lower() and 'application%2Fjson' in url:
      params=parse_qs(urlparse(url).query);params['OUTPUTFORMAT']=['application/gml+xml; version=3.2'];url=urlunparse(urlparse(url)._replace(query=urlencode({k:v[0] for k,v in params.items()})));continue
     break
   else:raise ValueError('Trop de redirections')
  errors=[];matched=None
  if body.lstrip().startswith(b'<'):
   if b'<!DOCTYPE' in body.upper():raise ValueError('DOCTYPE XML non accepté')
   root=ET.fromstring(body);matched=root.attrib.get('numberMatched') or root.attrib.get('numberOfFeatures');features=[]
   for member in root.iter():
    if tag(member) not in {'member','featureMember'} or not list(member):continue
    item=list(member)[0];attrs={};geom=None
    for child in item:
     if any(tag(g) in GEOMETRIES for g in child.iter()):
      try:
       g,crs=read_wrapper({'gml':ET.tostring(child,encoding='unicode'),'srs':root.attrib.get('srsName')});geom=mapping(transform(Transformer.from_crs(crs,4326,always_xy=True).transform,shape(g)))
      except Exception as e:errors.append(str(e)[:150])
     else:attrs[tag(child)]=child.text
    features.append({'type':'Feature','geometry':geom,'properties':attrs})
   if not features:raise ValueError('Pas de features WFS exploitables. Vérifier le type de couche et son format.')
   fc={'type':'FeatureCollection','features':features}
  else:
   d=json.loads(body);fc=d if d.get('type')=='FeatureCollection' else {'type':'FeatureCollection','features':[d]} if d.get('type')=='Feature' else None
   if fc is None:raise ValueError('GeoJSON FeatureCollection attendu pour cette API JSON.')
   matched=d.get('numberMatched',d.get('totalFeatures',d.get('total_count')))
  try:complete=int(matched)==len(fc['features']) and not errors
  except (TypeError,ValueError):complete=False
  return {'data':fc,'source':data.url,'fetched_url':url,'status':'COMPLETE' if complete else 'PARTIAL','received':len(fc['features']),'expected':matched,'errors':errors[:20],'note':'Instantané ; collecte plafonnée à 10 000 objets WFS. Total inconnu = partiel.'}
 except Exception as e:raise HTTPException(422,str(e)[:800])
class SaveDataset(BaseModel):metadata:dict;data:dict
@router.get('/datasets')
def datasets():
 if not STORE.exists():return []
 return [json.loads(p.read_text()) for p in sorted(STORE.glob('*.json'))]
@router.post('/datasets')
def save(d:SaveDataset):
 if len(json.dumps(d.model_dump()))>MAX_BYTES:raise HTTPException(413,'Import limité à 25 Mo')
 if d.data.get('type')!='FeatureCollection':raise HTTPException(422,'FeatureCollection attendu')
 if not d.metadata.get('display_name') or not d.metadata.get('theme') or not d.metadata.get('group'):raise HTTPException(422,'Nom, thème et groupe obligatoires')
 ident='user_'+uuid.uuid4().hex;meta={k:v for k,v in d.metadata.items() if k in ['display_name','theme','group','source','status','updated','license','description','variant_type','variant_value']};meta.update(id=ident,updated=datetime.datetime.now(datetime.timezone.utc).isoformat());features=[]
 for i,f in enumerate(d.data['features']):
  g=f.get('geometry')
  if g:
   try:
    geometry=shape(g);assert geometry.is_valid and not geometry.is_empty
    a,b,c,e=geometry.bounds;assert -180<=a<=c<=180 and -90<=b<=e<=90
   except Exception:raise HTTPException(422,'Géométrie WGS84 invalide : objet '+str(i))
  features.append({'type':'Feature','id':ident+':'+str(i),'geometry':g,'properties':dict(f.get('properties') or {},_id=ident+':'+str(i),_layer=ident)})
 out={'metadata':meta,'data':{'type':'FeatureCollection','features':features}};STORE.mkdir(parents=True,exist_ok=True);(STORE/(ident+'.json')).write_text(json.dumps(out,ensure_ascii=False));return out
