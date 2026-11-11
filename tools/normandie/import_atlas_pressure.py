#!/usr/bin/env python3
"""Convertit le bâti disponible en source candidate P ; aucune validation automatique."""
import argparse,gzip,json,pathlib
import geopandas as gpd

def main(root,out):
 atlas=root/'dist/data/atlas';catalog=json.loads((atlas/'catalog.json').read_text());id='file_96dc83a7d1807f4bc3';layer=next(x for x in catalog['layers'] if x['id']==id)
 features=[]
 for chunk in layer['chunks']:
  with gzip.open(atlas/chunk,'rt') as f:features.extend(json.load(f)['features'])
 out.mkdir(parents=True,exist_ok=True);frame=gpd.GeoDataFrame.from_features(features,crs=4326);frame.to_file(out/'built-2025.gpkg',driver='GPKG',layer='built')
 candidate={'id':id,'label':layer['name'],'metric':'built','role':'criterion','category':'urbanisme','year':2025,'enabled':False,'validated':False,'canonical_id':id,'local_path':'built-2025.gpkg','file_layer':'built','coverage_path':str((atlas/'normandie.geojson').resolve()),'status':layer['status'],'source':layer['url'],'geometry_quality':'display_simplified_30m','usage':'P = proportion bâtie, proxy de pression ; géométries d’affichage simplifiées, pas une mesure cadastrale. Validation explicite requise.','validation_requirements':['Contrôler couverture du fichier régional','Comparer les géométries aux données originales non simplifiées','Vérifier que le millésime 2025 convient au modèle','Accepter explicitement la définition du proxy et sa précision']}
 (out/'pressure.candidate.json').write_text(json.dumps({'layers':[candidate]},ensure_ascii=False,indent=2));print(json.dumps({'features':len(features),'candidate':str(out/'pressure.candidate.json'),'validated':False},ensure_ascii=False))
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--renatura-root',required=True,type=pathlib.Path);a.add_argument('--output',required=True,type=pathlib.Path);x=a.parse_args();main(x.renatura_root.resolve(),x.output.resolve())
