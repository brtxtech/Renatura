import json,os,tempfile,time,unittest
from pathlib import Path
os.environ.setdefault('RENATURA_WORKBENCH_DATA',tempfile.mkdtemp(prefix='renatura-tests-'))
os.environ.setdefault('RENATURA_PUBLISH_DIR',tempfile.mkdtemp(prefix='renatura-publish-'))
os.environ.setdefault('RENATURA_WORKBENCH_OPEN','1')  # functional tests; access rules are tested separately
from fastapi.testclient import TestClient
from pipeline.workbench.app import app
from pipeline.workbench.validation import validate
from pipeline.workbench.calculation import calculate
from pipeline.workbench import db
ROOT=Path(__file__).resolve().parents[2]/'pipeline'/'workbench'  # examples/ live here
class CoreTests(unittest.TestCase):
    def test_catalogue_taxonomy(self):
        rows=json.loads((ROOT/"data/catalog.json").read_text())
        self.assertEqual(len(rows),146)
        self.assertEqual(len({r["category"] for r in rows}),10)
        self.assertEqual(next(r for r in rows if r["name"]=="Sondages zones humides")["group"],"Connaissance et restauration des milieux")
        self.assertEqual(next(r for r in rows if r["name"]=="Corridors · milieu humide · surfacique")["group"],"TVB locales")
    def test_quarantine(self):
        data=json.loads((ROOT/'examples/anomalies.geojson').read_text());schema=json.loads((ROOT/'examples/canopy.schema.json').read_text())
        r=validate(data,schema,['canopy_pct']);self.assertEqual(r['valid_count'],1);self.assertEqual(r['rejected_count'],3)
        self.assertEqual(len(r['anomalies']),3)
    def test_missing_does_not_become_zero(self):
        cfg={'rules':[{'name':'Missing','dataset_id':'missing','field':'v','min':0,'max':100,'weight':1}]}
        r=calculate(cfg,[]);self.assertIsNone(r['score']);self.assertEqual(r['coverage'],0)
    def test_valid_zero_is_calculable(self):
        ds={'id':'d','kind':'json','data':[{'v':0}],'collection_state':'partial'}
        r=calculate({'rules':[{'name':'Zero','dataset_id':'d','field':'v','min':0,'max':100,'weight':1}]},[ds])
        self.assertEqual(r['score'],0);self.assertEqual(r['details'][0]['collection_state'],'partial')
    def test_coverage_threshold(self):
        rules=[{'name':'Known','dataset_id':'d','field':'v','min':0,'max':100,'weight':1},{'name':'Missing','dataset_id':'absent','field':'v','min':0,'max':100,'weight':3}]
        r=calculate({'rules':rules,'minimum_coverage':.6},[{'id':'d','kind':'json','data':[{'v':50}]}])
        self.assertEqual(r['coverage'],.25);self.assertIsNone(r['score'])
    def test_location_required_for_spatial(self):
        r=calculate({'rules':[{'name':'Spatial','dataset_id':'d','field':'v','min':0,'max':1,'weight':1}]},[{'id':'d','kind':'geojson','data':{'features':[]}}]);self.assertIsNone(r['score'])
    def test_import_revision_and_live_recalculation(self):
        with TestClient(app) as c:
            schema=(ROOT/'examples/canopy.schema.json').read_text()
            def upload(file,replace=''):
                return c.post('/api/datasets',files={'file':(file,(ROOT/'examples'/file).read_bytes(),'application/json')},data={'name':'Synthetic canopy','category':'Biodiversité','collection_state':'partial','schema_text':schema,'replace_dataset_id':replace})
            r=upload('canopy.geojson');self.assertEqual(r.status_code,200,r.text);ds=r.json()['dataset']
            cfg={'location':{'lat':49.1829,'lon':-.3707},'radius_m':500,'minimum_coverage':.6,'rules':[{'name':'Canopy','dataset_id':ds['id'],'field':'canopy_pct','min':0,'max':100,'weight':1}]}
            r=c.put('/api/config',json=cfg);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['score'],50)
            r=upload('canopy-updated.geojson',ds['id']);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['previous_calculation']['score'],50);self.assertEqual(r.json()['calculation']['score'],70)
            self.assertTrue(db.get('dataset_revisions',ds['revision']))
            r=c.get('/api/state');self.assertEqual(len(r.json()['catalog']),146)
    def test_invalid_json_and_schema_rejected(self):
        with TestClient(app) as c:
            r=c.post('/api/datasets',files={'file':('bad.json',b'{no','application/json')},data={'name':'Bad'});self.assertEqual(r.status_code,422)
            r=c.post('/api/datasets',files={'file':('bad.json',b'{"v":NaN}','application/json')},data={'name':'Bad'});self.assertEqual(r.status_code,422)
            r=c.put('/api/config',json={'rules':[{'name':'Bad','dataset_id':'d','field':'v','min':5,'max':2}]});self.assertEqual(r.status_code,422)
    def test_workflow_and_cancellation(self):
        with TestClient(app) as c:
            r=c.post('/api/chat',json={'context':'Observe habitat around Caen.'});self.assertEqual(r.status_code,202);key=r.json()['id']
            deadline=time.time()+30
            while time.time()<deadline:
                j=c.get('/api/jobs/'+key).json()
                if j['state'] not in ('running','queued'):break
                time.sleep(.1)
            self.assertEqual(j['state'],'completed',j);self.assertEqual(j['output']['classification']['prediction'],None)
            self.assertTrue(db.get('observations',j['output']['id']))
            self.assertGreaterEqual(len(c.get('/api/logs',params={'job':key}).json()),14)
            r=c.post('/api/chat',json={'context':'Cancellation fixture'});key=r.json()['id'];c.post('/api/jobs/'+key+'/stop')
            deadline=time.time()+10
            while time.time()<deadline:
                j=c.get('/api/jobs/'+key).json()
                if j['state'] not in ('running','queued'):break
                time.sleep(.1)
            self.assertEqual(j['state'],'stopped',j)
            self.assertIsNone(db.get('observations',j['payload']['id']))
    def test_auth_and_image_validation(self):
        with TestClient(app) as c:
            os.environ['RENATURA_TOKEN']='test-only-token'
            try:
                self.assertEqual(c.get('/api/state').status_code,401)
                self.assertEqual(c.get('/api/state',headers={'X-Workspace-Token':'test-only-token'}).status_code,200)
            finally:os.environ.pop('RENATURA_TOKEN',None)
            r=c.post('/api/images',files={'file':('fake.jpg',b'not an image','image/jpeg')});self.assertEqual(r.status_code,422)
if __name__=='__main__':unittest.main()
