import sys,unittest,tempfile,os,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pipeline.graph.api import validate_read_query
from pipeline.ingest.api import public_url
class Safety(unittest.TestCase):
 def test_read_only(self):
  validate_read_query('MATCH(n:Commune) RETURN n.name')
  for q in ['MATCH(n) DELETE n','CALL dbms.components()','LOAD CSV FROM "https://example.com" AS row RETURN row','RETURN 1; CREATE(n)']:
   with self.assertRaises(ValueError):validate_read_query(q)
 def test_public_urls(self):
  for url in ['http://example.com','https://127.0.0.1','https://example.com?api_key=example']:
   with self.assertRaises(ValueError):public_url(url)
 def test_real_user_dataset_save(self):
  import pipeline.ingest.api as api
  from fastapi import FastAPI
  from fastapi.testclient import TestClient
  with tempfile.TemporaryDirectory() as d:
   old=api.STORE;api.STORE=Path(d);app=FastAPI();app.include_router(api.router)
   try:
    client=TestClient(app);r=client.post('/api/datasets',json={'metadata':{'display_name':'Source test','theme':'water','group':'Tests','status':'COMPLETE'},'data':{'type':'FeatureCollection','features':[{'type':'Feature','geometry':{'type':'Point','coordinates':[-.37,49.18]},'properties':{'nom':'Caen'}}]}});self.assertEqual(r.status_code,200,r.text);items=client.get('/api/datasets').json();self.assertEqual(len(items),1);self.assertEqual(items[0]['data']['features'][0]['properties']['nom'],'Caen')
   finally:api.STORE=old
if __name__=='__main__':unittest.main()
