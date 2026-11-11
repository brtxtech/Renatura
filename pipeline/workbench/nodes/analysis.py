from ..calculation import calculate
from .. import db

def run(payload,ctx):
    ctx.check()
    config=db.get('config','active') or {'rules':[]}
    if payload.get('location'):config={**config,'location':payload['location']}
    payload['territorial_analysis']=calculate(config)
    payload['evidence']=[{'id':d['id'],'name':d['name'],'category':d['category'],'valid_count':d['valid_count'],'collection_state':d['collection_state']} for d in db.all_docs('datasets')]
    ctx.log(f"Spatial indicators evaluated: {payload['territorial_analysis']['state']}")
    return payload
