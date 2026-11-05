#!/usr/bin/env python3
"""Audit the delivered atlas, its source inventory and spatial index."""
import argparse,collections,gzip,json,sqlite3
from pathlib import Path
P=Path(__file__).resolve().parents[2]/'dist/data/atlas'
def run(database):
 c=json.load(open(P/'catalog.json'));inventory=json.load(open(P/'inventory.json'))
 assert len(inventory)==c['statistics']['inventory_entries']==1016
 assert len(c['files'])==41 and all(f['available'] for f in c['files'])
 assert sum(l['kind']!='FILE' for l in c['layers'])==221
 assert len({l['id'] for l in c['layers']})==len(c['layers'])
 total=0;types=collections.Counter()
 for l in c['layers']:
  n=0
  for path in l['chunks']:
   p=P/path;fc=json.load(gzip.open(p,'rt') if p.suffix=='.gz' else p.open());n+=len(fc['features'])
   for f in fc['features']:
    assert f['properties']['_layer']==l['id'];types[f['geometry']['type']]+=1
   if path in l.get('chunk_bounds',{}):
    a,b,d,e=l['chunk_bounds'][path];assert -2.1<a<=d<2 and 48<b<=e<50.2,(path,[a,b,d,e])
  assert n==l['map_count'],(l['name'],n,l['map_count']);total+=n
 assert total==c['statistics']['mapped_features']
 if database:
  with sqlite3.connect('file:'+str(Path(database).resolve())+'?mode=ro',uri=True) as db:
   counts=dict(db.execute('SELECT layer_id,count(*) FROM features GROUP BY layer_id'))
   assert db.execute('SELECT count(*) FROM bounds').fetchone()[0]==total
   assert sum(counts.values())==total
   for l in c['layers']:assert counts.get(l['id'],0)==l['map_count']
 z=json.load(open(P/'zones.geojson'));valid={l['id'] for l in c['layers']}
 for f in z['features']:
  r=json.load(open(P/'zones'/str(f['properties']['id']+'.json')))
  assert all(x['id'] in valid and x['count']>0 for x in r['layers'])
 result={'checks':'PASS','statistics':c['statistics'],'grid_zones':len(z['features']),'geometry_types':dict(types),'api_statuses':dict(collections.Counter(l['status'] for l in c['layers'] if l['kind']!='FILE')),'conversion_states':dict(collections.Counter(l['map_state'] for l in c['layers']))}
 (P/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--database');run(p.parse_args().database)
