#!/usr/bin/env python3
"""Exact intersection counts on unsimplified working geometries, before display simplification."""
import argparse,collections,concurrent.futures,functools,json,math,sqlite3,threading,gzip
from pathlib import Path
import shapely
from shapely.geometry import shape,mapping,box
from shapely.ops import transform
from pyproj import Transformer
P=Path(__file__).resolve().parents[2];OUT=P/'dist/data/atlas'
local=threading.local()
def dump(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,separators=(',',':')))
def run(args):
 database=str(Path(args.database).resolve());region=transform(Transformer.from_crs(4326,2154,always_xy=True).transform,shape(json.load(open(OUT/'normandie.geojson'))['features'][0]['geometry']));shapely.prepare(region);back=Transformer.from_crs(2154,4326,always_xy=True).transform
 @functools.lru_cache(maxsize=3000)
 def load(fid,blob):return shapely.from_wkb(blob)
 def analyse(item):
  zid,g=item;path=OUT/'zones'/f'{zid}.json'
  if path.exists():return json.load(open(path))
  if not hasattr(local,'db'):local.db=sqlite3.connect('file:'+database+'?mode=ro',uri=True)
  a,b,c,d=g.bounds;rows=local.db.execute('SELECT f.fid,f.layer_id,f.geom FROM features f JOIN bounds b ON b.fid=f.fid WHERE b.minx<=? AND b.maxx>=? AND b.miny<=? AND b.maxy>=?',(c,a,d,b))
  counts=collections.Counter();shapely.prepare(g)
  for fid,lid,blob in rows:
   if g.intersects(load(fid,blob)):counts[lid]+=1
  result={'zone_id':zid,'crs_work':'EPSG:2154','method':'Intersections géométriques avant simplification d’affichage ; réparations et contour régional décrits dans le catalogue','layers':[{'id':k,'count':v} for k,v in sorted(counts.items())],'note':'Comptes par source, non dédupliqués entre sources ; aucune preuve d’absence ni score de renaturation.'};dump(path,result);return result
 a,b,c,d=region.bounds;features=[];jobs=[]
 for x in range(math.floor(a/5000)*5000,math.ceil(c/5000)*5000,5000):
  for y in range(math.floor(b/5000)*5000,math.ceil(d/5000)*5000,5000):
   square=box(x,y,x+5000,y+5000)
   if not region.intersects(square):continue
   g=square if region.covers(square) else square.intersection(region)
   if g.is_empty or g.area<1:continue
   zid=f'N{x}_{y}';features.append({'type':'Feature','properties':{'id':zid,'area_ha':round(g.area/10000,2),'grid_size_m':5000},'geometry':mapping(transform(back,g))});jobs.append((zid,g))
 dump(OUT/'zones.geojson',{'type':'FeatureCollection','features':features});print('Zones',len(jobs),flush=True)
 with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
  for i,r in enumerate(ex.map(analyse,jobs),1):
   if i%50==0:print('zones complete',i,flush=True)
 catalog=json.load(open(OUT/'catalog.json'))
 zone_features={f['properties']['id']:f for f in features};overviews=collections.defaultdict(list);large={l['id'] for l in catalog['layers'] if l['map_count']>50000}
 for zid,_ in jobs:
  result=json.load(open(OUT/'zones'/f'{zid}.json'))
  for row in result['layers']:
   if row['id'] in large:
    f=zone_features[zid];overviews[row['id']].append({'type':'Feature','geometry':f['geometry'],'properties':{'_layer':row['id'],'_aggregation':True,'_count':row['count'],'_source_id':zid}})
 for l in catalog['layers']:
  if l['id'] not in large:continue
  name='overviews/'+l['id']+'.geojson.gz';path=OUT/name;path.parent.mkdir(exist_ok=True)
  with gzip.open(path,'wt',encoding='utf-8') as out:json.dump({'type':'FeatureCollection','features':overviews[l['id']]},out,ensure_ascii=False,separators=(',',':'))
  l['overview_file']=name
 dump(OUT/'catalog.json',catalog)
 report={'statistics':catalog['statistics'],'analysis_zones':len(jobs),'layers':[{k:l.get(k) for k in ['id','name','origin','status','map_state','map_count','read_count','outside_count','no_geometry','invalid_count','crs_issues','repaired_count','duplicates','errors','crs_observed']} for l in catalog['layers']],'geometry_note':'Les originaux sont conservés dans les archives sources. Les géométries de travail sont reprojetées en Lambert-93, réparées si nécessaire et découpées au contour Etalab 5 m. Simplification 30 m uniquement à l’affichage.','scoring':'Aucun nouveau score écologique ou réglementaire n’est déduit de la présence des couches.'};dump(OUT/'conversion-report.json',report);print('DONE',len(jobs),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--database',required=True);p.add_argument('--workers',type=int,default=3);run(p.parse_args())
