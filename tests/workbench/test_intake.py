import os,tempfile,json,time,unittest
from pathlib import Path
os.environ.setdefault('RENATURA_WORKBENCH_DATA',tempfile.mkdtemp(prefix='intake-tests-'))
os.environ.setdefault('RENATURA_PUBLISH_DIR',tempfile.mkdtemp(prefix='intake-publish-'))
os.environ.setdefault('RENATURA_WORKBENCH_OPEN','1')  # functional tests; access rules are tested separately
from fastapi.testclient import TestClient
from pipeline.workbench.app import app
from pipeline.workbench import db
ROOT=Path(__file__).resolve().parents[2]/'pipeline'/'workbench'  # examples/ live here
class IntakeTests(unittest.TestCase):
    def wait(self,c,key):
        deadline=time.time()+30
        while time.time()<deadline:
            j=c.get('/api/jobs/'+key).json()
            if j['state'] not in ('queued','running'):return j
            time.sleep(.05)
        self.fail('Worker did not finish')
    def test_gate_population_removal_and_restore(self):
        with TestClient(app) as c:
            category=next(x for x in c.get('/api/intake/state').json()['categories'] if x['name']=='Biodiversité et continuités écologiques')
            r=c.post('/api/intake/uploads',files={'file':('anomalies.geojson',(ROOT/'examples/anomalies.geojson').read_bytes(),'application/json')},data={'reference':'Intake quality fixture','element_type':'geojson','category_id':category['id'],'schema_text':(ROOT/'examples/canopy.schema.json').read_text(),'collection_state':'partial'})
            self.assertEqual(r.status_code,202,r.text);key=r.json()['batch_id'];self.assertEqual(self.wait(c,r.json()['job_id'])['state'],'completed')
            b=c.get('/api/intake/uploads/'+key).json();self.assertEqual(b['state'],'partial_ready');self.assertEqual(b['accepted_count'],1);self.assertEqual(b['rejected_count'],3)
            self.assertIsNone(db.get('datasets',key))
            new=c.post('/api/intake/categories',json={'name':'Fixture category','description':'Test target'}).json()
            self.assertEqual(c.patch('/api/intake/uploads/'+key+'/target',json={'category_id':new['id']}).status_code,200)
            r=c.post('/api/intake/uploads/'+key+'/populate');self.assertEqual(r.status_code,202,r.text);self.assertEqual(self.wait(c,r.json()['job_id'])['state'],'completed')
            d=db.get('datasets',key);self.assertEqual(d['valid_count'],1);self.assertEqual(d['category_id'],new['id'])
            self.assertEqual(c.post('/api/intake/uploads/'+key+'/populate').status_code,409)
            reroute=c.post('/api/nodes/routing/run',json={'payload':{'batch_id':key}}).json()
            self.assertEqual(self.wait(c,reroute['id'])['state'],'failed')
            self.assertEqual(db.get('batches',key)['state'],'populated')
            records=c.get('/api/intake/datasets/'+key+'/records').json();self.assertEqual(records['total'],1)
            removed=c.post('/api/intake/datasets/'+key+'/remove-records',json={'expected_revision':records['revision'],'indices':[0]});self.assertEqual(removed.status_code,200,removed.text)
            self.assertEqual(db.get('datasets',key)['valid_count'],0)
            self.assertEqual(c.post('/api/intake/trash/'+removed.json()['trash_id']+'/restore').status_code,200);self.assertEqual(db.get('datasets',key)['valid_count'],1)
            removed=c.delete('/api/intake/datasets/'+key);self.assertEqual(removed.status_code,200);self.assertIsNone(db.get('datasets',key))
            self.assertEqual(c.post('/api/intake/trash/'+removed.json()['trash_id']+'/restore').status_code,200);self.assertEqual(db.get('datasets',key)['valid_count'],1)
    def test_wrong_type_blocks_population(self):
        with TestClient(app) as c:
            category=c.get('/api/intake/state').json()['categories'][0]
            r=c.post('/api/intake/uploads',files={'file':('wrong.json',b'{"v":7}','application/json')},data={'reference':'Wrong box fixture','element_type':'geojson','category_id':category['id']})
            key=r.json()['batch_id'];self.assertEqual(self.wait(c,r.json()['job_id'])['state'],'completed')
            b=c.get('/api/intake/uploads/'+key).json();self.assertEqual(b['state'],'blocked');self.assertEqual(b['failure_node'],'type_check')
            self.assertEqual(c.post('/api/intake/uploads/'+key+'/populate').status_code,409)
            reroute=c.post('/api/nodes/routing/run',json={'payload':{'batch_id':key}}).json()
            self.assertEqual(self.wait(c,reroute['id'])['state'],'completed')
            self.assertEqual(db.get('batches',key)['state'],'blocked');self.assertIsNone(db.get('datasets',key))
    def test_stale_record_removal_is_blocked(self):
        with TestClient(app) as c:
            r=c.post('/api/datasets',files={'file':('rows.json',b'[{"v":1},{"v":2}]','application/json')},data={'name':'Concurrency fixture'})
            d=r.json()['dataset'];payload={'expected_revision':d['revision'],'indices':[0]}
            self.assertEqual(c.post('/api/intake/datasets/'+d['id']+'/remove-records',json=payload).status_code,200)
            self.assertEqual(c.post('/api/intake/datasets/'+d['id']+'/remove-records',json=payload).status_code,409)
