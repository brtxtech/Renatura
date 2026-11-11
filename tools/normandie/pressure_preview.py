#!/usr/bin/env python3
"""Carte régionale exploratoire du bâti disponible. Ne remplit JAMAIS le critère P validé."""
import argparse,json,pathlib
import geopandas as gpd
from shapely import make_valid,union_all

def preview(data,candidate):
 config=json.loads(candidate.read_text())['layers'][0];original=json.loads((data/'cells.geojson').read_text());grid=gpd.GeoDataFrame.from_features(original['features'],crs=4326).to_crs(2154)
 source=gpd.read_file(candidate.parent/config['local_path'],layer=config.get('file_layer')).to_crs(2154)[['geometry']];source.geometry=source.geometry.map(make_valid);input_count=len(source);source=source[source.geom_type.isin(['Polygon','MultiPolygon'])];excluded=input_count-len(source);acc={}
 for offset in range(0,len(source),10000):
  pieces=gpd.overlay(source.iloc[offset:offset+10000],grid[['id','geometry']],how='intersection',keep_geom_type=True)
  for key,group in pieces.groupby('id'):
   geometries=list(group.geometry.values)
   if key in acc:geometries.append(acc[key])
   acc[key]=union_all(geometries)
 for f in original['features']:
  p=f['properties'];area=acc[p['id']].area if p['id'] in acc else 0
  p['P_preview']=max(0,min(100,100*area/(p['area_ha']*10000)))
  p['pressure_preview']={'sourceId':config['id'],'year':2025,'built_area_m2':area,'method':'Surface de l’union bâtie / surface de maille ×100','validated':False,'geometry_quality':config['geometry_quality'],'excluded_non_polygon_geometries':excluded,'coverage':'Couverture régionale déclarée par le catalogue, non validée indépendamment','use':'Affichage exploratoire uniquement, exclu de RP'}
 (data/'cells.geojson').write_text(json.dumps(original,ensure_ascii=False,separators=(',',':'),allow_nan=False));print(json.dumps({'preview_cells':len(original['features']),'source_objects':len(source),'excluded_non_polygon_geometries':excluded,'validated_P_unchanged':True}))
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--data-dir',required=True,type=pathlib.Path);a.add_argument('--candidate',required=True,type=pathlib.Path);x=a.parse_args();preview(x.data_dir,x.candidate)
