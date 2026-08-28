"""Tests for opt-in bearer-token auth and the loopback-only bind default.

Auth engages only when GRIDSCOPE_API_TOKEN is set; unset keeps every
endpoint open (the loopback bind is the boundary). The middleware reads the
token per request, so tests toggle it with monkeypatch. 401 checks use the
sensitive endpoints (script execution, chat) — the middleware rejects
before routing, so no twin or OpenAI key is needed.
"""

import pytest
from fastapi.testclient import TestClient

import run
from app.auth import TOKEN_ENV_VAR
from app.main import app

TOKEN = "test-secret-token"


@pytest.fixture()
def client():
    return TestClient(app)


class TestTokenUnset:
    @pytest.fixture(autouse=True)
    def no_token(self, monkeypatch):
        monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)

    def test_root_open(self, client):
        assert client.get("/").status_code == 200

    def test_health_open(self, client):
        assert client.get("/health").status_code == 200

    def test_execute_status_open(self, client):
        assert client.get("/api/execute/status").status_code == 200


class TestTokenSet:
    @pytest.fixture(autouse=True)
    def set_token(self, monkeypatch):
        monkeypatch.setenv(TOKEN_ENV_VAR, TOKEN)

    # --- rejected requests -------------------------------------------------
    def test_missing_header_is_401(self, client):
        response = client.get("/")
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert "API token" in response.json()["detail"]

    def test_wrong_token_is_401(self, client):
        response = client.get("/", headers={"Authorization": "Bearer nope"})
        assert response.status_code == 401

    def test_wrong_scheme_is_401(self, client):
        response = client.get("/", headers={"Authorization": f"Token {TOKEN}"})
        assert response.status_code == 401

    def test_empty_bearer_is_401(self, client):
        response = client.get("/", headers={"Authorization": "Bearer "})
        assert response.status_code == 401

    def test_script_execution_requires_token(self, client):
        # The arbitrary-code endpoint must be gated; rejection happens in
        # middleware, before the body is even validated.
        response = client.post("/api/execute/run", json={"code": "print(1)"})
        assert response.status_code == 401

    def test_chat_requires_token(self, client):
        response = client.post("/api/chat", json={"message": "hi"})
        assert response.status_code == 401

    def test_docs_require_token(self, client):
        assert client.get("/docs").status_code == 401
        assert client.get("/openapi.json").status_code == 401

    # --- accepted requests -------------------------------------------------
    def test_correct_token_is_accepted(self, client):
        headers = {"Authorization": f"Bearer {TOKEN}"}
        assert client.get("/", headers=headers).status_code == 200
        assert client.get("/health", headers=headers).status_code == 200
        assert client.get("/api/execute/status", headers=headers).status_code == 200

    def test_scheme_is_case_insensitive(self, client):
        response = client.get("/", headers={"Authorization": f"bearer {TOKEN}"})
        assert response.status_code == 200

    def test_cors_preflight_bypasses_auth(self, client):
        # Browsers send preflights without Authorization headers; CORS must
        # answer them (it is mounted outside the auth middleware).
        response = client.options(
            "/api/chat",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert (
            response.headers["access-control-allow-origin"]
            == "http://localhost:5173"
        )


class TestBindDefaults:
    def test_default_is_loopback(self, monkeypatch):
        monkeypatch.delenv("HOST", raising=False)
        monkeypatch.delenv("PORT", raising=False)
        assert run.resolve_host_port() == ("127.0.0.1", 8000)

    def test_explicit_override_is_respected(self, monkeypatch):
        monkeypatch.setenv("HOST", "0.0.0.0")
        monkeypatch.setenv("PORT", "9000")
        assert run.resolve_host_port() == ("0.0.0.0", 9000)
