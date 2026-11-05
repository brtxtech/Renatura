#!/usr/bin/env python3
"""Losslessly gzip display chunks and index their geographic bounds for viewport loading."""
from pathlib import Path
import gzip,json
P=Path(__file__).resolve().parents[2]/'dist/data/atlas'
catalog=json.load(open(P/'catalog.json'));total=0
for index,layer in enumerate(catalog['layers'],1):
 bounds={};names=[]
 for name in layer['chunks']:
  src=P/name
  if name.endswith('.gz'):fc=json.load(gzip.open(src,'rt'));dest=src
  else:
   fc=json.load(open(src));dest=Path(str(src)+'.gz')
   with gzip.open(dest,'wt',encoding='utf-8',compresslevel=7) as f:json.dump(fc,f,ensure_ascii=False,separators=(',',':'))
  bb=[180,90,-180,-90]
  def collect(c):
   if c and isinstance(c[0],(float,int)):bb[0]=min(bb[0],c[0]);bb[1]=min(bb[1],c[1]);bb[2]=max(bb[2],c[0]);bb[3]=max(bb[3],c[1])
   else:
    for x in c:collect(x)
  def geom(g):
   if g['type']=='GeometryCollection':
    for x in g['geometries']:geom(x)
   else:collect(g['coordinates'])
  for feature in fc['features']:geom(feature['geometry'])
  total+=len(fc['features']);key=str(dest.relative_to(P));names.append(key);bounds[key]=bb
  if dest!=src:src.unlink()
 layer['chunks']=names;layer['chunk_bounds']=bounds
 if index%25==0:print('Compressed layers',index,flush=True)
assert total==catalog['statistics']['mapped_features'],(total,catalog['statistics']['mapped_features'])
(P/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,separators=(',',':')));print('Display gzip features verified:',total,flush=True)
