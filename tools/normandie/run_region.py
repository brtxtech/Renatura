#!/usr/bin/env python3
"""Une commande pour préparation -> graphe -> corridors -> ILP -> Monte Carlo -> audit."""
import argparse,pathlib,subprocess,sys
HERE=pathlib.Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--renatura-root',required=True,type=pathlib.Path);p.add_argument('--catalog',type=pathlib.Path);p.add_argument('--declared-layers',type=int,default=223);p.add_argument('--project',type=pathlib.Path);p.add_argument('--pilot-observations',action='store_true');p.add_argument('--pressure-preview',action='store_true');p.add_argument('--require-full-criteria',action='store_true');p.add_argument('--runs',type=int,default=1000);p.add_argument('--seconds',type=float,default=30);a=p.parse_args()
if a.project and a.pilot_observations:p.error('Choisir --project ou --pilot-observations, pas les deux')
cmd=[sys.executable,str(HERE/'build_normandie.py'),'--renatura-root',str(a.renatura_root.resolve())]
cmd+=['--declared-layers',str(a.declared_layers)]
if a.catalog:cmd+=['--catalog',str(a.catalog.resolve())]
if a.project:cmd+=['--project',str(a.project.resolve())]
if a.pilot_observations:cmd+=['--pilot-observations']
subprocess.run(cmd,check=True)
if a.pressure_preview:
 import tempfile
 with tempfile.TemporaryDirectory() as temp:
  subprocess.run([sys.executable,str(HERE/'import_atlas_pressure.py'),'--renatura-root',str(a.renatura_root.resolve()),'--output',temp],check=True)
  subprocess.run([sys.executable,str(HERE/'pressure_preview.py'),'--data-dir',str(HERE.parent.parent/'dist/data/normandie'),'--candidate',str(pathlib.Path(temp)/'pressure.candidate.json')],check=True)
cmd=[sys.executable,str(HERE/'complete_region.py'),'--data-dir',str(HERE.parent.parent/'dist/data/normandie'),'--runs',str(a.runs),'--seconds',str(a.seconds)]
if a.require_full_criteria:cmd+=['--require-full-criteria']
subprocess.run(cmd,check=True)
