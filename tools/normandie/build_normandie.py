#!/usr/bin/env python3
"""Adaptateur de données régional pour la VUE ORIGINALE Renatura. Aucun téléchargement."""
import argparse,datetime,hashlib,json,pathlib,shutil,tempfile,sys
import geopandas as gpd
from shapely import union_all
from prepare import main as prepare
ROOT=pathlib.Path(__file__).resolve().parents[2]
def read(p):return json.loads(pathlib.Path(p).read_text())
def write(p,v):p=pathlib.Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,separators=(',',':'),allow_nan=False))
def build(args):
 original=args.renatura_root.resolve();atlas=original/'dist/data/atlas';dest=ROOT/'dist/data/normandie';dest.mkdir(parents=True,exist_ok=True)
 boundary=atlas/'normandie.geojson'
 if not boundary.exists():raise ValueError('Contour régional du projet absent : '+str(boundary))
 catalogue=read(args.catalog.resolve() if args.catalog else atlas/'catalog.json')
 if not isinstance(catalogue.get('layers'),list):raise ValueError('Le catalogue doit contenir layers[]')
 if args.project:
  project=args.project.resolve();config=read(project);metrics_catalog=read(project.parent/config['catalog'])
 else:
  metrics_catalog={'layers':[]};config={'before_year':2010,'after_year':2016,'hex_area_km2':args.km2,'min_fragment_ha':1,'normalization_reference':'Normandie / observations couvertes / '+datetime.date.today().isoformat(),'allow_pressure_proxy':False}
  if args.pilot_observations:
   for metric,filename,year in [('hedges_before','hedges-2010.geojson',2010),('hedges_after','hedges-2016.geojson',2016),('woodland','woodland.geojson',2016)]:
    metrics_catalog['layers'].append({'id':'pilot-'+metric,'canonical_id':'FR2502014-'+metric,'label':'FR2502014 · '+metric+' · '+str(year),'metric':metric,'year':year,'role':'criterion','enabled':True,'validated':True,'local_path':str(original/'dist/data'/filename),'coverage_path':str(original/'dist/data/boundary.geojson'),'feature_semantics':'hedge_only','status':'COMPLETE','source':'https://www.data.gouv.fr/datasets/haies-et-zones-boisees-du-site-natura-2000-fr2502014-bocages-et-vergers-du-sud-pays-dauge-normandie','usage':'V/D : observations uniquement dans FR2502014, jamais extrapolées à toute la région.'})
 with tempfile.TemporaryDirectory() as temporary:
  tmp=pathlib.Path(temporary)
  # Résoudre les chemins du projet personnalisé avant de créer les fichiers temporaires.
  if args.project:
   base=args.project.resolve().parent
   for layer in metrics_catalog['layers']:
    for k in ['local_path','coverage_path']:
     if layer.get(k):layer[k]=str((base/layer[k]).resolve())
  metrics_catalog.update(declared_layers=args.declared_layers,declared_records=2930005)
  write(tmp/'catalog.json',metrics_catalog);config.update(boundary=str(boundary),catalog='catalog.json',output='prepared.geojson')
  write(tmp/'project.json',config);prepare(tmp/'project.json');collection=read(tmp/'prepared.geojson')
  bound=read(boundary);shutil.copyfile(boundary,dest/'boundary.geojson');rows=[]
  for feature in collection['features']:
   p=feature['properties'];area=p['area_ha'];m=p['metrics'];e=p['evidence']
   p.update(commune='Maille régionale '+p['id'],commune_codes=[],department=None,proxy_cost=area,coverage=25*sum(p[k] is not None for k in ['V','D','P','O']),betweenness=None,hedge_1947_m=None,hedge_2010_m=m['hedges_before']*area if m['hedges_before'] is not None else None,hedge_2016_m=m['hedges_after']*area if m['hedges_after'] is not None else None,woodland_ha=m['woodland']*area if m['woodland'] is not None else None)
   p['observation_years']={'before':config.get('before_year',2010),'after':config.get('after_year',2016)};rows.append(p)
  # Réutiliser le référentiel communal original s'il existe : noms pour la recherche.
  communes=original/'raw/communes.geojson'
  if communes.exists():
   cf=gpd.read_file(communes).to_crs(2154);grid=gpd.GeoDataFrame.from_features(collection['features'],crs=4326).to_crs(2154)
   joined=gpd.overlay(grid[['id','geometry']],cf[['nom','code','geometry']],how='intersection',keep_geom_type=True);joined['overlap']=joined.area
   lookup={key:group.sort_values('overlap',ascending=False) for key,group in joined.groupby('id')}
   for p in rows:
    if p['id'] in lookup:
     group=lookup[p['id']];p.update(commune=str(group.iloc[0]['nom']),commune_codes=[str(x) for x in group['code']],department=str(group.iloc[0]['code'])[:2])
  # Couverture du référentiel communal d'Orne limitée : aucun nom attribué ailleurs.
  write(dest/'cells.geojson',collection)
  total_area=sum(p['area_ha'] for p in rows);cov=[p['coverage'] for p in rows]
  summary={'title':'Normandie · territoire régional','site':'NORMANDIE-28','built_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'cell_count':len(rows),'area_ha':total_area,'boundary_area_ha':total_area+collection['metadata']['excluded_ha'],'omitted_slivers_ha':collection['metadata']['excluded_ha'],'hedge_2016_km':sum(p['hedge_2016_m'] or 0 for p in rows)/1000 if any(p['hedge_2016_m'] is not None for p in rows) else None,'coverage_min':min(cov),'coverage_max':max(cov),'declared_layers':args.declared_layers,'declared_records':2930005,'actual_catalogue_references':len(catalogue['layers']),'status':'regional_variable_coverage','weights':[.3,.3,.15,.25],'limits':['Maillage régional entier ; scores seulement sur les mailles effectivement couvertes.','Le contour régional est généralisé à 5 m selon la provenance du projet.','Le catalogue contient des sources contextuelles et des formats alternatifs, pas autant de critères indépendants.','Les noms communaux dépendent du référentiel fourni.','Les connexions ne sont pas calculées par cette construction ; aucun gain régional inventé.','P (pression anthropique) est un indice composite transparent par catégorie — urbanisation (bâti), infrastructure (routes OSM + rail SRCE), industrie (ICPE), fréquentation (arrêts de transport OSM) — pondéré et renormalisé par maille sur les composants disponibles ; ce n’est pas une mesure d’émission ou de nuisance réelle. Le réseau routier DREAL a été remplacé par le réseau OSM (complet, sans troncature de pagination) ; CORINE Land Cover, les fragilités pavillonnaires et les ressources géologiques du catalogue 193-couches ont été exclus de P : toutes leurs variantes sont PARTIAL pour la même raison (limite de pages WFS). Aucune couche de végétation/boisement régionale complète n’est disponible pour l’instant.']}
  sources=[];bindings={l['id']:l for l in metrics_catalog['layers']}
  for l in catalogue['layers']:
   sources.append({'id':l['id'],'title':l['name'],'categories':l.get('categories',[]),'status':'context','producer':'Voir la référence du catalogue original','licence':l.get('license'),'years':[],'url':l.get('url'),'resolution':'Voir métadonnées source','crs':'Voir source','sha256':l.get('sha256'),'processing':'Contexte uniquement ; non utilisé automatiquement dans V/D/P/O.','usage':'Contexte : '+ '; '.join(l.get('use_cases') or [])})
  for l in bindings.values():sources.append({'id':l['id'],'title':l['label'],'categories':[l.get('category','biodiversite')],'status':'used' if l['id'] in collection['metadata']['loaded_sources'] else 'unavailable','producer':'Source configurée et validée par le projet','licence':l.get('licence','Vérifier source'),'years':[l.get('year')],'url':l.get('source'),'resolution':'Mesures géométriques par maille','crs':'EPSG:2154 → EPSG:4326','sha256':None,'processing':l.get('usage','Métrique '+l.get('metric','contexte')),'usage':l.get('usage','Métrique '+l.get('metric','contexte'))})
  write(dest/'summary.json',summary);write(dest/'data_catalog.json',sources);write(dest/'source_registry.json',metrics_catalog)
  # Contrats originaux préservés. Les pré-calculs du pilote ne sont pas recyclés à l'échelle régionale.
  write(dest/'scenarios.json',[]);write(dest/'connectivity.json',{'paths':[],'status':'non_calculated_regional'});write(dest/'sensitivity.json',{'runs':0,'seed':42,'weights':[.3,.3,.15,.25],'allow_partial':True,'sites':[],'mean_top20_jaccard':None,'mean_rank_correlation':None})
  empty={'type':'FeatureCollection','features':[]}
  for file in ['woodland.geojson','routes.geojson','hedges-1947.geojson','hedges-2010.geojson','hedges-2016.geojson']:write(dest/file,empty)
  if args.pilot_observations:
   for name in ['woodland.geojson','hedges-1947.geojson','hedges-2010.geojson','hedges-2016.geojson']:shutil.copyfile(original/'dist/data'/name,dest/name)
  # Toute nouvelle période configure aussi le sélecteur de couche observée.
  write(dest/'regional_config.json',{'hedge_years':[config.get('before_year',2010),config.get('after_year',2016)],'connectivity_available':False,'hex_area_km2':config.get('hex_area_km2',1)})
  manifest={p.name:{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in dest.glob('*') if p.is_file() and p.name!='manifest.json'};write(dest/'manifest.json',manifest)
  print(json.dumps({'cells':len(rows),'area_km2':total_area/100,'cells_with_V':sum(p['V'] is not None for p in rows),'sources_loaded':collection['metadata']['loaded_sources'],'output':str(dest)},ensure_ascii=False))
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--renatura-root',required=True,type=pathlib.Path);a.add_argument('--catalog',type=pathlib.Path,help='Catalogue régional actuel, par exemple vos 223 couches');a.add_argument('--declared-layers',type=int,default=223);a.add_argument('--project',type=pathlib.Path,help='Projet métriques extensible prepare.py');a.add_argument('--pilot-observations',action='store_true',help='Importer les observations originales seulement sur leur couverture locale');a.add_argument('--km2',type=float,default=1);build(a.parse_args())
