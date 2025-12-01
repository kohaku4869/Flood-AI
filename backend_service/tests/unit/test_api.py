import pytest
from backend_service.app import create_app

@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_route_request(client):
    payload = {
        "start_coords": {"lat": 21.0, "lng": 105.8},
        "end_coords": {"lat": 21.1, "lng": 105.9},
        "camera_data": []
    }
    response = client.post('/route_request', json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'success'
    assert data['data']['start'] == payload['start_coords']

def test_route_request_invalid_json(client):
    # Sending non-JSON data without Content-Type application/json results in 415 Unsupported Media Type
    response = client.post('/route_request', data="invalid")
    assert response.status_code == 415


def test_route_request_missing_data(client):
    payload = {
        "start_coords": {"lat": 21.0, "lng": 105.8}
        # Missing end_coords
    }
    response = client.post('/route_request', json=payload)
    assert response.status_code == 400
