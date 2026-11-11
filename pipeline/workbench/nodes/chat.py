from datetime import datetime,timezone

def run(payload,ctx):
    ctx.check();ctx.log('Receiving field observation')
    return {**payload,'received_at':datetime.now(timezone.utc).isoformat(),'review_status':'unverified'}
