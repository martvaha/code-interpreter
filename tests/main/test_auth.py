import pytest

from app.shared.config import get_settings
from app.utils.generate_id import generate_id

API_KEY = "test-secret-key"


@pytest.fixture
def auth_enabled():
    """Enable API key auth on the cached settings instance for the duration of a test."""
    settings = get_settings()
    original = settings.API_KEY
    settings.API_KEY = API_KEY
    yield
    settings.API_KEY = original


def test_no_key_configured_allows_requests(client):
    """When API_KEY is unset, requests without a header succeed."""
    assert get_settings().API_KEY is None
    response = client.get(f"/v1/files/{generate_id()}")
    assert response.status_code == 200


def test_missing_header_rejected(client, auth_enabled):
    response = client.get(f"/v1/files/{generate_id()}")
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_wrong_key_rejected(client, auth_enabled):
    response = client.get(f"/v1/files/{generate_id()}", headers={"x-api-key": "wrong-key"})
    assert response.status_code == 401


def test_correct_key_accepted(client, auth_enabled):
    response = client.get(f"/v1/files/{generate_id()}", headers={"x-api-key": API_KEY})
    assert response.status_code == 200


def test_librechat_401_uses_librechat_error_format(client, auth_enabled):
    response = client.get(f"/v1/librechat/files/{generate_id()}")
    assert response.status_code == 401
    assert response.json() == {"message": "Unauthorized"}


def test_librechat_correct_key_accepted(client, auth_enabled):
    response = client.get(f"/v1/librechat/files/{generate_id()}", headers={"x-api-key": API_KEY})
    assert response.status_code == 200


def test_health_endpoint_unauthenticated(client, auth_enabled):
    response = client.get("/health")
    assert response.status_code == 200
