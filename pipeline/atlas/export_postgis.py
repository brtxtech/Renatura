#!/usr/bin/env python3
"""Optional import of the verified spatial index into a user-owned PostGIS database."""
import argparse,json,os,sqlite3

def main():
 p=argparse.ArgumentParser();p.add_argument('--database',required=True,help='normandie.sqlite');args=p.parse_args()
 import psycopg
 url=os.environ.get('DATABASE_URL')
 if not url:raise SystemExit('Définir DATABASE_URL pour votre instance PostGIS.')
 with sqlite3.connect('file:'+args.database+'?mode=ro',uri=True) as source,psycopg.connect(url) as target:
  target.execute('CREATE EXTENSION IF NOT EXISTS postgis')
  target.execute('CREATE TABLE IF NOT EXISTS renatura_layers (id text PRIMARY KEY, metadata jsonb NOT NULL)')
  target.execute('CREATE TABLE IF NOT EXISTS renatura_features (id bigint PRIMARY KEY, layer_id text REFERENCES renatura_layers(id), source_id text, properties jsonb NOT NULL, geom geometry(Geometry,2154) NOT NULL)')
  for lid,meta in source.execute('SELECT id,meta FROM layers'):target.execute('INSERT INTO renatura_layers VALUES(%s,%s::jsonb) ON CONFLICT(id) DO UPDATE SET metadata=excluded.metadata',(lid,meta))
  count=0
  for fid,lid,sid,blob,props in source.execute('SELECT fid,layer_id,source_id,geom,props FROM features'):
   target.execute('INSERT INTO renatura_features VALUES(%s,%s,%s,%s::jsonb,ST_GeomFromWKB(%s,2154)) ON CONFLICT(id) DO UPDATE SET properties=excluded.properties,geom=excluded.geom,layer_id=excluded.layer_id,source_id=excluded.source_id',(fid,lid,sid,props,bytes(blob)));count+=1
  target.execute('CREATE INDEX IF NOT EXISTS renatura_features_geom_idx ON renatura_features USING gist(geom)')
  observed=target.execute('SELECT count(*) FROM renatura_features').fetchone()[0]
  if observed!=count:raise RuntimeError('Écart de compte ; utiliser une base dédiée ou examiner des versions précédentes.')
  print('Import PostGIS validé :',observed,'objets')
if __name__=='__main__':main()
