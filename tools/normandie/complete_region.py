#!/usr/bin/env python3
"""Calcule graphe, corridors, scénarios et audit sans inventer les critères manquants."""
import argparse,hashlib,json,math,pathlib,sys
from regional_model.connectivity import analyse
from regional_model.optimisation import solve
from regional_model.sensitivity import monte_carlo

KEYS=['V','D','P','O']
def read(p):return json.loads(p.read_text())
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,separators=(',',':'),allow_nan=False))
def write_gzip(p):
 """Compressed copy for the browser (84 MB -> ~5 MB); the page only uses it if it is not older than the plain file."""
 import gzip,shutil
 with open(p,'rb') as src,gzip.open(str(p)+'.gz','wb',compresslevel=9) as dst:shutil.copyfileobj(src,dst)
def complete(data,runs=1000,seconds=30,strict=False):
 cells=read(data/'cells.geojson');rows=[f['properties'] for f in cells['features']]
 if not rows:raise ValueError('Maillage vide : couverture complète impossible')
 if len({p['id'] for p in rows})!=len(rows):raise ValueError('Identifiants de mailles dupliqués')
 for p in rows:
  for k in KEYS:
   if p.get(k) is not None and (not isinstance(p[k],(int,float)) or not math.isfinite(p[k]) or not 0<=p[k]<=100):raise ValueError('Critère hors bornes : '+p['id']+' / '+k)
 threshold=read(data/'regional_config.json').get('core_threshold',60) if (data/'regional_config.json').exists() else 60
 graph,routes,centrality=analyse(cells,threshold=threshold)
 for p in rows:p['betweenness']=centrality.get(p['id'])
 write(data/'cells.geojson',cells);write_gzip(data/'cells.geojson');write(data/'connectivity.json',graph);write(data/'routes.geojson',routes)
 weights=[.3,.3,.15,.25];specs=[('focused','Intervention ciblée','sites',5),('balanced','Réseau équilibré','sites',12),('ambitious','Ambition territoriale','sites',25),('area500','Enveloppe de 500 ha','hectares',500),('proxy1000','Proxy de 1 000 unités','proxy',1000)]
 presets=[]
 for id,name,mode,budget in specs:
  r=solve(rows,graph['paths'],mode,budget,.35,weights,True,seconds)
  if r['status']=='NO_ELIGIBLE_DATA':continue
  r.update(id=id,name=name,scope='Normandie / mailles réellement observées et éligibles',regional_coverage_complete=graph['observed_cells']==len(rows));presets.append(r)
 write(data/'scenarios.json',presets)
 eligible=[p for p in rows if isinstance(p.get('V'),(int,float)) and math.isfinite(p['V']) and p['V']>=10]
 sensitivity=monte_carlo(eligible,runs,42,weights,True)
 for key,value in {'weights':weights,'allow_partial':True,'mean_top20_jaccard':None,'mean_rank_correlation':None}.items():sensitivity.setdefault(key,value)
 write(data/'sensitivity.json',sensitivity)
 coverage={k:{'available_cells':sum(isinstance(p.get(k),(int,float)) and math.isfinite(p[k]) for p in rows),'total_cells':len(rows)} for k in KEYS}
 complete_cells=sum(all(isinstance(p.get(k),(int,float)) and math.isfinite(p[k]) for k in KEYS) for p in rows)
 blocked=[k for k in KEYS if coverage[k]['available_cells']<len(rows)]
 audit={'status':'complete_coverage' if not blocked else 'incomplete_coverage','criteria':coverage,'all_four_criteria_cells':complete_cells,'blocked_criteria':blocked,'connectivity':{'computed':graph['observed_cells']>0,'cells':graph['observed_cells'],'regional_coverage_complete':graph['observed_cells']==len(rows),'corridors':len(graph['paths'])},'precomputed_scenarios':len(presets),'blockers':{'V':'Inventaires régionaux comparables de haies et boisements requis pour la définition originale.','D':'Deux inventaires régionaux comparables de haies requis.','P':'Indice composite transparent par catégorie (urbanisation : bâti ; infrastructure : routes OSM + rail ; industrie : ICPE ; fréquentation : arrêts de transport OSM), pondéré et renormalisé par maille ; proxy explicite de pression anthropique, pas une mesure d’émission ou de nuisance réelle.','O':'Mobilisabilité foncière documentée nécessaire ; ORE, friches et secteurs potentiels ne prouvent pas le consentement.'},'interpretation':'Fonctions exécutées sur les observations présentes. La couverture régionale complète n’est pas déduite du nombre de sources.'}
 write(data/'readiness.json',audit)
 summary=read(data/'summary.json');summary.update(regional_readiness=audit,connection_count=len(graph['paths']),patch_count=graph['patch_count']);write(data/'summary.json',summary)
 config=read(data/'regional_config.json');config.update(connectivity_available=graph['observed_cells']>0,corridors_available=bool(graph['paths']),connectivity_scope='observed_subset',scenarios_available=bool(presets));write(data/'regional_config.json',config)
 write(data/'manifest.json',{p.name:{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in data.glob('*') if p.is_file() and p.name!='manifest.json'})
 print(json.dumps(audit,ensure_ascii=False,indent=2))
 try:
  from build_display import build as build_display  # light explorer files, rebuilt only if cells changed
  build_display()
 except Exception as error:print('display files not rebuilt:',error)
 if strict and blocked:raise SystemExit(2)
 return audit
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--data-dir',type=pathlib.Path,default=pathlib.Path(__file__).resolve().parents[2]/'dist/data/normandie');a.add_argument('--runs',type=int,default=1000);a.add_argument('--seconds',type=float,default=30);a.add_argument('--require-full-criteria',action='store_true');args=a.parse_args()
 if args.runs<2 or args.seconds<=0:a.error('runs >= 2 et seconds > 0 requis')
 complete(args.data_dir,args.runs,args.seconds,args.require_full_criteria)
