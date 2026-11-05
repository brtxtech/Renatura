#!/usr/bin/env python3
"""Import actual catalogue/feature records into Neo4j. City links use simplified display geometry, explicitly labelled."""
import argparse,datetime,gzip,json,os,sys,collections,hashlib
from pathlib import Path
from neo4j import GraphDatabase
import shapely
from shapely.geometry import shape
ROOT=Path(__file__).resolve().parents[2];DATA=ROOT/'dist/data/atlas'
def catalog_signature():
 h=hashlib.sha256((DATA/'catalog-v2.json').read_bytes());folder=ROOT/'user-data/datasets'
 if folder.exists():
  for p in sorted(folder.glob('*.json')):h.update(p.read_bytes())
 return h.hexdigest()
def driver():
 uri=os.getenv('NEO4J_URI','bolt://127.0.0.1:7687');password=os.getenv('NEO4J_PASSWORD');return GraphDatabase.driver(uri,auth=(os.getenv('NEO4J_USER','neo4j'),password) if password else None)
def jsonfile(p):
 with gzip.open(p,'rt') if str(p).endswith('.gz') else open(p) as f:return json.load(f)
def run(city='Caen',all_cities=False,metadata_only=False):
 tree=jsonfile(DATA/'catalog-v2.json');raw=jsonfile(DATA/'catalog.json');byid={l['id']:l for l in raw['layers']};boundaries=jsonfile(ROOT/'dist/data/graph/communes.geojson.gz')['features'];cities=[c for c in boundaries if all_cities or c['properties']['code']==city or c['properties']['nom'].casefold()==city.casefold()]
 if not cities:raise ValueError('Commune introuvable : '+city)
 selected={};relationships=[];metadata=[]
 for t in tree['themes']:
  for g in t['groups']:
   for l in g['layers']:
    metadata.append({'theme':t['id'],'theme_name':t['display_name'],'group':g['id'],'group_name':g['display_name'],'layer':l['id'],'layer_name':l['display_name']})
    for v in l['variants']:
     selected[v['source_id']]=dict(byid[v['source_id']],logical_id=l['id'],variant_id=v['id'],dimensions=v['dimensions']);relationships.extend({'alternative':id,'preferred':v['source_id']} for id in v['source_ids'] if id!=v['source_id'])
 custom_root=ROOT/'user-data/datasets'
 if custom_root.exists():
  for p in custom_root.glob('*.json'):
   d=jsonfile(p);m=d['metadata'];theme=m.get('theme','biodiversity');gid='user-group:'+m.get('group','Imports');lid='user-layer:'+m['id'];metadata.append({'theme':theme,'theme_name':theme,'group':gid,'group_name':m.get('group','Imports'),'layer':lid,'layer_name':m['display_name']});byid[m['id']]={'id':m['id'],'name':m['display_name'],'status':m.get('status','PARTIAL'),'url':m.get('source',''),'origin':'Import utilisateur','collected_at':m.get('updated'),'map_count':len(d['data']['features'])};selected[m['id']]=dict(byid[m['id']],logical_id=lid,custom_file=str(p))
 dbname=os.getenv('NEO4J_DATABASE','neo4j');db=driver();db.verify_connectivity()
 with db.session(database=dbname) as session:
  for label in ['Theme','Group','Layer','Source','Element','Commune','CatalogueEntry','CatalogueCategory','File']:session.run(f'CREATE CONSTRAINT renatura_{label.lower()} IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE').consume()
  session.run('MATCH(l:Layer:Renatura) SET l.catalog_active=false').consume()
  session.run('UNWIND $rows AS r MERGE(t:Theme {id:r.theme}) SET t.name=r.theme_name MERGE(g:Group {id:r.group}) SET g.name=r.group_name MERGE(l:Layer {id:r.layer}) SET l:Renatura SET l.display_name=r.layer_name,l.catalog_active=true MERGE(l)-[:IN_GROUP]->(g) MERGE(g)-[:IN_THEME]->(t)',rows=metadata).consume()
  sources=[{'id':l['id'],'name':l['name'],'status':l['status'],'url':l.get('url') or '', 'count':l['map_count'],'collected_at':l.get('collected_at') or ''} for l in byid.values()]
  session.run('UNWIND $rows AS r MERGE(s:Source {id:r.id}) SET s+=r',rows=sources).consume()
  session.run('MATCH(s:Source)-[r:VARIANT_OF]->(:Layer) WHERE s.id IN $ids DELETE r',ids=list(selected)).consume()
  session.run('UNWIND $rows AS r MATCH(s:Source {id:r.source}),(l:Layer {id:r.layer}) MERGE(s)-[:VARIANT_OF]->(l)',rows=[{'source':l['id'],'layer':l['logical_id']} for l in selected.values()]).consume()
  session.run('UNWIND $rows AS r MATCH(a:Source {id:r.alternative}),(s:Source {id:r.preferred}) MERGE(a)-[:ALTERNATIVE_TO {basis:"curated catalogue; not individual-object deduplication"}]->(s)',rows=relationships).consume()
  session.run('UNWIND $rows AS r MERGE(c:Commune {id:r.code}) SET c.code=r.code,c.name=r.name',rows=[{'code':c['properties']['code'],'name':c['properties']['nom']} for c in boundaries]).consume()
  entries=jsonfile(DATA/'inventory.json')
  session.run('UNWIND $rows AS r MERGE(e:CatalogueEntry {id:r.id}) SET e.name=r.name,e.url=r.url,e.status=r.status,e.usage=r.usage,e.metadata_json=r.metadata_json',rows=[{'id':r['endpoint_id'],'name':r['name'],'url':r.get('url') or r.get('reference') or '', 'status':r.get('status') or '', 'usage':r.get('use_case_fr') or '', 'metadata_json':json.dumps(r,ensure_ascii=False)} for r in entries]).consume()
  session.run('UNWIND $rows AS r MATCH(s:Source {id:r.source}),(e:CatalogueEntry {id:r.entry}) MERGE(s)-[:DOCUMENTED_BY]->(e)',rows=[{'source':l['id'],'entry':e} for l in byid.values() for e in l.get('entry_ids',[])]).consume()
  session.run('UNWIND $rows AS r MERGE(c:CatalogueCategory {id:r.id}) SET c.name=r.name',rows=raw['categories']).consume()
  session.run('UNWIND $rows AS r MATCH(e:CatalogueEntry {id:r.entry}),(c:CatalogueCategory {id:r.category}) MERGE(e)-[:CLASSIFIED_AS]->(c)',rows=[{'entry':e['endpoint_id'],'category':c} for e in entries for c in e.get('category_ids',[])]).consume()
  session.run('UNWIND $rows AS r MERGE(f:File {id:r.id}) SET f.name=r.name,f.sha256=r.sha256,f.metadata_json=r.metadata_json',rows=[{'id':f['relative_file'],'name':f['filename'],'sha256':f.get('sha256') or '', 'metadata_json':json.dumps(f,ensure_ascii=False)} for f in raw['files']]).consume()
  session.run('UNWIND $rows AS r MATCH(e:CatalogueEntry {id:r.entry}),(f:File {id:r.file}) MERGE(e)-[:REFERENCES_FILE]->(f)',rows=[{'entry':e['endpoint_id'],'file':e['relative_file']} for e in entries if e.get('relative_file')]).consume()
  if metadata_only:print('Metadata imported into real Neo4j',flush=True);db.close();return
  geoms=[shapely.make_valid(shape(c['geometry'])) for c in cities];index=shapely.STRtree(geoms);extent=shapely.union_all(geoms).bounds;counts=collections.Counter();batch=[];scanned=0
  def flush():
   if not batch:return
   session.run('UNWIND $rows AS r MERGE(e:Element {id:r.id}) SET e.name=r.name,e.properties_json=r.properties_json,e.geometry_json=r.geometry_json,e.collection_status=r.status MERGE(s:Source {id:r.source}) MERGE(e)-[:FROM_SOURCE]->(s) WITH e,r UNWIND r.cities AS city MATCH(c:Commune {id:city}) MERGE(e)-[link:INTERSECTS_DISPLAY]->(c) SET link.method="Intersection of display geometries (30m simplification) with API Geo commune contours",link.not_regulatory=true',rows=batch).consume();batch.clear()
  for n,l in enumerate(selected.values(),1):
   chunks=[None] if l.get('custom_file') else l.get('chunks',[])
   for chunk in chunks:
    box=l.get('chunk_bounds',{}).get(chunk)
    if box and (box[0]>extent[2] or box[2]<extent[0] or box[1]>extent[3] or box[3]<extent[1]):continue
    fc=jsonfile(l['custom_file'])['data'] if chunk is None else jsonfile(DATA/chunk)
    for i,f in enumerate(fc['features']):
     scanned+=1
     if not f.get('geometry'):continue
     try:g=shape(f['geometry']);matches=index.query(g,predicate='intersects')
     except Exception:continue
     if not len(matches):continue
     props=f.get('properties') or {};oid=str(props.get('_id') or f.get('id') or l['id']+':'+str(i));name=next((str(v) for k,v in props.items() if k.lower() in ['name','nom','libelle','nom_site'] and v),l['name']);linked=[cities[int(j)]['properties']['code'] for j in matches]
     batch.append({'id':oid,'name':name[:500],'properties_json':json.dumps(props,ensure_ascii=False,default=str),'geometry_json':json.dumps(f['geometry'],separators=(',',':')),'status':l['status'],'source':l['id'],'cities':linked});counts.update(linked)
     if len(batch)>=500:flush()
   if n%20==0:print('Sources',n,'/',len(selected),'linked records',sum(counts.values()),flush=True)
  flush();now=datetime.datetime.now(datetime.timezone.utc).isoformat()
  session.run('UNWIND $rows AS r MATCH(c:Commune {id:r.code}) SET c.features_imported=true,c.catalog_version=$signature,c.imported_at=$at,c.scope="Preferred catalogue variants; partial sources retain their status",c.method="INTERSECTS_DISPLAY: approximate, display simplification 30m"',rows=[{'code':c['properties']['code']} for c in cities],at=now,signature=catalog_signature()).consume()
  result={'city_counts':dict(counts),'scanned':scanned,'preferred_source_count':len(selected),'imported_at':now,'database':'real Neo4j','relation':'INTERSECTS_DISPLAY','limitation':'Display geometries simplified at 30m; not cadastral/regulatory intersections; incomplete API snapshots remain partial.'};out=ROOT/'user-data';out.mkdir(exist_ok=True);(out/'last-neo4j-import.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False),flush=True)
 db.close()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--city',default='Caen');p.add_argument('--all',action='store_true');p.add_argument('--metadata-only',action='store_true');a=p.parse_args();run(a.city,a.all,a.metadata_only)
