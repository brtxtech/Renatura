import unittest,sys,tempfile,sqlite3,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pipeline/atlas'))
from gml_geometry import read_wrapper
from shapely.geometry import shape,Polygon,Point,mapping
class GMLTests(unittest.TestCase):
 def test_holes_and_lambert_axis(self):
  g,s=read_wrapper({'gml':'<Polygon xmlns="http://www.opengis.net/gml" srsName="urn:ogc:def:crs:EPSG::2154"><exterior><LinearRing><posList>0 0 10 0 10 10 0 10 0 0</posList></LinearRing></exterior><interior><LinearRing><posList>3 3 7 3 7 7 3 7 3 3</posList></LinearRing></interior></Polygon>'});self.assertEqual(shape(g).area,84)
 def test_gml_authoritative_latitude_longitude_order(self):
  g,s=read_wrapper({'gml':'<Point xmlns="http://www.opengis.net/gml" srsName="urn:ogc:def:crs:EPSG::4326"><pos>49.18 -0.37</pos></Point>'});self.assertEqual(g['coordinates'],[-.37,49.18])
 def test_nonlinear_geometry_rejected(self):
  with self.assertRaises(ValueError):read_wrapper({'gml':'<Curve xmlns="http://www.opengis.net/gml" srsName="EPSG:2154"><Arc><posList>1 2 3 4 5 6</posList></Arc></Curve>'})
class AnalysisTests(unittest.TestCase):
 def test_bbox_candidate_inside_hole_is_not_intersection(self):
  # This exercises the actual endpoint, not merely the R-tree bounding boxes.
  from fastapi.testclient import TestClient
  from pipeline.atlas.server import app
  import shapely,json
  from shapely.ops import transform
  from pyproj import Transformer
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'test.sqlite';db=sqlite3.connect(p);db.executescript('CREATE TABLE features(fid INTEGER,layer_id TEXT,geom BLOB);CREATE TABLE layers(id TEXT,meta TEXT);CREATE VIRTUAL TABLE bounds USING rtree(fid,minx,maxx,miny,maxy);')
   g=Polygon([(400000,6900000),(410000,6900000),(410000,6910000),(400000,6910000)],holes=[[(403000,6903000),(407000,6903000),(407000,6907000),(403000,6907000)]])
   db.execute('INSERT INTO features VALUES(1,?,?)',('layer',g.wkb));a,b,c,e=g.bounds;db.execute('INSERT INTO bounds VALUES(?,?,?,?,?)',(1,a,c,b,e));db.execute('INSERT INTO layers VALUES(?,?)',('layer',json.dumps({'name':'Test','status':'PARTIAL','entry_ids':['API-TEST']})));db.commit();db.close()
   old=os.environ.get('RENATURA_SPATIAL_DB');os.environ['RENATURA_SPATIAL_DB']=str(p)
   try:
    to4326=Transformer.from_crs(2154,4326,always_xy=True).transform
    q=Polygon([(404000,6904000),(406000,6904000),(406000,6906000),(404000,6906000)])
    r=TestClient(app).post('/api/analyse',json={'geometry':mapping(transform(to4326,q))});self.assertEqual(r.status_code,200);self.assertEqual(r.json()['layers'],[])
   finally:
    if old is None:os.environ.pop('RENATURA_SPATIAL_DB',None)
    else:os.environ['RENATURA_SPATIAL_DB']=old
