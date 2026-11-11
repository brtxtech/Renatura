"""Minimal inference API for loaded, trusted Renatura-trained artifacts."""
from pathlib import Path
import os
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from .training import predict

app=FastAPI(title='Renatura Environmental ML API',version='0.1.0')
ARTIFACT_DIR=Path(os.getenv('RENATURA_ARTIFACT_DIR','artifacts'))
MODELS={'human_pressure','eco_vulnerability','territory_forecast'}
class PredictRequest(BaseModel):
    rows:list[dict[str,float|int|None]]=Field(min_length=1,max_length=1000)
@app.get('/health')
def health():
    return {'status':'ok','available_models':[m for m in sorted(MODELS) if (ARTIFACT_DIR/f'{m}.joblib').exists()]}
@app.post('/predict/{model}')
def inference(model:str,request:PredictRequest):
    if model not in MODELS: raise HTTPException(404,'Unknown model')
    path=ARTIFACT_DIR/f'{model}.joblib'
    if not path.exists(): raise HTTPException(503,'Model not trained / unavailable')
    try:
        predictions=predict(path,pd.DataFrame(request.rows))
        return {'model':model,'status':'exploratory','predictions':[None if pd.isna(x) else float(x) for x in predictions]}
    except ValueError as e: raise HTTPException(422,str(e)) from e
