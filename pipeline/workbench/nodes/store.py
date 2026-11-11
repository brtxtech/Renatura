from .. import db

def run(payload,ctx):
    ctx.check();db.put('observations',payload['id'],payload)
    ctx.log('Observation, image reference, context and analysis stored in SQLite')
    return payload
