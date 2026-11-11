"""Validate data, quarantine invalid rows, and keep full provenance."""
import math
from collections import Counter
from jsonschema import Draft202012Validator
from shapely.geometry import shape, mapping

def finite(value):
    if isinstance(value,float) and not math.isfinite(value): return False
    if isinstance(value,list): return all(finite(v) for v in value)
    if isinstance(value,dict): return all(finite(v) for v in value.values())
    return True

def infer_schema(records):
    keys=set().union(*(r.keys() for r in records)) if records else set()
    def kind(v):
        if v is None:return 'null'
        if isinstance(v,bool):return 'boolean'
        if isinstance(v,int):return 'integer'
        if isinstance(v,float):return 'number'
        if isinstance(v,str):return 'string'
        if isinstance(v,list):return 'array'
        return 'object'
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','type':'object','properties':{k:{'type':sorted({kind(r.get(k)) for r in records})} for k in sorted(keys)},'additionalProperties':True}

def validate(data, schema=None, required=None, stop=None, log=lambda *a:None):
    required=required or []
    geo=isinstance(data,dict) and data.get('type')=='FeatureCollection'
    if geo: rows=data.get('features')
    else: rows=data if isinstance(data,list) else [data]
    if not isinstance(rows,list): raise ValueError('features must be an array')
    if len(rows)>100000: raise ValueError('Maximum 100,000 features per import; split large layers into batches.')
    if schema: Draft202012Validator.check_schema(schema)
    validator=Draft202012Validator(schema) if schema else None
    valid=[]; anomalies=[]; seen=set(); records=[]
    for i,row in enumerate(rows):
        if stop and stop.is_set(): raise InterruptedError('Validation cancelled')
        errors=[]; warnings=[]
        if not isinstance(row,dict): errors.append('Row must be an object'); props={}
        else:
            props=row.get('properties') if geo else row
            if not isinstance(props,dict): errors.append('properties must be an object'); props={}
            if not finite(row): errors.append('Non-finite numeric value')
            if validator:
                errors += [f'{".".join(map(str,e.path)) or "$"}: {e.message}' for e in validator.iter_errors(props)]
            for k,v in props.items():
                if v is None: warnings.append(f'Null value: {k}')
            for k in required:
                if props.get(k) is None or props.get(k)=='': errors.append(f'Required non-null property: {k}')
            if geo:
                if row.get('type')!='Feature': errors.append('Entry must be a GeoJSON Feature')
                try:
                    geom=shape(row.get('geometry'))
                    if geom.is_empty or not geom.is_valid: errors.append('Empty or invalid geometry')
                    if any(not math.isfinite(v) for v in geom.bounds):errors.append('Invalid coordinate')
                    x1,y1,x2,y2=geom.bounds
                    if not(-180<=x1<=x2<=180 and -90<=y1<=y2<=90): errors.append('Coordinates out of WGS84 longitude/latitude bounds; reproject before upload')
                except Exception: errors.append('Unreadable geometry')
            key=str(row.get('id',props.get('id','')))
            if key and key in seen: errors.append('Duplicate feature id: '+key)
            if key:seen.add(key)
        if errors or warnings: anomalies.append({'index':i,'severity':'error' if errors else 'warning','errors':errors,'warnings':warnings})
        if not errors: valid.append(row);records.append(props)
        if i%1000==0:log(f'Validated {i+1}/{len(rows)} records')
    profile={}
    keys=set().union(*(r.keys() for r in records)) if records else set()
    for key in sorted(keys):
        vals=[r.get(key) for r in records]
        nums=[v for v in vals if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)]
        profile[key]={'types':dict(Counter(type(v).__name__ for v in vals)),'missing_or_null':sum(v is None for v in vals),'numeric_count':len(nums),'min':min(nums) if nums else None,'max':max(nums) if nums else None,'mean':sum(nums)/len(nums) if nums else None}
    return {'profile':profile,'data':{'type':'FeatureCollection','features':valid} if geo else valid,'is_geojson':geo,'valid_count':len(valid),'rejected_count':len(rows)-len(valid),'total_count':len(rows),'anomalies':anomalies,'schema':schema or infer_schema(records),'schema_origin':'supplied' if schema else 'inferred — review before enforcement'}
