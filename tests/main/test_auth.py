import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.shared.config import get_settings
from app.utils.generate_id import generate_id


def _public_pem(private_key) -> str:
    return (
        private_key.public_key()
        .public_bytes(encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode("utf-8")
    )


@pytest.fixture(scope="session")
def ed25519_key():
    return Ed25519PrivateKey.generate()


@pytest.fixture(scope="session")
def wrong_ed25519_key():
    return Ed25519PrivateKey.generate()


@pytest.fixture(scope="session")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def jwt_auth_enabled(ed25519_key):
    """Enable JWT auth on the cached settings instance for the duration of a test."""
    settings = get_settings()
    original = settings.CODEAPI_JWT_PUBLIC_KEY
    settings.CODEAPI_JWT_PUBLIC_KEY = _public_pem(ed25519_key)
    yield
    settings.CODEAPI_JWT_PUBLIC_KEY = original


@pytest.fixture
def rsa_auth_enabled(rsa_key):
    settings = get_settings()
    original = settings.CODEAPI_JWT_PUBLIC_KEY
    settings.CODEAPI_JWT_PUBLIC_KEY = _public_pem(rsa_key)
    yield
    settings.CODEAPI_JWT_PUBLIC_KEY = original


def mint_token(private_key, alg="EdDSA", kid="lc-codeapi-2026-05", **claim_overrides) -> str:
    """Mint a token shaped like LibreChat's getCodeApiAuthHeaders output."""
    now = int(time.time())
    claims = {
        "iss": "librechat",
        "aud": "codeapi",
        "sub": "test-user-id",
        "iat": now,
        "nbf": now,
        "exp": now + 300,
        "jti": str(uuid.uuid4()),
        "tenant_id": "legacy",
        "role": "USER",
        "principal_source": "librechat_jwt",
    }
    claims.update(claim_overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, private_key, algorithm=alg, headers={"kid": kid})


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_no_key_configured_allows_requests(client):
    """When no public key is configured, requests without a header succeed."""
    assert get_settings().JWT_PUBLIC_KEY_PEM is None
    response = client.get(f"/v1/files/{generate_id()}")
    assert response.status_code == 200


def test_missing_header_rejected(client, jwt_auth_enabled):
    response = client.get(f"/v1/files/{generate_id()}")
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_malformed_token_rejected(client, jwt_auth_enabled):
    response = client.get(f"/v1/files/{generate_id()}", headers=auth_headers("not.a.jwt"))
    assert response.status_code == 401


def test_non_bearer_scheme_rejected(client, jwt_auth_enabled):
    response = client.get(f"/v1/files/{generate_id()}", headers={"Authorization": "Basic abc"})
    assert response.status_code == 401


def test_wrong_signature_rejected(client, jwt_auth_enabled, wrong_ed25519_key):
    token = mint_token(wrong_ed25519_key)
    response = client.get(f"/v1/files/{generate_id()}", headers=auth_headers(token))
    assert response.status_code == 401


def test_expired_token_rejected(client, jwt_auth_enabled, ed25519_key):
    token = mint_token(ed25519_key, exp=int(time.time()) - 120)
    response = client.get(f"/v1/files/{generate_id()}", headers=auth_headers(token))
    assert response.status_code == 401


def test_expired_within_leeway_accepted(client, jwt_auth_enabled, ed25519_key):
    token = mint_token(ed25519_key, exp=int(time.time()) - 5)
    response = client.get(f"/v1/files/{generate_id()}", headers=auth_headers(token))
    assert response.status_code == 200


def test_future_nbf_rejected(client, jwt_auth_enabled, ed25519_key):
    token = mint_token(ed25519_key, nbf=int(time.time()) + 120)
    response = client.get(f"/v1/files/{generate_id()}", headers=auth_headers(token))
    assert response.status_code == 401


def test_wrong_audience_rejected(client, jwt_auth_enabled, ed25519_key):
    token = mint_token(ed25519_key, aud="other-service")
    response = client.get(f"/v1/files/{generate_id()}", headers=auth_headers(token))
    assert response.status_code == 401


def test_wrong_issuer_rejected(client, jwt_auth_enabled, ed25519_key):
    token = mint_token(ed25519_key, iss="someone-else")
    response = client.get(f"/v1/files/{generate_id()}", headers=auth_headers(token))
    assert response.status_code == 401


def test_missing_sub_rejected(client, jwt_auth_enabled, ed25519_key):
    token = mint_token(ed25519_key, sub=None)
    response = client.get(f"/v1/files/{generate_id()}", headers=auth_headers(token))
    assert response.status_code == 401


def test_valid_eddsa_token_accepted(client, jwt_auth_enabled, ed25519_key):
    token = mint_token(ed25519_key)
    response = client.get(f"/v1/files/{generate_id()}", headers=auth_headers(token))
    assert response.status_code == 200


def test_valid_rs256_token_accepted(client, rsa_auth_enabled, rsa_key):
    token = mint_token(rsa_key, alg="RS256")
    response = client.get(f"/v1/files/{generate_id()}", headers=auth_headers(token))
    assert response.status_code == 200


def test_rs256_token_against_ed25519_key_rejected(client, jwt_auth_enabled, rsa_key):
    """No algorithm confusion: an RS256 token must not pass when the server holds an Ed25519 key."""
    token = mint_token(rsa_key, alg="RS256")
    response = client.get(f"/v1/files/{generate_id()}", headers=auth_headers(token))
    assert response.status_code == 401


def test_unknown_kid_tolerated(client, jwt_auth_enabled, ed25519_key):
    """kid is logged but never branched on — a single key is configured server-side."""
    token = mint_token(ed25519_key, kid="some-future-rotation-key")
    response = client.get(f"/v1/files/{generate_id()}", headers=auth_headers(token))
    assert response.status_code == 200


def test_librechat_401_uses_librechat_error_format(client, jwt_auth_enabled):
    response = client.get(f"/v1/librechat/files/{generate_id()}")
    assert response.status_code == 401
    assert response.json() == {"message": "Unauthorized"}


def test_librechat_valid_token_accepted(client, jwt_auth_enabled, ed25519_key):
    token = mint_token(ed25519_key)
    response = client.get(f"/v1/librechat/files/{generate_id()}", headers=auth_headers(token))
    assert response.status_code == 200


def test_health_endpoint_unauthenticated(client, jwt_auth_enabled):
    response = client.get("/health")
    assert response.status_code == 200
