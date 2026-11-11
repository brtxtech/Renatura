"""Exploratory weighted index. No ecological or regulatory validity is claimed."""
import math
from shapely.geometry import shape, Point
from shapely.ops import transform
from pyproj import Transformer
from . import db
TO_METRES=Transformer.from_crs('EPSG:4326','EPSG:2154',always_xy=True).transform

def calculate(config, uploads=None):
    uploads=uploads if uploads is not None else db.all_docs('datasets')
    by_id={u['id']:u for u in uploads}
    loc=config.get('location');radius=config.get('radius_m',500)
    area=transform(TO_METRES,Point(loc['lon'],loc['lat'])).buffer(radius) if loc else None
    details=[]; weighted=0.;available_weight=0.;total_weight=0.
    for rule in config.get('rules',[]):
        weight=rule.get('weight',1)
        if not rule.get('enabled',True) or weight<=0:continue
        total_weight+=weight
        ds=by_id.get(rule.get('dataset_id'));values=[]; intersects=0
        reason=None
        if ds and ds.get('kind')=='geojson' and area is None:reason='Set an analysis location before using spatial features'
        elif ds:
            for row in ds.get('data',{}).get('features',[]) if ds.get('kind')=='geojson' else ds.get('data',[]):
                if ds.get('kind')=='geojson':
                    geom=transform(TO_METRES,shape(row['geometry']))
                    if not geom.intersects(area):continue
                    intersects+=1;props=row['properties']
                else:props=row
                v=props.get(rule.get('field'))
                if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v):values.append(v)
        if not ds:reason='Dataset not imported'
        if ds and not values and not reason:reason='No valid numeric values in the selected area' if area else 'No valid numeric values'
        if rule.get('max',1)<=rule.get('min',0):reason='Normalization maximum must exceed minimum'
        score=None;mean=None
        if not reason:
            mean=sum(values)/len(values)
            score=max(0.,min(1.,(mean-rule.get('min',0))/(rule.get('max',1)-rule.get('min',0))))
            if rule.get('direction')=='lower':score=1-score
            weighted+=weight*score;available_weight+=weight
        details.append({'name':rule.get('name','Indicator'),'dataset_id':rule.get('dataset_id'),'field':rule.get('field'),'value':mean,'score':None if score is None else round(score*100,2),'weight':weight,'sample_size':len(values),'intersections':intersects,'reason':reason,'collection_state':ds.get('collection_state') if ds else 'not_imported','source_id':ds.get('catalog_id') if ds else None,'revision':ds.get('revision') if ds else None})
    coverage=available_weight/total_weight if total_weight else 0
    eligible=available_weight>0 and coverage>=config.get('minimum_coverage',.6)
    return {'score':round(100*weighted/available_weight,2) if eligible else None,'coverage':round(coverage,4),'available_weight':available_weight,'total_weight':total_weight,'state':'calculable' if eligible else 'insufficient_data','details':details,'method':'Weighted mean of available normalized numeric indicators. Missing indicators excluded; minimum coverage enforced.','limitations':['Exploratory index; rules require domain validation.','Partial datasets never prove absence.','A spatial intersection is not a species presence or ecological impact determination.','Point buffers use Lambert-93; this implementation targets mainland Normandie.'],'config':config}
