#!/usr/bin/env python3
"""Prepare local orientation overlays from actual Overpass replies and API Géo communes.
Network display simplified by 0.00005 degrees. Not used for ecological analysis.
"""
import argparse,json,gzip,hashlib,datetime
from pathlib import Path
OUT=Path(__file__).resolve().parents[2]/'dist/data/orientation'
def simplify(points,tol=0.00005):
 if len(points)<3:return points
 keep={0,len(points)-1};stack=[(0,len(points)-1)];threshold=tol*tol
 while stack:
  a,b=stack.pop();x,y=points[a];dx=points[b][0]-x;dy=points[b][1]-y;den=dx*dx+dy*dy;best=threshold;chosen=None
  for i in range(a+1,b):
   px,py=points[i];t=max(0,min(1,((px-x)*dx+(py-y)*dy)/den)) if den else 0;d=(px-x-t*dx)**2+(py-y-t*dy)**2
   if d>best:best=d;chosen=i
  if chosen is not None:keep.add(chosen);stack.extend([(a,chosen),(chosen,b)])
 return [points[i] for i in sorted(keep)]
def run(folder):
 OUT.mkdir(parents=True,exist_ok=True);sources=[]
 for kind in ['roads','rail','stops']:
  file=folder/(kind+'.json');raw=json.load(open(file));features=[]
  for element in raw['elements']:
   tags=element.get('tags',{});props={k:v for k,v in tags.items() if k in ['name','ref','highway','railway','public_transport','operator','network','amenity','service','disused']};props.update(osm_id=str(element['type'])+'/'+str(element['id']))
   if element['type']=='node':coords=[round(element['lon'],6),round(element['lat'],6)];geom={'type':'Point','coordinates':coords};bb=[*coords,*coords]
   else:
    coords=simplify([[round(p['lon'],6),round(p['lat'],6)] for p in element.get('geometry',[]) if 'lon' in p and 'lat' in p])
    if len(coords)<2:continue
    geom={'type':'LineString','coordinates':coords};bb=[min(p[0] for p in coords),min(p[1] for p in coords),max(p[0] for p in coords),max(p[1] for p in coords)]
   features.append({'type':'Feature','id':props['osm_id'],'bbox':bb,'properties':props,'geometry':geom})
  fc={'type':'FeatureCollection','features':features}
  with gzip.open(OUT/(kind+'.geojson.gz'),'wt',encoding='utf8',compresslevel=7) as out:json.dump(fc,out,ensure_ascii=False,separators=(',',':'))
  sources.append({'id':kind,'feature_count':len(features),'raw_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'osm_timestamp':raw.get('osm3s',{}).get('timestamp_osm_base'),'url':'https://overpass-api.de/api/interpreter','license':'OpenStreetMap ODbL 1.0','scope':'Bounding box WGS84: west -2.0, south 48.1, east 1.9, north 50.2; includes neighbouring areas','display_simplification_degrees':0.00005});print(kind,len(features),flush=True)
 file=folder/'communes.geojson';raw=json.load(open(file));cities=[]
 for f in raw['features']:
  if f.get('geometry',{}).get('type')!='Point':continue
  p=f['properties'];cities.append({'name':p['nom'],'code':p['code'],'center':f['geometry']['coordinates'],'population':p.get('population',0) or 0})
 (OUT/'cities.json').write_text(json.dumps(cities,ensure_ascii=False,separators=(',',':')));sources.append({'id':'cities','feature_count':len(cities),'raw_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'urls':['https://geo.api.gouv.fr/departements/'+d+'/communes?fields=nom,code,population,centre&format=geojson&geometry=centre' for d in ['14','27','50','61','76']],'license':'Licence Ouverte 2.0','scope':'Communes of Normandy; administrative centres for orientation only'})
 (OUT/'provenance.json').write_text(json.dumps({'collected_on':datetime.datetime.now(datetime.timezone.utc).date().isoformat(),'purpose':'Orientation cartographique; not incorporated into scenario scores or ecological counts','sources':sources},ensure_ascii=False,indent=2));print('cities',len(cities),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('folder',type=Path);run(p.parse_args().folder)
