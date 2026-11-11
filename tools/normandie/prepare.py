#!/usr/bin/env python3
"""Prétraitement SIG local. Entrées réelles uniquement ; aucune simulation régionale."""
import argparse,hashlib,json,math,pathlib,collections
import geopandas as gpd
import pyogrio
from shapely import wkb as shapely_wkb
from shapely.geometry import Polygon
from shapely import make_valid,union_all
from shapely.prepared import prep

CACHE_DIR=pathlib.Path(__file__).resolve().parents[2]/'derived/prepare_cache'

def source_cache_key(source,cfg,base):
 """Tout ce qui, s'il change, invalide le cache de superposition pour cette source."""
 parts=[source['id'],source.get('canonical_id',''),source.get('metric',''),str(source.get('year'))]
 for key in ('local_path','coverage_path'):
  if source.get(key):
   p=base/source[key]
   try:stat=p.stat();parts.append(f'{key}:{stat.st_mtime_ns}:{stat.st_size}')
   except FileNotFoundError:parts.append(f'{key}:missing')
 parts.append('filters:'+json.dumps(source.get('filters',{}),sort_keys=True))
 parts.append('layer:'+str(source.get('file_layer','')))
 parts.append('grid:'+str(cfg.get('hex_area_km2',1))+':'+str(cfg.get('min_fragment_ha',1)))
 boundary_path=base/cfg['boundary']
 try:stat=boundary_path.stat();parts.append(f'boundary:{stat.st_mtime_ns}:{stat.st_size}')
 except FileNotFoundError:pass
 return hashlib.sha256('|'.join(parts).encode()).hexdigest()[:20]

def load_cached_overlay(source,cfg,base):
 key=source_cache_key(source,cfg,base);path=CACHE_DIR/f'{source["id"]}_{key}.json'
 if not path.exists():return None,key
 payload=json.loads(path.read_text(encoding='utf-8'))
 parts={cellid:shapely_wkb.loads(bytes.fromhex(h)) for cellid,h in payload['source_parts'].items()}
 return {'source_parts':parts,'n_filtered':payload['n_filtered']},key

def save_cached_overlay(source,key,source_parts,n_filtered):
 CACHE_DIR.mkdir(parents=True,exist_ok=True)
 payload={'source_parts':{cellid:shapely_wkb.dumps(g).hex() for cellid,g in source_parts.items()},'n_filtered':n_filtered}
 (CACHE_DIR/f'{source["id"]}_{key}.json').write_text(json.dumps(payload),encoding='utf-8')

CRS='EPSG:2154'
DEFINITIONS={'hedges_before':'line_density','hedges_after':'line_density','woodland':'area_fraction','built':'area_fraction','icpe':'point_density','rail':'line_density','roads':'line_density','stops':'point_density','opportunity':'area_fraction'}
# Catégories de pression anthropique, par type d'empreinte humaine mesurée au sol :
#   urbanisation (bâti)   : artificialisation / emprise construite
#   infrastructure (routes, rail) : fragmentation par réseaux de transport lourds
#   industrie (ICPE)       : établissements classés, pollution potentielle
#   fréquentation (stops)  : densité de lieux de transit / activité humaine
# Chaque catégorie est d'abord classée en rang percentile (comme V), puis combinée par
# une moyenne pondérée renormalisée sur les composants réellement disponibles par maille.
PRESSURE_METRICS=('built','roads','icpe','stops','rail')
DEFAULT_PRESSURE_WEIGHTS={'built':0.35,'roads':0.30,'icpe':0.20,'stops':0.10,'rail':0.05}
MIN_PRESSURE_WEIGHT_COVERAGE=0.4
def load_json(p):return json.loads(p.read_text(encoding='utf-8'))
def dump(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def geom_file(path):
 g=gpd.read_file(path)
 if g.crs is None:raise ValueError(f'CRS absent : {path}')
 g=g.to_crs(CRS);return union_all([make_valid(x) for x in g.geometry if x is not None and not x.is_empty])
def rank(values):
 ref=sorted(v for v in values if v is not None and math.isfinite(v) and v>=0)
 def one(v):
  if v is None:return None
  if v==0:return 0.
  if not ref:return None
  lo=sum(x<v for x in ref);eq=sum(x==v for x in ref)
  return 100*(lo+eq/2)/len(ref)
 return [one(v) for v in values]
def grid(boundary,area_km2,min_ha,max_candidates):
 if not math.isfinite(area_km2) or area_km2<=0:raise ValueError('Surface de maille invalide')
 side=math.sqrt(2*area_km2*1e6/(3*math.sqrt(3)));dy=math.sqrt(3)*side
 minx,miny,maxx,maxy=boundary.bounds
 # Origine Lambert-93 commune à toutes les extractions de même résolution.
 c0=math.floor(minx/(1.5*side))-1;c1=math.ceil(maxx/(1.5*side))+1
 r0=math.floor(miny/dy)-1;r1=math.ceil(maxy/dy)+1
 if (c1-c0+1)*(r1-r0+1)>max_candidates:raise ValueError('Trop de mailles candidates : augmenter la surface ou la limite explicite')
 rows=[];excluded=0.;prepared=prep(boundary)
 for col in range(c0,c1+1):
  for row in range(r0,r1+1):
   x=col*1.5*side;y=(row+.5*(col%2))*dy
   p=Polygon([(x+side*math.cos(math.pi*k/3),y+side*math.sin(math.pi*k/3)) for k in range(6)])
   if not prepared.intersects(p):continue
   clipped=p if prepared.covers(p) else make_valid(p.intersection(boundary))
   if clipped.is_empty or clipped.area==0:continue
   ha=clipped.area/10000
   if ha<min_ha:excluded+=ha;continue
   rows.append({'cell_id':f'H{area_km2:g}_{col}_{row}','area_ha':ha,'geometry':clipped})
 if not rows:raise ValueError('Aucune maille conservée')
 return gpd.GeoDataFrame(rows,crs=CRS),excluded

def main(config_path):
 base=config_path.parent;cfg=load_json(config_path);catalog=load_json(base/cfg['catalog']);boundary=geom_file(base/cfg['boundary'])
 if boundary.is_empty or not boundary.geom_type.endswith('Polygon'):raise ValueError('Frontière régionale surfacique attendue')
 cells,excluded=grid(boundary,float(cfg.get('hex_area_km2',1)),float(cfg.get('min_fragment_ha',1)),cfg.get('max_candidates',150000))
 before_year=cfg.get('before_year',2010);after_year=cfg.get('after_year',2016)
 if before_year>=after_year:raise ValueError('Années des inventaires non ordonnées')
 definitions={**DEFINITIONS,**cfg.get('extra_metric_definitions',{})}
 if any(v not in ['line_density','area_fraction','point_density'] for v in definitions.values()):raise ValueError('Agrégation inconnue')
 ids=list(cells.cell_id);geoms=dict(zip(ids,cells.geometry));areas=dict(zip(ids,cells.area_ha));fragments=collections.defaultdict(dict);coverages=collections.defaultdict(list);trace=collections.defaultdict(lambda:collections.defaultdict(list));loaded=[];warnings=[];canonical=set()
 for source in catalog['layers']:
  if not(source.get('enabled') and source.get('validated') and source.get('metric')):continue
  metric=source['metric'];kind=definitions.get(metric)
  if metric in DEFINITIONS and source.get('role')!='criterion':warnings.append('Rôle contexte, exclu du score : '+source['id']);continue
  if kind is None:raise ValueError(f'Métrique non enregistrée : {metric}')
  token=(source.get('canonical_id',source['id']),metric,source.get('year'))
  if token in canonical:raise ValueError(f'Double version canonique : {token}')
  canonical.add(token)
  if source.get('year') is None:raise ValueError(f'Année requise : {source["id"]}')
  expected={'hedges_before':before_year,'hedges_after':after_year,'woodland':after_year}.get(metric)
  if expected is not None and source['year']!=expected:raise ValueError(f'Année incompatible avec la méthode : {source["id"]}, attendu {expected}')
  if metric.startswith('hedges') and not(source.get('filters') or source.get('feature_semantics')=='hedge_only'):raise ValueError('Configurer Nature=haie ou attester feature_semantics=hedge_only')
  if metric in PRESSURE_METRICS+('opportunity',) and not source.get('validation',{}).get('evidence'):raise ValueError('Référence de validation documentée obligatoire pour P/O : '+source['id'])
  if metric in PRESSURE_METRICS and not cfg.get('allow_pressure_proxy',False):warnings.append('Composant de pression non activé : '+source['id']);continue
  if metric=='opportunity' and not(source.get('opportunity_documented') and source.get('filters')):raise ValueError('O exige statut foncier documenté et filtre des terrains mobilisables')
  if not source.get('local_path'):warnings.append('Fichier absent : '+source['id']);continue
  if source.get('status')=='PARTIAL' and not(cfg.get('allow_partial_sources') and source.get('coverage_path')):warnings.append('Source partielle exclue : '+source['id']);continue
  if source.get('coverage_path'):coverage=geom_file(base/source['coverage_path']).intersection(boundary)
  elif source.get('coverage_complete'):coverage=boundary
  else:warnings.append('Couverture inconnue : '+source['id']);continue
  relevant=cells[cells.intersects(coverage)]
  cached,cache_key=load_cached_overlay(source,cfg,base)
  if cached is not None:
   source_parts=cached['source_parts'];n_filtered=cached['n_filtered']
   print(source['id'],n_filtered,'objets filtrés (cache)',flush=True)
  else:
   kwargs={}
   if source.get('file_layer'):kwargs['layer']=source['file_layer']
   path=base/source['local_path'];info=pyogrio.read_info(path,**kwargs)
   if not info['crs']:raise ValueError('CRS source absent : '+source['id'])
   bbox=tuple(gpd.GeoSeries([boundary],crs=CRS).to_crs(info['crs']).total_bounds)
   data=gpd.read_file(path,bbox=bbox,**kwargs).to_crs(CRS)
   for key,allowed in source.get('filters',{}).items():
    if key not in data:raise ValueError(f'Champ {key} absent : {source["id"]}')
    if not isinstance(allowed,list):allowed=[allowed]
    data=data[data[key].isin(allowed)]
   data=data[['geometry']].copy();data.geometry=data.geometry.map(lambda g:make_valid(g) if g is not None else None);data=data[data.geometry.notna()&~data.geometry.is_empty]
   expected_types={'line_density':['LineString','MultiLineString'],'area_fraction':['Polygon','MultiPolygon'],'point_density':['Point','MultiPoint']}[kind]
   if not data.geom_type.isin(expected_types).all():raise ValueError('Types géométriques incompatibles : '+source['id'])
   data=data.drop_duplicates(subset='geometry')
   if kind=='point_density':data=data.explode(index_parts=False).reset_index(drop=True).drop_duplicates(subset='geometry')
   source_parts={}
   # Fragments exacts par cellule ; union progressive pour éviter le double comptage.
   for offset in range(0,len(data),10000):
    chunk=data.iloc[offset:offset+10000].copy();chunk.geometry=chunk.geometry.intersection(coverage);chunk=chunk[~chunk.geometry.is_empty]
    if chunk.empty:continue
    if kind=='point_density':chunk['_point_id']=chunk.index
    overlay=gpd.overlay(chunk,relevant[['cell_id','geometry']],how='intersection',keep_geom_type=False)
    if kind=='point_density' and not overlay.empty:overlay=overlay.sort_values('cell_id').drop_duplicates('_point_id')
    for cellid,group in overlay.groupby('cell_id'):
     # Les contacts ponctuels de lignes ne contribuent pas à la longueur.
     piece=union_all(group.geometry.values)
     source_parts[cellid]=union_all([source_parts[cellid],piece]) if cellid in source_parts else piece
   n_filtered=len(data)
   save_cached_overlay(source,cache_key,source_parts,n_filtered)
   print(source['id'],n_filtered,'objets filtrés',flush=True)
  coverages[metric].append(coverage)
  for cellid,g in source_parts.items():fragments[metric][cellid]=union_all([fragments[metric][cellid],g]) if cellid in fragments[metric] else g
  for cellid in relevant.cell_id:
   g=source_parts.get(cellid);raw=0 if g is None else (g.length if kind=='line_density' else g.area/10000 if kind=='area_fraction' else len(g.geoms) if g.geom_type=='MultiPoint' else 1)
   trace[metric][cellid].append({'sourceId':source['id'],'year':source['year'],'metric':metric,'value':raw,'unit':'m' if kind=='line_density' else 'ha' if kind=='area_fraction' else 'objets'})
  loaded.append(source['id'])
 metric_values={}
 for metric in definitions:
  cover=union_all(coverages[metric]) if coverages[metric] else None;values=[]
  for cellid in ids:
   if cover is None or geoms[cellid].difference(cover).area>1e-4:values.append(None);continue
   g=fragments[metric].get(cellid);kind=definitions[metric]
   raw=0 if g is None else (g.length if kind=='line_density' else g.area/10000 if kind=='area_fraction' else len(g.geoms) if g.geom_type=='MultiPoint' else 1)
   values.append(raw/areas[cellid])
  metric_values[metric]=values
 h_rank=rank(metric_values['hedges_after']);w_rank=rank(metric_values['woodland']);records=[]
 pressure_weights={**DEFAULT_PRESSURE_WEIGHTS,**cfg.get('pressure_weights',{})}
 pressure_total_weight=sum(pressure_weights.get(m,0) for m in PRESSURE_METRICS)
 pressure_ranks={m:rank(metric_values[m]) for m in PRESSURE_METRICS if m in metric_values}
 for i,cellid in enumerate(ids):
  V=(h_rank[i]+w_rank[i])/2 if h_rank[i] is not None and w_rank[i] is not None else None
  hb=metric_values['hedges_before'][i];ha=metric_values['hedges_after'][i];D=100*max(0,1-ha/hb) if hb is not None and hb>0 and ha is not None else None
  available_pressure=[(m,pressure_ranks[m][i]) for m in PRESSURE_METRICS if m in pressure_ranks and pressure_ranks[m][i] is not None]
  pressure_weight_sum=sum(pressure_weights.get(m,0) for m,_ in available_pressure)
  P=(sum(pressure_weights.get(m,0)*v for m,v in available_pressure)/pressure_weight_sum
     if available_pressure and pressure_total_weight>0 and pressure_weight_sum>=MIN_PRESSURE_WEIGHT_COVERAGE*pressure_total_weight
     else None)
  O=100*min(1,metric_values['opportunity'][i]) if metric_values['opportunity'][i] is not None else None
  mapping={'V':['hedges_after','woodland'],'D':['hedges_before','hedges_after'],'P':list(PRESSURE_METRICS),'O':['opportunity']}
  ev={k:[e for m in metrics for e in trace[m][cellid]] for k,metrics in mapping.items()}
  records.append({'id':cellid,'area_ha':areas[cellid],'V':V,'D':D,'P':P,'O':O,'metrics':{m:metric_values[m][i] for m in definitions},'evidence':ev,'missing_reasons':{'V':'Haies/bois ou couverture/référence insuffisants','D':'Inventaires absents, couverture incomplète ou référence nulle','P':f'Composite de pression (bâti/routes/ICPE/arrêts/rail) : couverture pondérée sous le seuil de {round(MIN_PRESSURE_WEIGHT_COVERAGE*100)}% requis, ou aucune source activée','O':'Mobilisabilité foncière non documentée ou sans couverture complète'},'normalization_reference':cfg.get('normalization_reference','Non nommée'),'methods':{'V':'Moyenne des rangs moyens des densités de haies et de bois ; zéro reste zéro','D':f'Recul net {before_year}–{after_year}','P':'Indice composite de pression anthropique, par catégorie : rang percentile par maille de chaque composant disponible &mdash; urbanisation : bâti '+str(round(100*pressure_weights.get("built",0)/pressure_total_weight))+'% ; infrastructure : routes '+str(round(100*pressure_weights.get("roads",0)/pressure_total_weight))+'% + rail '+str(round(100*pressure_weights.get("rail",0)/pressure_total_weight))+'% ; industrie : ICPE '+str(round(100*pressure_weights.get("icpe",0)/pressure_total_weight))+'% ; fréquentation : arrêts de transport '+str(round(100*pressure_weights.get("stops",0)/pressure_total_weight))+'% &mdash; moyenne pondérée renormalisée sur les composants réellement couvrant la maille ; proxy transparent, pas une mesure d’émission ou de nuisance réelle. Réseau routier DREAL remplacé par OSM (complet) ; CORINE/fragilités/géologie exclus (toutes variantes PARTIAL) ; aucune couche de végétation régionale complète disponible.','O':'Surface mobilisable documentée / surface de maille ; pas de probabilité de disponibilité'}})
 output=gpd.GeoDataFrame(records,geometry=cells.geometry.values,crs=CRS).to_crs('EPSG:4326')
 result=json.loads(output.to_json(drop_id=True,na='null'));result['metadata']={'scope':'Normandie selon la frontière fournie','normalization_reference':cfg.get('normalization_reference'),'hex_area_km2':cfg.get('hex_area_km2',1),'excluded_ha':excluded,'loaded_sources':loaded,'warnings':warnings,'declared_layers':catalog.get('declared_layers'),'declared_records':catalog.get('declared_records'),'hedge_years':[before_year,after_year]}
 dump(base/cfg['output'],result)
 print('Écrit',base/cfg['output'],len(records),'mailles ; sources',len(loaded))
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('project',type=pathlib.Path);args=parser.parse_args();main(args.project.resolve())
