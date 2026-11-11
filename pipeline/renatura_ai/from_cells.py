"""Adapter for existing Renatura dist/data/normandie/cells.geojson.
Conservatively extracts V,D,P,O,P_preview and metadata; DOES NOT invent target labels.
"""
import argparse,json
from pathlib import Path
import pandas as pd

def main():
 a=argparse.ArgumentParser();a.add_argument('--input',default='dist/data/normandie/cells.geojson');a.add_argument('--output',default='data/renatura_cells.csv');x=a.parse_args()
 raw=json.loads(Path(x.input).read_text())
 rows=[]
 for i,f in enumerate(raw.get('features',[])):
  p=f.get('properties') or {}; rows.append({'cell_id':str(p.get('cell_id') or p.get('id') or f.get('id') or i),
   'observation_year':p.get('observation_year'),
   'V':p.get('V'),'D':p.get('D'),'P':p.get('P'),'O':p.get('O'), 'P_preview':p.get('P_preview'),
   'loaded_sources':json.dumps(p.get('loaded_sources')) if p.get('loaded_sources') is not None else None})
 output=Path(x.output);output.parent.mkdir(parents=True,exist_ok=True)
 pd.DataFrame(rows).to_csv(output,index=False)
 print(f'Extracted {len(rows)} cells to {output}. This is a coverage audit, NOT ML training material until real features, dates, and independent labels are joined.')
if __name__=='__main__':main()
