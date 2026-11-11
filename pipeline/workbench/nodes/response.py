def run(payload,ctx):
    ctx.check()
    if not payload.get('model_text'):
        a=payload.get('territorial_analysis',{});classification=payload.get('classification',{})
        candidate=classification.get('prediction')
        prediction=(f"Classifier candidate: {candidate['label']} (unverified). " if candidate else 'Species has not been identified. ')
        score=a.get('score');state=f"Exploratory indicator: {score}/100." if score is not None else 'Exploratory indicator cannot be calculated with the available evidence.'
        payload['model_text']=prediction+state+f" Weighted data coverage: {a.get('coverage',0)*100:.0f}%. "+'Partial or missing datasets cannot establish absence. The record is saved for human review.'
    ctx.log('Response prepared; human review status preserved')
    return payload
