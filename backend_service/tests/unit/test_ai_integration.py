import pytest
import respx
from httpx import Response
from backend_service.app import create_app
from backend_service.ai_service import AI_SERVICE_URL

@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@respx.mock
def test_route_request_with_flood(client):
    # Mock AI Service response
    respx.post(AI_SERVICE_URL).mock(return_value=Response(200, json={"status": "FLOODED"}))
    
    payload = {
        "start_coords": {"lat": 21.0, "lng": 105.8},
        "end_coords": {"lat": 21.1, "lng": 105.9},
        "camera_data": [
            {"id": "cam_001", "coords": {"lat": 21.05, "lng": 105.85}}
        ]
    }
    
    response = client.post('/route_request', json=payload)
    assert response.status_code == 200
    data = response.get_json()
    
    # Check if flooded_coords contains the camera coords
    assert len(data['data']['flooded_coords']) == 1
    assert data['data']['flooded_coords'][0] == payload['camera_data'][0]['coords']

@respx.mock
def test_route_request_safe(client):
    # Mock AI Service response
    respx.post(AI_SERVICE_URL).mock(return_value=Response(200, json={"status": "SAFE"}))
    
    payload = {
        "start_coords": {"lat": 21.0, "lng": 105.8},
        "end_coords": {"lat": 21.1, "lng": 105.9},
        "camera_data": [
            {"id": "cam_001", "coords": {"lat": 21.05, "lng": 105.85}}
        ]
    }
    
    response = client.post('/route_request', json=payload)
    assert response.status_code == 200
    data = response.get_json()
    
    # Check if flooded_coords is empty
    assert len(data['data']['flooded_coords']) == 0
