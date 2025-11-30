import pytest
from backend_service.routing_service import get_safe_route, get_graph
import osmnx as ox
import networkx as nx

# Mock graph for testing to avoid network calls
@pytest.fixture
def mock_graph(mocker):
    # Create a simple graph
    # 0 -- 1 -- 2
    # |    |    |
    # 3 -- 4 -- 5
    G = ox.graph_from_bbox(north=21.01, south=21.00, east=105.81, west=105.80, network_type='drive')
    mocker.patch('backend_service.routing_service.get_graph', return_value=G)
    return G

def create_synthetic_graph():
    # Create a simple grid graph
    # Nodes:
    # 0 (0,0) -- 1 (0,1)
    # |          |
    # 2 (1,0) -- 3 (1,1)
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"
    
    # Add nodes with lat/lng (y/x)
    # Let's map 0,0 to 21.0, 105.8
    nodes = {
        0: {"y": 21.00, "x": 105.80},
        1: {"y": 21.00, "x": 105.81},
        2: {"y": 21.01, "x": 105.80},
        3: {"y": 21.01, "x": 105.81}
    }
    for n, data in nodes.items():
        G.add_node(n, **data)
        
    # Add edges with length
    edges = [
        (0, 1, 100), (1, 0, 100),
        (0, 2, 100), (2, 0, 100),
        (1, 3, 100), (3, 1, 100),
        (2, 3, 100), (3, 2, 100)
    ]
    for u, v, length in edges:
        G.add_edge(u, v, length=length)
        
    return G

def test_get_safe_route_no_flood(mocker):
    G = create_synthetic_graph()
    mocker.patch('backend_service.routing_service.get_graph', return_value=G)
    
    start = {"lat": 21.00, "lng": 105.80} # Node 0
    end = {"lat": 21.01, "lng": 105.81}   # Node 3
    flooded = []
    
    path = get_safe_route(start, end, flooded)
    assert isinstance(path, list)
    assert len(path) > 0

def test_get_safe_route_with_flood(mocker):
    G = create_synthetic_graph()
    mocker.patch('backend_service.routing_service.get_graph', return_value=G)

    start = {"lat": 21.00, "lng": 105.80} # Node 0
    end = {"lat": 21.01, "lng": 105.81}   # Node 3
    
    # Flood Node 1 (21.00, 105.81)
    # Path should go 0 -> 2 -> 3 instead of 0 -> 1 -> 3
    flooded = [{"lat": 21.00, "lng": 105.81}]
    
    path = get_safe_route(start, end, flooded)
    assert isinstance(path, list)
    assert len(path) > 0
    
    # Check that we didn't go through node 1
    # Node 1 coords: 21.00, 105.81
    for p in path:
        # Allow small float error
        assert not (abs(p['lat'] - 21.00) < 1e-5 and abs(p['lng'] - 105.81) < 1e-5)
