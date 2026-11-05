"""A reproducible structural connectivity model, not species movement evidence."""
from __future__ import annotations

import itertools
import math
import networkx as nx
from shapely.geometry import LineString, mapping


def build_graph(cells, habitat_threshold=60):
    """Neighbour cells are connected with positive density-derived resistance.

    High-woodland cells form habitat cores. This is an explicitly assumed
    structural model; no dispersal distances or habitat quality are observed.
    """
    graph = nx.Graph()
    by_id = {row['id']: row for row in cells}
    for row in cells:
        graph.add_node(row['id'], habitat=row['V'] >= habitat_threshold,
                       area=row['woodland_ha'], center=row['center'])
    for a, b in itertools.combinations(cells, 2):
        # Neighbours are identified by shared boundaries, not point distances.
        if a['geometry'].distance(b['geometry']) > 0.01:
            continue
        distance = math.dist(a['center'], b['center'])
        quality = (a['V'] + b['V']) / 200
        resistance = distance * (1 + 4 * (1 - quality))
        graph.add_edge(a['id'], b['id'], weight=max(1, resistance))
    habitat_nodes = [node for node, data in graph.nodes(data=True) if data['habitat']]
    patches = list(nx.connected_components(graph.subgraph(habitat_nodes)))
    patches.sort(key=lambda p: (-sum(by_id[n]['woodland_ha'] for n in p), sorted(p)))
    centrality = nx.betweenness_centrality(graph, weight='weight', normalized=True)
    paths = []
    # At most twelve patches keep the documented model small and reproducible.
    for index, (left, right) in enumerate(itertools.combinations(patches[:12], 2)):
        best = None
        for a in sorted(left):
            lengths, routes = nx.single_source_dijkstra(graph, a, weight='weight')
            for b in sorted(right):
                if b in lengths and (best is None or lengths[b] < best[0]):
                    best = (lengths[b], routes[b])
        if best is None:
            continue
        distance, route = best
        required = [node for node in route if node not in left and node not in right]
        if not required:
            continue
        left_area = sum(by_id[n]['woodland_ha'] for n in left)
        right_area = sum(by_id[n]['woodland_ha'] for n in right)
        # Geometric mean favours reconnection of two substantial patches.
        gain = math.sqrt(left_area * right_area)
        paths.append({'id': f'connection-{index + 1:03}', 'sites': required,
                      'route': route, 'gain': gain, 'resistance': distance,
                      'left_area': left_area, 'right_area': right_area})
    highest = max((p['gain'] for p in paths), default=1)
    for path in paths:
        path['gain'] = 100 * path['gain'] / highest
    return graph, patches, centrality, paths


def realised_connections(selected, paths):
    chosen = set(selected)
    return [path for path in paths if set(path['sites']).issubset(chosen)]


def connection_total(selected, paths):
    return sum(p['gain'] for p in realised_connections(selected, paths))


def evaluate_graph(graph, selected, paths):
    """Report route completion and resistance reduction separately."""
    restored = graph.copy()
    chosen = set(selected)
    for a, b, edge in restored.edges(data=True):
        if a in chosen or b in chosen:
            edge['weight'] *= 0.5
    completed = realised_connections(chosen, paths)
    changes = []
    for path in paths:
        start, end = path['route'][0], path['route'][-1]
        before = nx.shortest_path_length(graph, start, end, weight='weight')
        after = nx.shortest_path_length(restored, start, end, weight='weight')
        changes.append({'connection': path['id'], 'before': before, 'after': after})
    return {'completed_connections': len(completed),
            'connectivity_index': connection_total(chosen, paths),
            'resistance_changes': changes,
            'assumption': 'Selected cells halve incident-edge resistance; uncalibrated.'}
