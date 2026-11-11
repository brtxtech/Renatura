from typing import Literal, Any
from pydantic import BaseModel, Field, FiniteFloat, model_validator
class Location(BaseModel):
    lat:float=Field(ge=48,le=51)
    lon:float=Field(ge=-3,le=3)
class Rule(BaseModel):
    name:str=Field(min_length=1,max_length=160)
    dataset_id:str
    field:str
    min:FiniteFloat
    max:FiniteFloat
    weight:float=Field(default=1,ge=0,le=1000)
    direction:Literal['higher','lower']='higher'
    enabled:bool=True
    @model_validator(mode='after')
    def bounds(self):
        if self.max<=self.min:raise ValueError('max must exceed min')
        return self
class Config(BaseModel):
    location:Location|None=None
    radius_m:float=Field(default=500,ge=1,le=50000)
    minimum_coverage:float=Field(default=.6,ge=0,le=1)
    rules:list[Rule]=Field(default_factory=list,max_length=100)
class ChatInput(BaseModel):
    context:str=Field(default='',max_length=12000)
    image_id:str|None=None
    location:Location|None=None
    label:str=Field(default='Unidentified species',max_length=160)
class NodeInput(BaseModel):
    payload:dict[str,Any]=Field(default_factory=dict)
class LabelInput(BaseModel):
    label:str=Field(min_length=1,max_length=160)
