#!/usr/bin/env python3
"""Curated thematic catalogue. No source is deleted; alternate snapshots/formats retain provenance."""
import csv,gzip,hashlib,json,re,unicodedata,collections
from pathlib import Path
P=Path(__file__).resolve().parents[2]/'dist/data/atlas'
THEMES=[('biodiversity','Biodiversité et continuités écologiques'),('water','Eau'),('landuse','Occupation du sol et urbanisme'),('landscape','Paysages et patrimoine'),('coast','Littoral et DTA ES'),('energy','Énergie et climat'),('risks','Risques et nuisances'),('geology','Carrières et géologie'),('mobility','Mobilité et logement'),('regulation','Réglementation')]
def norm(s):return re.sub(r'\s+',' ',''.join(c for c in unicodedata.normalize('NFKD',s.lower().replace('’',"'")) if not unicodedata.combining(c))).strip()
def sid(s):return hashlib.sha256(s.encode()).hexdigest()[:14]
def classify(l):
 n=l['name'];s=norm(n);year=None;mode=None;territory=None;level=None;hidden=None
 if not l['map_count']:return None,'Non cartographiable : référence, table, erreur ou hors Normandie'
 if 'sentinelles' in s or 'source link' in s:return None,'Source technique ou signalement à valider ; conservée dans le registre des sources'
 if n.lower().startswith('tvb_') and '.zip' in s:return None,'Archive brute : ses couches thématiques sont déjà cataloguées'
 if s.startswith('tvb '):
  parts=re.split(r'\s*[—–]\s*',n);territory=parts[1] if len(parts)>2 else 'Normandie';raw=norm(parts[-1]);base=raw
  milieu='aquatique' if any(x in raw for x in ['aqu','cours_eau','cours eau','rivieres']) else 'humide' if any(x in raw for x in ['humid','mares','zh_']) else 'bocager' if any(x in raw for x in ['boc','haies','prairies']) else 'boisé' if any(x in raw for x in ['bois','foret']) else 'calcicole' if 'calci' in raw else 'silicicole' if 'silic' in raw else 'landicole' if 'land' in raw else 'littoral' if 'littor' in raw else 'écologique'
  role='Obstacles et ruptures' if any(x in raw for x in ['obstacle','rupture','onema','roe','_pc_']) else 'Corridors' if any(x in raw for x in ['corridor','_ce_']) else 'Espaces écologiques' if any(x in raw for x in ['_er_','relais']) else 'Réservoirs' if any(x in raw for x in ['reservoir','_rb','_rbg','_rbs']) else 'Continuités' if any(x in raw for x in ['continuite','secteur']) else 'Trame'
  extra=' · mares' if 'mares' in raw else ' · haies' if 'haies' in raw else ' · prairies' if 'prairies' in raw else ' · aide à l’interprétation' if 'aide' in raw else ' · cours d’eau' if 'cours_eau' in raw else ''
  extra+= ' · principaux' if 'principaux' in raw else ' · secondaires' if 'secondaires' in raw else ''
  extra+= ' · Mortainais' if 'mortainais' in raw else ''
  extra+= ' · référentiel ROE' if 'referentiel_obstacle' in raw or 'onema_roe' in raw else ' · obstacles inventoriés' if 'obstacle' in raw else ''
  extra+= ' · linéaire' if re.search(r'_l(?:_|$)|_lig_',raw) else ' · surfacique' if re.search(r'_s(?:_|$)|_pol_',raw) else ' · ponctuel' if re.search(r'_p(?:_|$)',raw) else ''
  if 'picanes' in raw:extra+=' · inventaire Picanes'
  return ('biodiversity','TVB locales',role+' · milieu '+milieu+extra,{'territory':territory}),None
 if 'nature en ville' in s:
  year=re.search(r'20\d{2}',s).group();sub=n.split('—')[-1].strip();sub={'Water surfaces':'Surfaces en eau','Permanent low vegetation':'Végétation basse permanente','Tree canopy':'Canopée arborée','Vegetated infrastructure':'Infrastructures végétalisées'}.get(sub,sub)
  return ('biodiversity','Nature en Ville',sub,{'year':year}),None
 if 'corine' in s or s.startswith('clc '):
  if ' dom ' in s:return None,'Hors périmètre normand'
  years=re.findall(r'(?:19|20)\d{2}',s);mode='Changements' if 'change' in s else 'Occupation';year='–'.join(years[:2]) if mode=='Changements' else years[0] if years else 'Non daté'
  return ('landuse','CORINE Land Cover','Occupation et changements',{'mode':mode,'year':year,'revised':'revisee' in s}),None
 if 'tache du bati' in s or 'tachebati' in s:return ('landuse','Tâche du bâti','Emprise bâtie',{'year':re.search(r'20\d{2}',s).group()}),None
 if 'dta es' in s:return ('coast','DTA ES',re.sub(r'^DTA ES\s*[-—–]\s*','',re.sub(r'\s*[—–]\s*WFS$','',n),flags=re.I),{}),None
 if 'src normandie' in s:
  if 'hierarchisation' in s:
   m=re.search(r'niveau (gris|rouge|orange|jaune)',s);level=m.group(1).capitalize() if m else 'Synthèse';return ('geology','SRC · Enjeux environnementaux','Hiérarchisation des enjeux',{'level':level}),None
  clean=re.sub(r'^SRC Normandie\s*[-—–]\s*','',n,flags=re.I);return ('geology','SRC · Ressources et contraintes',clean,{}),None
 if 'geothermie' in s:
  m=re.search(r'(\d+)\s*[–-]\s*(\d+)\s*m',n);return ('energy','Géothermie','Géothermie de minime importance',{'level':m.group(0) if m else n}),None
 if 'pentes' in s or 'predisposes' in s:
  dep=next((v for k,v in [('seine-maritime','76'),('calvados','14'),('eure','27'),("l'orne",'61'),('manche','50')] if k in s),'Normandie');return ('water' if 'predisposes' in s else 'landuse','Milieux humides' if 'predisposes' in s else 'Relief','Prédisposition aux zones humides' if 'predisposes' in s else 'Pentes',{'territory':dep}),None
 protected=[('natura 2000','Natura 2000 · Oiseaux' if ('oiseaux' in s or 'zps' in s) else 'Natura 2000 · Habitats'),('znieff','ZNIEFF '+('2' if 'type 2' in s else '1')+(' · marine' if 'marine' in s else '')),('reserves naturelles nationales','Réserves naturelles nationales'),('reserves naturelles regionales','Réserves naturelles régionales'),('protection de biotope','Arrêtés de protection de biotope'),('protection des habitats','Arrêtés de protection des habitats'),('ramsar','Zones Ramsar'),('parcs naturels regionaux','Parcs naturels régionaux'),('foret de protection','Forêts de protection')]
 for key,title in protected:
  if key in s and 'habitats natura' not in s:return ('biodiversity','Espaces protégés et inventaires',title,{}),None
 if 'srce' in s or any(x in s for x in ['reservoirs de biodiversite','corridors (','continuites interregionales','continuites a rendre','actions prioritaires','secteurs a biodiversite','secteurs d\'interet','voies ferrees','reseau routier','principales zones baties']):
  if 'voies ferrees' in s:return ('mobility','Réseaux de transport','Voies ferrées',{}),None
  if 'reseau routier' in s:return ('mobility','Réseaux de transport','Réseau routier',{}),None
  if 'zones baties' in s:
   size='100' if '100' in s else '10';return ('landuse','Zones bâties','Zones bâties > '+size+' ha',{}),None
  title='Réservoirs de biodiversité' if 'reservoir' in s else 'Corridors interrégionaux' if 'interregion' in s else 'Corridors' if 'corridor' in s else 'Actions prioritaires ponctuelles' if 'ponctuel' in s else 'Actions prioritaires surfaciques' if 'surfac' in s else 'Continuités prioritaires' if 'priorit' in s else 'Biodiversité de plaine' if 'plaine' in s else 'Secteurs d’intérêt'
  territory='Haute-Normandie' if any(x in s for x in ['haute','27-76']) else 'Basse-Normandie' if any(x in s for x in ['basse','14-50-61']) else 'Normandie';return ('biodiversity','SRCE',title,{'territory':territory}),None
 hydro={'bassin hydrographique':'Bassins hydrographiques','bassinhydrographique':'Bassins hydrographiques','bassinversanttopographique':'Bassins versants topographiques','planeau_fxx':'Plans d’eau','surfaceelementaire':'Surfaces élémentaires hydrographiques'}
 for key,title in hydro.items():
  if key in s:return ('water','Référentiels hydrographiques',title,{}),None
 if 'avis de l' in s and 'environnementale' in s:
  title='Avis AE · Plans et programmes' if 'programmes' in s else 'Avis AE · Autorité nationale' if 'nationale' in s else 'Avis AE · Projets';return ('regulation','Évaluation environnementale',title,{}),None
 title=re.sub(r'\s*[—–]\s*WFS$','',n);title=re.sub(r'\s*[-—–]\s*Normandie$','',title);title=title.replace('— Normandie','').strip()
 if any(x in s for x in ['eolien','eolienne','saturation visuelle']):theme,group='energy','Éolien'
 elif any(x in s for x in ['pcaet','climats air']):theme,group='energy','PCAET'
 elif any(x in s for x in ['photovolta','hydroelectri','methanis','chaufferies']):theme,group='energy','Production énergétique'
 elif any(x in s for x in ['icpe','pprt','pprm','miniers','aléas','aleas','pesticid','phytatmo']):theme,group='risks','Risques et nuisances'
 elif any(x in s for x in ['littoral','erosion','hydrosediment']):theme,group='regulation','Littoral et urbanisme'
 elif any(x in s for x in ['sites classes','unesco','paysag','grands sites']):theme,group='landscape','Paysages et patrimoine'
 elif any(x in s for x in ['scot','urbanisme','pavillonn','baties']):theme,group='landuse','Planification et urbanisme'
 elif any(x in s for x in ['anah','opah','aides a la pierre','covoitur','location velo']):theme,group='mobility','Mobilité et logement'
 elif any(x in s for x in ['eau','hydro','ecoulement','piezo','6par','effluent','vulnerable','bassin','riviere','module']):theme,group='water','Milieux aquatiques et gestion de l’eau'
 else:theme,group='biodiversity','Connaissance et restauration des milieux'
 return (theme,group,title,{}),None

def score(l,v):return (int(bool(l['map_count'])),int(v.get('revised',False)),int(l['status'] in ['COMPLETE','FILE_VERIFIED']),l['map_count'],int(l['kind']!='FILE'))
def build():
 raw=json.load(open(P/'catalog.json'));tree={i:{'id':i,'display_name':name,'groups':{}} for i,name in THEMES};hidden=[];rows=[];merges=[]
 for l in raw['layers']:
  info,reason=classify(l)
  if not info:hidden.append({'source_id':l['id'],'name':l['name'],'reason':reason});continue
  theme,group,title,dimensions=info;title=re.sub(r'\s*[—–]\s*WFS$','',title).strip();gid='g_'+sid(theme+group);lid='l_'+sid(theme+group+norm(title));g=tree[theme]['groups'].setdefault(gid,{'id':gid,'display_name':group,'theme':theme,'layers':{},'facets':{}});layer=g['layers'].setdefault(lid,{'id':lid,'display_name':title,'theme':theme,'group':gid,'variants':{}})
  dims={k:v for k,v in dimensions.items() if k!='revised'};vid='v_'+sid(lid+json.dumps(dims,sort_keys=True));variant=layer['variants'].setdefault(vid,{'id':vid,'dimensions':dims,'source_ids':[],'_choices':[]});variant['source_ids'].append(l['id']);variant['_choices'].append((l,dimensions))
 for theme in tree.values():
  for g in theme['groups'].values():
   for layer in g['layers'].values():
    for v in layer['variants'].values():
     choices=v.pop('_choices');primary,extra=max(choices,key=lambda x:score(*x));v.update(source_id=primary['id'],status='complete' if primary['status'] in ['COMPLETE','FILE_VERIFIED'] else 'partial',map_count=primary['map_count'],updated=primary.get('collected_at'),source=primary.get('url'),default_visible=any(x in primary['name'] for x in ['Réserves Naturelles Nationales','Parcs éoliens terrestres — points','Station hydrométrique - Normandie']))
     geometry='unknown'
     if primary['chunks']:
      path=P/primary['chunks'][0]
      with gzip.open(path,'rt') if str(path).endswith('.gz') else path.open() as f:features=json.load(f)['features']
      if features:geometry={'Point':'point','MultiPoint':'point','LineString':'line','MultiLineString':'line','Polygon':'polygon','MultiPolygon':'polygon'}.get(features[0]['geometry']['type'],'mixed')
     v['geometry']=geometry;kind=next((k for k in ['year','territory','level'] if k in v['dimensions']),'none');v['variant_type']=kind;v['variant_value']=v['dimensions'].get(kind);rows.append({'id':v['id'],'display_name':layer['display_name'],'theme':theme['display_name'],'group':g['display_name'],'variant_type':kind,'variant_value':v['variant_value'],'geometry':geometry,'status':v['status'],'default_visible':v['default_visible'],'source':v['source'],'updated':v['updated'],'source_id':v['source_id'],'source_ids':'|'.join(v['source_ids'])})
     if len(choices)>1:merges.append({'logical_layer':layer['display_name'],'dimensions':v['dimensions'],'preferred':v['source_id'],'alternatives':v['source_ids'],'rule':'Prefer revised version, complete extraction, then largest retained count. Alternative sources retained; counts not added.'})
     for k,value in v['dimensions'].items():g['facets'].setdefault(k,set()).add(value)
    layer['variants']=list(layer['variants'].values())
   g['layers']=sorted(g['layers'].values(),key=lambda l:l['display_name']);g['facets']={k:sorted(v) for k,v in g['facets'].items()};g['selection']={k:('Tous' if k=='territory' and g['display_name']!='TVB locales' else 'Occupation' if k=='mode' else 'Synthèse' if k=='level' and 'Synthèse' in v else v[-1]) for k,v in g['facets'].items()}
   if g['display_name']=='CORINE Land Cover':g['selection']['year']='2018'
  theme['groups']=sorted(theme['groups'].values(),key=lambda g:g['display_name'])
 result={'schema_version':2,'themes':list(tree.values()),'hidden_sources':hidden,'source_registry':'catalog.json','note':'Groups and display variants are editorial. Alternate source counts are never added as unique objects.','statistics':{'themes':len(tree),'groups':sum(len(t['groups']) for t in tree.values()),'logical_layers':sum(len(g['layers']) for t in tree.values() for g in t['groups']),'variants':len(rows),'source_references_preserved':len(raw['layers'])}}
 (P/'catalog-v2.json').write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')))
 with (P/'catalog-v2.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 (P/'catalog-review.json').write_text(json.dumps({'statistics':result['statistics'],'preferred_sources':merges,'hidden_sources':hidden,'limitations':['Semantic grouping retains all provenance; not a geometry-level deduplication of individual observations.','Territory variants are combined only when their facet is Tous; overlaps may persist.']},ensure_ascii=False,indent=2));print(result['statistics'])
if __name__=='__main__':build()
