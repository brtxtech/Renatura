"""Inspect data coverage without assuming all atlas layers are ingested."""
import argparse,json
from .training import load_table

def main():
 p=argparse.ArgumentParser();p.add_argument('--data',required=True);a=p.parse_args()
 df=load_table(a.data)
 print(json.dumps({'rows':len(df),'columns':df.columns.tolist(),'non_null':df.notna().sum().to_dict(),
 'years':sorted(df['observation_year'].dropna().astype(str).unique().tolist()) if 'observation_year' in df else [],
 'unique_cells':int(df['cell_id'].nunique()) if 'cell_id' in df else None},indent=2,ensure_ascii=False))
if __name__=='__main__':main()
