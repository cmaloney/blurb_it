from __future__ import annotations

import base64
import pathlib
import ssl
from unittest import mock

import aiohttp
import aiohttp_jinja2
import jinja2
import pytest
from aiohttp import web
from aiohttp_session import setup as setup_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from cryptography import fernet
from pydantic import ValidationError

from blurb_it import __main__


def create_app() -> web.Application:
    fernet_key = fernet.Fernet.generate_key()
    secret_key = base64.urlsafe_b64decode(fernet_key)

    app = web.Application(
        middlewares=[
            __main__.middleware.error_middleware,
            __main__.session_middleware(EncryptedCookieStorage(secret_key)),
        ]
    )

    aiohttp_jinja2.setup(
        app, loader=jinja2.FileSystemLoader(pathlib.Path.cwd() / "templates")
    )
    app[__main__.SETTINGS] = __main__.Settings()
    return app


async def test_handle_get(aiohttp_client) -> None:
    # Arrange
    app = create_app()

    # Act
    app.router.add_get("/", __main__.handle_get)
    client = await aiohttp_client(app)
    resp = await client.get("/")

    # Assert
    assert resp.status == 200
    text = await resp.text()
    assert "<title>📜🤖 Blurb It!</title>" in text
    assert "Sign in with GitHub" in text


async def test_handle_howto_get(aiohttp_client) -> None:
    # Arrange
    app = create_app()

    # Act
    app.router.add_get("/howto", __main__.handle_howto_get)
    client = await aiohttp_client(app)
    resp = await client.get("/howto")

    # Assert
    assert resp.status == 200
    text = await resp.text()
    assert "<title>📜🤖 Blurb It!</title>" in text
    assert "As part of CPython’s workflow" in text


async def test_handle_install(aiohttp_client) -> None:
    # Arrange
    app = create_app()

    # Act
    app.router.add_get("/install", __main__.handle_install)
    client = await aiohttp_client(app)
    resp = await client.get("/install")

    # Assert
    assert resp.status == 200
    text = await resp.text()
    assert "<title>📜🤖 Blurb It!</title>" in text
    assert "Please install" in text


async def test_certificate_error_shows_fix_instructions(aiohttp_client) -> None:
    # Arrange
    async def handler(request: web.Request) -> web.Response:
        raise aiohttp.ClientConnectorCertificateError(
            mock.Mock(), ssl.SSLCertVerificationError("certificate verify failed")
        )

    app = create_app()
    app.router.add_get("/", handler)
    client = await aiohttp_client(app)

    # Act
    resp = await client.get("/")

    # Assert
    text = await resp.text()
    assert "Install Certificates.command" in text


def test_localdev_settings_reads_env_file_and_secrets(tmp_path, monkeypatch) -> None:
    # Arrange
    monkeypatch.chdir(tmp_path)
    for name in ("GH_APP_ID", "GH_PRIVATE_KEY", "APP_PROTOCOL", "PORT"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "ENV" / "secrets").mkdir(parents=True)
    (tmp_path / "ENV" / "localdev.env").write_text(
        "GH_APP_ID=12345\nAPP_PROTOCOL=http\nPORT=8080\n"
    )
    (tmp_path / "ENV" / "secrets" / "gh_private_key").write_text("PEM DATA\n")
    monkeypatch.setenv("PORT", "9000")

    # Act
    settings = __main__._localdev_settings()

    # Assert
    assert settings.gh_app_id == "12345"
    assert settings.app_protocol == "http"
    assert settings.gh_private_key == "PEM DATA"
    assert settings.port == 9000  # environment variables override the file


def test_localdev_settings_rejects_unknown_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ENV" / "secrets").mkdir(parents=True)
    (tmp_path / "ENV" / "localdev.env").write_text("GH_APP_IDD=typo\n")

    with pytest.raises(ValidationError, match="gh_app_idd"):
        __main__._localdev_settings()


def test_localdev_settings_requires_env_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit, match="ENV/localdev.env not found"):
        __main__._localdev_settings()


def test_settings_app_context() -> None:
    settings = __main__.Settings(
        gh_client_id="test_client_id", app_url="localhost:8080", app_protocol="http"
    )
    assert settings.app_context() == {
        "client_id": "test_client_id",
        "app_base_url": "http://localhost:8080",
    }


def test_settings_app_context_defaults_to_https(monkeypatch) -> None:
    monkeypatch.setenv("APP_URL", "example.com")
    monkeypatch.delenv("APP_PROTOCOL", raising=False)
    ctx = __main__.Settings().app_context()
    assert ctx["app_base_url"] == "https://example.com"


@pytest.mark.parametrize(
    "token_str, expected",
    [
        (
            "access_token=gho_16C7e42F292c6912E7710c838347Ae178B4a&scope=repo%2Cgist&token_type=bearer",
            "gho_16C7e42F292c6912E7710c838347Ae178B4a",
        ),
        ("scope=repo%2Cgist&token_type=bearer", None),
    ],
)
def test_get_access_token(token_str: str, expected: str | None) -> None:
    assert __main__.get_access_token(token_str) == expected
