"""Conservative GML 2/3 linear geometry reader. Unsupported curves are rejected, never approximated."""
import re,xml.etree.ElementTree as ET
from pyproj import CRS
GEOMETRIES={'Point','LineString','LinearRing','Polygon','PolygonPatch','Surface','Curve','MultiPoint','MultiLineString','MultiCurve','MultiPolygon','MultiSurface','GeometryCollection','MultiGeometry','CompositeSurface'}
def tag(e):return e.tag.rsplit('}',1)[-1]
def coordinates(e,dimension=2):
 for p in e.iter():
  if tag(p)=='posList':
   dim=int(p.attrib.get('srsDimension',e.attrib.get('srsDimension',dimension)));v=[float(x) for x in (p.text or '').split()]
   if dim not in {2,3} or len(v)%dim:raise ValueError('GML dimension incohérente')
   return [v[i:i+2] for i in range(0,len(v),dim)]
  if tag(p)=='coordinates':return [[float(x) for x in pair.split(',')[:2]] for pair in (p.text or '').split()]
 ps=[p for p in e.iter() if tag(p)=='pos']
 if ps:return [[float(v) for v in p.text.split()[:2]] for p in ps]
 raise ValueError('GML sans coordonnées linéaires')
def children_geoms(e):
 out=[]
 def walk(n):
  for c in n:
   if tag(c) in GEOMETRIES:out.append(c)
   else:walk(c)
 walk(e);return out

def parse(e):
 t=tag(e)
 if t=='Point':return {'type':'Point','coordinates':coordinates(e)[0]}
 if t in {'LineString','LinearRing'}:return {'type':'LineString','coordinates':coordinates(e)}
 if t=='Curve':
  if any(tag(c) in {'Arc','ArcString','Circle','CircleByCenterPoint','BSpline','CubicSpline','GeodesicString'} for c in e.iter()):raise ValueError('Courbe non linéaire non prise en charge')
  segments=[c for c in e.iter() if tag(c)=='LineStringSegment'];out=[]
  if not segments:raise ValueError('Curve sans segment linéaire')
  for s in segments:
   ps=coordinates(s)
   if out and out[-1]!=ps[0]:raise ValueError('Segments disjoints')
   out+=ps[1:] if out else ps
  return {'type':'LineString','coordinates':out}
 if t in {'Polygon','PolygonPatch'}:
  rings=[]
  for names in [{'exterior','outerBoundaryIs'},{'interior','innerBoundaryIs'}]:
   for r in e:
    if tag(r) in names:
     p=coordinates(r)
     if p[0]!=p[-1]:p.append(p[0])
     rings.append(p)
  if not rings:raise ValueError('Polygon sans anneau')
  return {'type':'Polygon','coordinates':rings}
 if t in {'Surface','CompositeSurface'}:
  gs=[parse(g) for g in children_geoms(e)]
  ps=[]
  for g in gs:
   if g['type']=='Polygon':ps.append(g['coordinates'])
   elif g['type']=='MultiPolygon':ps.extend(g['coordinates'])
   else:raise ValueError('Surface non polygonale')
  if not ps:raise ValueError('Surface vide')
  return {'type':'MultiPolygon','coordinates':ps}
 gs=[parse(g) for g in children_geoms(e)]
 if t=='MultiPoint':return {'type':'MultiPoint','coordinates':[g['coordinates'] for g in gs if g['type']=='Point']}
 if t in {'MultiLineString','MultiCurve'}:
  if any(g['type']!='LineString' for g in gs):raise ValueError('MultiCurve non linéaire')
  return {'type':'MultiLineString','coordinates':[g['coordinates'] for g in gs]}
 if t in {'MultiSurface','MultiPolygon'}:
  ps=[]
  for g in gs:
   if g['type']=='Polygon':ps.append(g['coordinates'])
   elif g['type']=='MultiPolygon':ps.extend(g['coordinates'])
   else:raise ValueError('MultiSurface non polygonale')
  return {'type':'MultiPolygon','coordinates':ps}
 if t in {'GeometryCollection','MultiGeometry'}:return {'type':'GeometryCollection','geometries':gs}
 raise ValueError('Type GML non pris en charge : '+t)
CRS_CACHE={}
def read_wrapper(wrapper):
 root=ET.fromstring(wrapper['gml']);g=root if tag(root) in GEOMETRIES else next((c for c in root.iter() if tag(c) in GEOMETRIES),None)
 if g is None:raise ValueError('GML sans géométrie')
 crs=g.attrib.get('srsName') or wrapper.get('srs')
 if not crs:raise ValueError('GML sans projection déclarée')
 result=parse(g);labels=g.attrib.get('axisLabels','').lower().split()
 if labels:swap=labels[0] in {'lat','latitude','north','northing','n'}
 else:
  if crs not in CRS_CACHE:CRS_CACHE[crs]=CRS.from_user_input(crs)
  axis=CRS_CACHE[crs].axis_info;swap=('urn:' in crs.lower() or '/def/crs/' in crs.lower()) and bool(axis and axis[0].direction in {'north','south'})
 if swap:
  def flip(c):
   if c and isinstance(c[0],(int,float)):return [c[1],c[0]]+c[2:]
   return [flip(x) for x in c]
  def apply(g):
   if g['type']=='GeometryCollection':
    for c in g['geometries']:apply(c)
   else:g['coordinates']=flip(g['coordinates'])
  apply(result)
 return result,crs
