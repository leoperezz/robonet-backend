"""
Tests unitarios de los routers de sesiones y uploads.
Todos los servicios externos (Firebase, R2) están mockeados.
"""

from unittest.mock import MagicMock, patch


FAKE_USER = {"uid": "user-123", "email": "test@example.com"}
FAKE_TOKEN = "fake-token"


def _auth_headers():
    return {"Authorization": f"Bearer {FAKE_TOKEN}"}


def _mock_session(session_id: str = "sess-abc") -> dict:
    from datetime import datetime, timezone

    return {
        "sessionId": session_id,
        "userId": FAKE_USER["uid"],
        "status": "recording",
        "startedAt": datetime.now(tz=timezone.utc),
        "endedAt": None,
        "videoKey": f"sessions/{session_id}/video/final.mp4",
        "imuKey": f"sessions/{session_id}/imu/final.ndjson",
        "videoUpload": {"uploadId": "vid-upload-id", "completedParts": []},
        "imuUpload": {"uploadId": "imu-upload-id", "completedParts": []},
        "deviceInfo": {},
        "summary": {},
    }


@patch("app.routers.sessions.create_multipart_upload", return_value="upload-id-123")
@patch("app.services.firebase.verify_token", return_value=FAKE_USER)
def test_create_session(mock_verify, mock_r2, client):
    mock_db = MagicMock()
    with patch("app.routers.sessions.get_db", return_value=mock_db):
        response = client.post("/sessions", headers=_auth_headers(), json={})
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "recording"
    assert data["userId"] == FAKE_USER["uid"]
    assert "sessionId" in data


@patch("app.services.firebase.verify_token", return_value=FAKE_USER)
def test_get_session_not_found(mock_verify, client):
    mock_db = MagicMock()
    mock_doc = MagicMock()
    mock_doc.exists = False
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc
    with patch("app.routers.sessions.get_db", return_value=mock_db):
        response = client.get("/sessions/nonexistent", headers=_auth_headers())
    assert response.status_code == 404


@patch("app.services.firebase.verify_token", return_value=FAKE_USER)
def test_presign_chunk(mock_verify, client):
    session = _mock_session()
    mock_db = MagicMock()
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = session
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    with patch("app.routers.uploads.get_db", return_value=mock_db), patch(
        "app.routers.uploads.generate_presigned_part_url",
        return_value="https://r2.example.com/presigned",
    ):
        response = client.post(
            f"/sessions/{session['sessionId']}/chunks/presign",
            headers=_auth_headers(),
            json={"partNumber": 1},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["partNumber"] == 1
    assert "videoPresignedUrl" in data
    assert "imuPresignedUrl" in data
