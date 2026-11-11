import numpy as np
import pandas as pd
import pytest
from pipeline.renatura_ai.training import validate, make_training_table, split_spatial_temporal
CFG={'cell_id':'cell_id','year':'observation_year','models':{
'human_pressure':{'features':['built_fraction','road_density_km_km2'],'target':'observed_human_pressure'},
'eco_vulnerability':{'features':['forest_fraction'],'target':'observed_ecological_impact'},
 'territory_forecast':{'features':['built_fraction'],'target':'built_fraction','horizon_years':1}}}

def test_missing_ground_truth_rejected():
 df=pd.DataFrame({'cell_id':['a'], 'observation_year':[2020], 'built_fraction':[.2], 'road_density_km_km2':[1.]})
 with pytest.raises(ValueError,match='Independent observed target'):
  make_training_table(df,CFG,'human_pressure')

def test_missing_features_not_zero():
 df=pd.DataFrame({'cell_id':['a'], 'observation_year':[2020], 'built_fraction':[np.nan], 'road_density_km_km2':[np.nan], 'observed_human_pressure':[.1]})
 with pytest.raises(ValueError,match='No real feature observations'):
  make_training_table(df,CFG,'human_pressure')

def test_forecast_pairs_exact_year():
 df=pd.DataFrame({'cell_id':['a','a','b','b'],'observation_year':[2020,2021,2020,2022], 'built_fraction':[.2,.3,.4,.6]})
 pairs,_=make_training_table(df,CFG,'territory_forecast')
 assert len(pairs)==1 and pairs['_label'].iloc[0]==.3

def test_spatial_temporal_holdout_disjoint():
 df=pd.DataFrame([{'cell_id':f'cell{i}','observation_year':year,'built_fraction':i/100.,'_label':i/100.} for year in [2019,2020] for i in range(100)])
 train,test,_=split_spatial_temporal(df,CFG)
 assert set(train.cell_id).isdisjoint(test.cell_id)
 assert set(train.observation_year)=={2019}
 assert set(test.observation_year)=={2020}
