import urllib.request,urllib.parse,json,concurrent.futures,pathlib
p=pathlib.Path(__file__).resolve().parent
queries={'roads':'way[highway~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link)$"]','rail':'way[railway~"^(rail|light_rail|tram|subway)$"]','stops':'node[railway~"^(station|halt|tram_stop)$"];node[highway=bus_stop];node[amenity=ferry_terminal]'}
def get(k,sel):
 bbox='(48.1,-2.0,50.2,1.9)';parts=';'.join(v+bbox for v in sel.split(';'));q='[out:json][timeout:90];('+parts+';);out body geom;'
 req=urllib.request.Request('https://overpass-api.de/api/interpreter',data=urllib.parse.urlencode({'data':q}).encode(),headers={'User-Agent':'RenaturaNormandie/1.0 (map context; public OSM data)'})
 with urllib.request.urlopen(req,timeout=115) as r:d=json.load(r)
 assert 'remark' not in d,d.get('remark');(p/(k+'.json')).write_text(json.dumps(d));print(k,len(d['elements']),flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
 for x in ex.map(lambda kv:get(*kv),queries.items()):pass
def communes(dep):
 url='https://geo.api.gouv.fr/departements/'+dep+'/communes?fields=nom,code,population,centre&format=geojson&geometry=centre'
 with urllib.request.urlopen(url,timeout=45) as r:return json.load(r)['features']
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:features=sum(ex.map(communes,['14','27','50','61','76']),[])
(p/'communes.geojson').write_text(json.dumps({'type':'FeatureCollection','features':features}));print('communes',len(features),flush=True)
