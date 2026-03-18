"""Tests básicos del endpoint /health y configuración general."""


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "env" in data


def test_docs_available(client):
    response = client.get("/docs")
    assert response.status_code == 200


def test_openapi_schema(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Robonet Sensor Backend"
    # Verifica que los routers principales están registrados
    paths = schema["paths"]
    assert "/health" in paths
    assert "/sessions" in paths
    assert "/auth/me" in paths
