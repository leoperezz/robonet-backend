"""
Fixtures compartidas para todos los tests.

Usa mocks de Firebase y R2 para no necesitar credenciales reales al correr pytest.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def mock_firebase_init():
    """Evita que init_firebase() intente conectarse a Firebase real en tests."""
    with patch("app.services.firebase.firebase_admin") as mock_admin:
        mock_admin._apps = {}
        mock_admin.initialize_app = MagicMock()
        with patch("app.services.firebase.firestore") as mock_fs:
            mock_fs.client.return_value = MagicMock()
            yield


@pytest.fixture()
def client():
    """Cliente HTTP de prueba. Firebase ya está mockeado por autouse fixture."""
    from app.main import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
