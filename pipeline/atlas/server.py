"""Local Renatura map + exact arbitrary GeoJSON intersection API. No external database required."""
import collections,json,os,sqlite3
from pathlib import Path
import shapely
from shapely.geometry import shape
from shapely.ops import transform
from pyproj import Transformer
from fastapi import FastAPI,HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
P=Path(__file__).resolve().parents[2]
app=FastAPI(title='Renatura · API géographique',version='1.0')
class Analysis(BaseModel):
 geometry:dict
 layer_ids:list[str]=Field(default_factory=list,max_length=500)
@app.get('/api/health')
def health():return {'status':'ok','spatial_database_available':Path(os.getenv('RENATURA_SPATIAL_DB',str(P/'atlas-data/normandie.sqlite'))).is_file()}
@app.post('/api/analyse')
def analyse(data:Analysis):
 dbpath=Path(os.getenv('RENATURA_SPATIAL_DB',str(P/'atlas-data/normandie.sqlite')))
 if not dbpath.exists():raise HTTPException(503,'Extraire les données spatiales ou définir RENATURA_SPATIAL_DB.')
 try:g=shape(data.geometry)
 except Exception as e:raise HTTPException(422,'Géométrie GeoJSON invalide') from e
 if g.geom_type not in {'Polygon','MultiPolygon'} or g.is_empty or not g.is_valid:raise HTTPException(422,'Fournir un Polygon ou MultiPolygon valide en longitude–latitude.')
 a,b,c,d=g.bounds
 if not (-180<=a<=c<=180 and -90<=b<=d<=90):raise HTTPException(422,'Coordonnées WGS84 longitude–latitude attendues.')
 g=transform(Transformer.from_crs(4326,2154,always_xy=True).transform,g);shapely.prepare(g);a,b,c,d=g.bounds;counts=collections.Counter()
 with sqlite3.connect('file:'+str(dbpath.resolve())+'?mode=ro',uri=True) as db:
  for lid,blob in db.execute('SELECT f.layer_id,f.geom FROM features f JOIN bounds b ON f.fid=b.fid WHERE b.minx<=? AND b.maxx>=? AND b.miny<=? AND b.maxy>=?',(c,a,d,b)):
   if data.layer_ids and lid not in data.layer_ids:continue
   if g.intersects(shapely.from_wkb(blob)):counts[lid]+=1
  meta={lid:json.loads(s) for lid,s in db.execute('SELECT id,meta FROM layers')}
 return {'method':'Intersections sur géométries de travail Lambert-93, avant simplification d’affichage','layers':[{'id':lid,'name':meta[lid]['name'],'count':v,'collection_status':meta[lid]['status'],'entry_ids':meta[lid]['entry_ids']} for lid,v in sorted(counts.items())],'note':'Les extractions partielles ne prouvent pas une absence. Aucun score automatique n’est calculé.'}
from pipeline.graph.api import router as graph_router
from pipeline.ingest.api import router as ingest_router
app.include_router(graph_router)
app.include_router(ingest_router)
app.mount('/',StaticFiles(directory=P/'dist',html=True),name='atlas')
