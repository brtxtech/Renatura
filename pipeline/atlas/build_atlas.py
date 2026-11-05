#!/usr/bin/env python3
"""Reproject real source features, clip to Normandy, index exact geometries and write lazy display chunks."""
import argparse,collections,csv,gzip,hashlib,json,logging,math,sqlite3,sys,time,zipfile
from pathlib import Path
import fiona
from gml_geometry import read_wrapper
import shapely
from shapely.geometry import shape,mapping,box
from shapely.ops import transform
from pyproj import CRS,Transformer
logging.getLogger('fiona').setLevel(logging.ERROR)
import warnings
warnings.filterwarnings("ignore",category=DeprecationWarning)
SITE=Path(__file__).resolve().parents[2]
def dump(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,ensure_ascii=False,separators=(',',':'),default=str))
def ident(s):return hashlib.sha256(s.encode()).hexdigest()[:18]
def jsgeom(g):
 d=mapping(g)
 def rounded(x):return round(x,6) if isinstance(x,float) else [rounded(v) for v in x] if isinstance(x,(tuple,list)) else x
 return {'type':d['type'],'geometries':[jsgeom(x) for x in g.geoms]} if d['type']=='GeometryCollection' else {'type':d['type'],'coordinates':rounded(d['coordinates'])}
def islocal(r):return r.get('kind')=='FILE'
def init_db(path):
 c=sqlite3.connect(path);c.executescript('PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS layers(id TEXT PRIMARY KEY,meta TEXT); CREATE TABLE IF NOT EXISTS features(fid INTEGER PRIMARY KEY,layer_id TEXT,source_id TEXT,geom BLOB,props TEXT); CREATE VIRTUAL TABLE IF NOT EXISTS bounds USING rtree(fid,minx,maxx,miny,maxy); CREATE INDEX IF NOT EXISTS layer_idx ON features(layer_id);');return c

def build(args):
 out=SITE/'dist/data/atlas';out.mkdir(parents=True,exist_ok=True);cache=Path(args.cache);cache.mkdir(parents=True,exist_ok=True)
 normfc=json.loads(Path(args.boundary).read_text());region=shape(normfc['features'][0]['geometry']);forward=Transformer.from_crs(4326,2154,always_xy=True).transform;back=Transformer.from_crs(2154,4326,always_xy=True).transform;region=shapely.make_valid(transform(forward,region));shapely.prepare(region)
 dump(out/'normandie.geojson',normfc);dump(out/'boundary_provenance.json',json.loads(Path(args.boundary).with_name('boundary_provenance.json').read_text()))
 source=Path(args.source);reports=json.loads((source/'api_collection_manifest.json').read_text());graph=json.loads((source/'graph.json').read_text());categories=[{'id':n['id'].rsplit(':',1)[-1],'name':n['properties']['nom'],'color':n['properties']['couleur']} for n in graph['nodes'] if n['label']=='Categorie'];catmap={c['name']:c['id'] for c in categories}
 # Add every existing file-layer reference, including non-spatial/unavailable sources as catalogue entries.
 rows=list(csv.DictReader((source/'source/api_history.csv').open(encoding='utf-8-sig')));entrycats=collections.defaultdict(set)
 for rel in graph['relationships']:
  if rel['type']=='APPARTIENT_A' and ':entree:' in rel['source']:entrycats[rel['source'].rsplit(':',1)[-1]].add(rel['target'].rsplit(':',1)[-1])
 manifest=json.loads((source/'source/package_metadata/file_manifest.json').read_text());fileby={x['relative_file']:x for x in manifest};groups={}
 for r in rows:
  if not r['endpoint_type'].startswith('LOCAL_') or not r.get('relative_file'):continue
  if r['endpoint_type'] in {'LOCAL_7Z'}:continue
  k=(r['relative_file'],r.get('layer',''))
  if k not in groups:groups[k]=dict(r,entry_ids=[],category_ids=set())
  groups[k]['entry_ids'].append(r['endpoint_id']);groups[k]['category_ids'].update(entrycats[r['endpoint_id']])
 for (path,layer),r in groups.items():
  f=fileby.get(path,{})
  reports.append(dict(id='file_'+ident(path+'|'+layer),name=r['name'],kind='FILE',path=path,layer=layer,entry_ids=r['entry_ids'],categories=[c['name'] for c in categories if c['id'] in r['category_ids']],status='FILE_VERIFIED',complete=True,records=int(r.get('records_returned') or 0),pages=[],collected_at=r.get('checked_at_utc'),url=r.get('reference') or f.get('reference',''),license=r.get('license') or f.get('license',''),sha256=r.get('sha256') or f.get('sha256',''),use_cases=[r.get('use_case_fr','')],snapshot_node_id='',crs_hint=r.get('crs_authority') or r.get('crs') or ''))
 db=init_db(cache/'normandie.sqlite');full_meta=[];start=time.time();transformers={}
 for n,r in enumerate(reports):
  lid=r['id'];receipt=cache/(lid+'.json')
  if receipt.exists():
   previous=json.loads(receipt.read_text())
   if '0' not in previous.get('errors',[]) and previous.get('map_state')!='READ_ERROR':
    previous['chunks']=[name+'.gz' if not (out/name).exists() and (out/(name+'.gz')).exists() else name for name in previous['chunks']]
    full_meta.append(previous);continue
  m={k:r.get(k) for k in ['id','name','kind','entry_ids','categories','status','complete','records','collected_at','url','license','use_cases','reason','sha256','path']};m.update(category_ids=[catmap[x] for x in r.get('categories',[]) if x in catmap],map_count=0,read_count=0,no_geometry=0,invalid_count=0,repaired_count=0,outside_count=0,crs_issues=0,duplicates=0,chunks=[],crs_observed=[],errors=[],display_simplification_m=30,analysis_crs='EPSG:2154',geometry_scope='Intersection avec le contour régional Etalab généralisé à 5 mètres',origin='Fichier fourni' if islocal(r) else 'API collectée')
  for old_chunk in (out/lid).glob('*.geojson*'):old_chunk.unlink()
  db.execute('DELETE FROM bounds WHERE fid IN (SELECT fid FROM features WHERE layer_id=?)',(lid,));db.execute('DELETE FROM features WHERE layer_id=?',(lid,))
  display=[];display_bytes=0;chunk=0;seen=set();counter=0
  def flush():
   nonlocal display,display_bytes,chunk
   if not display:return
   name=f'{lid}/{chunk:04d}.geojson';dump(out/name,{'type':'FeatureCollection','features':display});m['chunks'].append(name);chunk+=1;display=[];display_bytes=0
  def emit(raw,props,crs,source_id=None):
   nonlocal counter,display_bytes,display
   counter+=1;m['read_count']+=1
   if raw is None:m['no_geometry']+=1;return
   try:
    g=shape(raw)
    if g.is_empty:m['no_geometry']+=1;return
    if not crs:m['crs_issues']+=1;return
    key=str(crs)
    if key not in transformers:
     original=CRS.from_user_input(crs);transformers[key]=(original.to_string(),None if original.to_epsg()==2154 else Transformer.from_crs(original,2154,always_xy=True).transform)
    authority,trans=transformers[key]
    if authority not in m['crs_observed']:m['crs_observed'].append(authority)
    if trans:g=transform(trans,g)
    if not all(math.isfinite(v) for v in g.bounds):m['invalid_count']+=1;return
    if not region.intersects(g):m['outside_count']+=1;return
    if not g.is_valid:g=shapely.make_valid(g);m['repaired_count']+=1
    if g.is_empty:m['invalid_count']+=1;return
    if not region.covers(g):g=g.intersection(region)
    if g.is_empty:m['outside_count']+=1;return
    if g.geom_type=='GeometryCollection':
     parts=[v for v in g.geoms if not v.is_empty]
     if not parts:m['invalid_count']+=1;return
     g=shapely.union_all(parts)
    props={str(k):v for k,v in dict(props).items()};digest=hashlib.sha256(g.wkb+json.dumps(props,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
    if digest in seen:m['duplicates']+=1;return
    seen.add(digest)
    oid=lid+':'+str(counter);neo=r.get('snapshot_node_id','')+':record:'+str(counter) if not islocal(r) else ''
    p={**props,'_id':oid,'_layer':lid,'_origin':m['origin'],'_collection_status':r['status'],'_source_id':str(source_id or counter),'_neo4j_id':neo}
    cur=db.execute('INSERT INTO features(layer_id,source_id,geom,props) VALUES(?,?,?,?)',(lid,str(source_id or counter),sqlite3.Binary(g.wkb),json.dumps(p,ensure_ascii=False,default=str)));a,b,c,d=g.bounds;db.execute('INSERT INTO bounds VALUES(?,?,?,?,?)',(cur.lastrowid,a,c,b,d))
    simple=g.simplify(30,preserve_topology=True);simple=transform(back,simple)
    f={'type':'Feature','id':oid,'geometry':jsgeom(simple),'properties':p};size=len(json.dumps(f,ensure_ascii=False,default=str))
    if display and (display_bytes+size>1_500_000 or len(display)>=1200):flush()
    display.append(f);display_bytes+=size;m['map_count']+=1
   except Exception as e:
    m['invalid_count']+=1
    if len(m['errors'])<3:m['errors'].append(type(e).__name__+': '+str(e)[:220])
  def read_vector(path,layer=None):
   kw={'allow_unsupported_drivers':True}
   if layer:kw['layer']=layer
   with fiona.Env(GML_DOWNLOAD_SCHEMA='NO',GML_SKIP_RESOLVE_ELEMS='ALL'):
    with fiona.open(path,**kw) as src:
     if src.schema['geometry'] in (None,'None'):
      m['map_state']='NON_SPATIAL_OR_ARCHIVE';m['no_geometry']+=len(src);return
     crs=src.crs_wkt or src.crs
     if not crs:
      m['crs_issues']+=len(src);return
     features=src
     if islocal(r):
      extent=Transformer.from_crs(2154,crs,always_xy=True).transform_bounds(*region.bounds,densify_pts=21);features=src.filter(bbox=extent)
     for f in features:emit(f.geometry,dict(f.properties),crs,dict(f.properties).get('gml_id') or f.id)
  try:
   if islocal(r):
    p=Path(args.files_root)/r['path'] if args.files_root else Path('/__unavailable__')
    if not p.exists():m['map_state']='MISSING_LOCAL_FILE'
    elif p.suffix.lower() in {'.gpkg','.shp','.geojson'}:read_vector(str(p),r['layer'] if p.suffix=='.gpkg' else None)
    elif p.suffix.lower()=='.zip' and not r.get('layer') and any(path==r['path'] and layer for path,layer in groups):m['map_state']='NON_SPATIAL_OR_ARCHIVE'
    elif p.suffix.lower()=='.zip':
     with zipfile.ZipFile(p) as z:
      candidates=[x for x in z.namelist() if x.lower().endswith(('.shp','.gpkg','.geojson')) and not any(part.startswith('.') or part=='__MACOSX' for part in x.split('/'))]
     if r.get('layer'):candidates=[item for item in candidates if item==r['layer']]
     for item in candidates:read_vector('/vsizip/'+str(p.resolve())+'/'+item)
    elif p.suffix.lower() in {'.tif','.tiff'}:m['map_state']='RASTER_REFERENCE'
    else:m['map_state']='NON_SPATIAL_OR_ARCHIVE'
   elif r['kind']=='WFS':
    m['geometry_reader']='GML linéaire 2/3, ordre des axes selon srsName'
    page_crs={}
    for number,pg in enumerate(r['pages'],1):
     if pg['file'].endswith('.json.gz'):
      body=json.loads(gzip.open(source/'api_data'/lid/pg['file'],'rb').read());declared=body.get('crs',{}) if isinstance(body,dict) else {};page_crs[number]=declared.get('properties',{}).get('name','EPSG:4326')
    path=source/r.get('record_file',f'api_data/{lid}/records.jsonl')
    if path.exists():
     with path.open() as f:
      for line in f:
       rec=json.loads(line);wrappers=rec.get('geometry')
       if not wrappers:emit(None,rec.get('attributes',{}),None,rec.get('source_id'));continue
       try:
        if isinstance(wrappers,dict):geom,crs=wrappers,page_crs.get(rec['page'],'EPSG:4326')
        else:geom,crs=read_wrapper(wrappers[0])
        emit(geom,rec.get('attributes',{}),crs,rec.get('source_id'))
       except Exception as e:
        counter+=1;m['read_count']+=1;m['invalid_count']+=1
        if len(m['errors'])<3:m['errors'].append(str(e)[:220])
   else:
    path=source/r.get('record_file',f'api_data/{lid}/records.jsonl')
    if path.exists():
     with path.open() as f:
      for line in f:
       rec=json.loads(line);geom=rec.get('geometry');attrs=rec.get('attributes',{});crs=None
       if isinstance(geom,dict):
        geom=geom.get('geometry',geom)
        if geom.get('type') and 'coordinates' in geom:crs='EPSG:4326'
        else:geom=None
       if geom is None:
        for x,y in [('lng','lat'),('longitude','latitude'),('lon','lat')]:
         if attrs.get(x) is not None and attrs.get(y) is not None:
          try:
           lon,lat=float(attrs[x]),float(attrs[y])
           if -180<=lon<=180 and -90<=lat<=90:geom={'type':'Point','coordinates':[lon,lat]};crs='EPSG:4326'
          except (TypeError,ValueError):pass
          break
       emit(geom,attrs,crs,rec.get('source_id'))
  except Exception as e:m['errors'].append(type(e).__name__+': '+str(e)[:300]);m['map_state']='READ_ERROR'
  flush();m.setdefault('map_state','READY' if m['map_count'] else 'GEOMETRY_REVIEW' if m['invalid_count'] or m['crs_issues'] else 'NO_NORMANDY_GEOMETRY');db.execute('INSERT OR REPLACE INTO layers VALUES(?,?)',(lid,json.dumps(m,ensure_ascii=False)));db.commit();dump(receipt,m);full_meta.append(m)
  print(f'{n+1}/{len(reports)} {m["map_state"]} {m["map_count"]} {r["name"][:65]}',flush=True)
 # Retain the full categorized catalogue, including WMS/WMTS and nonspatial references.
 inventory=[dict(r,category_ids=sorted(entrycats[r['endpoint_id']])) for r in rows]
 dump(out/'inventory.json',inventory)
 # Every original file remains explicitly represented, including containers and nonspatial originals.
 file_inventory=[dict(f,available=bool(args.files_root and (Path(args.files_root)/f['relative_file']).exists())) for f in manifest]
 catalog={'version':'2026-11-05','categories':categories,'layers':full_meta,'files':file_inventory,'statistics':{'inventory_entries':len(rows),'api_sources':sum(not islocal(r) for r in reports),'original_files':len(manifest),'original_files_available':sum(f['available'] for f in file_inventory),'mapped_features':sum(m['map_count'] for m in full_meta),'mapped_layers':sum(m['map_count']>0 for m in full_meta),'layers':len(full_meta),'display_simplification_m':30},'boundary_source':'boundary_provenance.json','note':'Les extractions partielles ne prouvent jamais une absence. Les couches peuvent se recouvrir; les comptes ne sont pas des objets uniques entre sources.'};dump(out/'catalog.json',catalog)
 print('CATALOG',catalog['statistics'],'seconds',round(time.time()-start),flush=True);db.close()
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--source',required=True);a.add_argument('--files-root');a.add_argument('--boundary',required=True);a.add_argument('--cache',required=True);build(a.parse_args())
