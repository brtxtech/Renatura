"""Graphe spatial indexé : aucune traversée supposée dans une maille V inconnue."""
import itertools,math
import networkx as nx
import geopandas as gpd
from shapely.geometry import LineString,mapping

def connection_total(selected,paths):
 chosen=set(selected);return sum(p['gain'] for p in paths if set(p['sites']).issubset(chosen))

def analyse(collection,threshold=60,samples=128):
 frame=gpd.GeoDataFrame.from_features(collection['features'],crs=4326).to_crs(2154)
 # Taille des réservoirs : habitat_ha (proxy régional surface × V/100) s'il existe, sinon boisement observé du pilote.
 size='habitat_ha' if 'habitat_ha' in frame.columns and frame['habitat_ha'].notna().any() else 'woodland_ha'
 valid=frame[frame.V.notna() & frame[size].notna()].reset_index(drop=True)
 graph=nx.Graph();lookup={};centers={}
 for _,row in valid.iterrows():
  node=row['id'];lookup[node]=row;centers[node]=(row.geometry.centroid.x,row.geometry.centroid.y)
  graph.add_node(node,V=float(row.V),woodland_ha=float(row[size]))
 for i,row in valid.iterrows():
  for j in valid.sindex.query(row.geometry,predicate='intersects'):
   if int(j)<=i:continue
   other=valid.iloc[j]
   # Partage d'un segment, pas seulement d'un sommet.
   if row.geometry.boundary.intersection(other.geometry.boundary).length<.01:continue
   a,b=row['id'],other['id'];distance=math.dist(centers[a],centers[b]);resistance=max(1.,distance*(1+4*(1-(float(row.V)+float(other.V))/200)))
   graph.add_edge(a,b,resistance=resistance,conductance=1/resistance)
 n=graph.number_of_nodes();centrality=nx.betweenness_centrality(graph,k=min(samples,n) if n>samples else None,weight='resistance',seed=42) if n else {}
 cores=[n for n,p in graph.nodes(data=True) if p['V']>=threshold]
 patches=sorted(nx.connected_components(graph.subgraph(cores)),key=lambda c:(-sum(graph.nodes[n]['woodland_ha'] for n in c),sorted(c)))
 paths=[]
 for i,(left,right) in enumerate(itertools.combinations(patches[:12],2)):
  lengths,routes=nx.multi_source_dijkstra(graph,sorted(left),weight='resistance')
  reachable=[n for n in right if n in lengths]
  if not reachable:continue
  end=min(reachable,key=lambda n:(lengths[n],n));route=routes[end];required=[n for n in route if n not in left and n not in right]
  if not required:continue
  la=sum(graph.nodes[n]['woodland_ha'] for n in left);ra=sum(graph.nodes[n]['woodland_ha'] for n in right)
  paths.append({'id':f'regional-connection-{i+1:03d}','sites':required,'route':route,'resistance':lengths[end],'gain_raw':math.sqrt(la*ra),'left_area':la,'right_area':ra})
 peak=max((p['gain_raw'] for p in paths),default=1)
 for p in paths:p['gain']=100*p['gain_raw']/peak if peak else 0
 lines=[]
 for path in paths:
  line=gpd.GeoSeries([LineString([centers[n] for n in path['route']])],crs=2154).to_crs(4326).iloc[0]
  lines.append({'type':'Feature','properties':path,'geometry':mapping(line)})
 result={'paths':paths,'nodes':[{'id':n,**p,'betweenness':centrality[n]} for n,p in graph.nodes(data=True)],'edges':[{'source':a,'target':b,**p} for a,b,p in graph.edges(data=True)],'status':'computed_observed_subset' if n else 'no_observed_structure','observed_cells':n,'total_cells':len(frame),'observed_cell_fraction':n/len(frame) if len(frame) else 0,'patch_count':len(patches),'components':nx.number_connected_components(graph) if n else 0,'centrality_method':{'algorithm':'weighted_betweenness','samples':min(samples,n),'seed':42,'approximate':n>samples},'assumptions':['V >= 60 : réservoir structurel supposé','Au maximum 12 réservoirs par surface boisée','Les cellules sans V ne sont pas des chemins connus','Le gain n’est pas un nombre d’hectares uniques ni une probabilité de déplacement']}
 return result,{'type':'FeatureCollection','features':lines},centrality
