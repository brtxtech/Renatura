"""Rebuild reference metadata from the user's supplied inventory snapshot."""
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
lines=(ROOT/'docs/supplied-requirements.txt').read_text().splitlines()
sections=['Biodiversité et continuités écologiques','Eau','Occupation du sol et urbanisme','Paysages et patrimoine','Littoral et DTA ES','Énergie et climat','Risques et nuisances','Carrières et géologie','Mobilité et logement','Réglementation']
status={'Collecte complète':'complete','Partiel':'partial','Fichier vérifié':'verified_file'}
section=sections[0];group='';rows=[]
for i,raw in enumerate(lines):
    line=raw.strip();nxt=lines[i+1].strip() if i+1<len(lines) else ''
    if line in sections:section=line
    heading=re.search(r' (\d+)$',line)
    if heading and int(heading.group(1))<=100 and nxt not in status and 'objets' not in line:
        group=line[:heading.start()]
    if line in status:
        count=re.match(r'([\d\s\u202f\u00a0]+) objets?',nxt)
        rows.append({'id':f'layer-{len(rows)+1:03d}','name':lines[i-1].strip(),'category':section,'group':group,'reported_state':status[line],'reported_count':int(re.sub(r'\D','',count.group(1))) if count else None,'reported_detail':nxt,'schema':None,'actual_imported':False,'provenance':'User-provided catalogue snapshot; no source geometries or API endpoints supplied.'})
(ROOT/'data/catalog.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
print(f'{len(rows)} reference layers generated')
