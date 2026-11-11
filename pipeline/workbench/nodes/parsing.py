from .. import db

def run(payload,ctx):
    ctx.check()
    if payload.get('image_id'):
        image=db.get('images',payload['image_id'])
        if not image: raise ValueError('Unknown image id')
        payload['image']=image
    if not payload.get('context') and not payload.get('image'):
        raise ValueError('An image or context is required')
    ctx.log('Validated observation references and input')
    return payload
