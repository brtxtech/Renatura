import sys,pathlib,unittest,json,tempfile,contextlib,io
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'tools/normandie'))
from regional_model.connectivity import analyse,connection_total
from regional_model.optimisation import solve
from regional_model.sensitivity import monte_carlo
from complete_region import complete

def collection(unknown=False):
 features=[]
 for i,v in enumerate([80,20,20,20,80]):
  x=i*.01;features.append({'type':'Feature','properties':{'id':str(i),'V':None if unknown and i==2 else v,'D':v,'P':v,'O':v,'woodland_ha':100 if v==80 else 1,'area_ha':100,'proxy_cost':100},'geometry':{'type':'Polygon','coordinates':[[[x,49],[x+.01,49],[x+.01,49.01],[x,49.01],[x,49]]]}})
 return {'type':'FeatureCollection','features':features}
class RegionalTests(unittest.TestCase):
 def test_routes_use_real_neighbours(self):
  graph,routes,c=analyse(collection());self.assertEqual(len(graph['edges']),4);self.assertEqual(len(graph['paths']),1);self.assertEqual(graph['paths'][0]['sites'],['1','2','3']);self.assertGreater(c['2'],c['0']);self.assertEqual(len(routes['features']),1)
 def test_unknown_not_a_zero_resistance_bridge(self):
  graph,_,c=analyse(collection(True));self.assertEqual(graph['observed_cells'],4);self.assertEqual(graph['paths'],[]);self.assertNotIn('2',c)
 def test_ilp_requires_every_corridor_cell(self):
  cells=collection();g,_,_=analyse(cells);rows=[f['properties'] for f in cells['features']];r=solve(rows,g['paths'],mode='sites',budget=3,connectivity_weight=3,allow_partial=True,seconds=10);self.assertLessEqual(r['used'],3);self.assertEqual(set(r['selected']),{'1','2','3'});self.assertEqual(r['connectivity_total'],100);self.assertGreaterEqual(r['objective'],r['baseline_objective']);self.assertEqual(connection_total(['1','2'],g['paths']),0)
 def test_sensitivity_with_one_candidate_has_no_false_correlation(self):
  row=collection()['features'][0]['properties'];r=monte_carlo([row],runs=20,allow_partial=True);self.assertEqual(r['mean_top20_jaccard'],1);self.assertIsNone(r['mean_rank_correlation'])
 def test_full_readiness_only_with_four_real_input_scores(self):
  with tempfile.TemporaryDirectory() as temporary:
   d=pathlib.Path(temporary)
   for name,obj in [('cells.geojson',collection()),('summary.json',{}),('regional_config.json',{})]: (d/name).write_text(json.dumps(obj))
   with contextlib.redirect_stdout(io.StringIO()):audit=complete(d,runs=20,seconds=1,strict=True)
   self.assertEqual(audit['status'],'complete_coverage');self.assertEqual(audit['all_four_criteria_cells'],5)
   c=collection();c['features'][0]['properties']['O']=None;(d/'cells.geojson').write_text(json.dumps(c))
   with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(SystemExit) as error:complete(d,runs=20,seconds=1,strict=True)
   self.assertEqual(error.exception.code,2)
if __name__=='__main__':unittest.main()
