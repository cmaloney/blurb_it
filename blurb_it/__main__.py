from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

import aiohttp
import aiohttp_jinja2
import gidgethub
import jinja2
import sentry_sdk
from aiohttp import web
from aiohttp.web_request import Request
from aiohttp.web_response import Response
from aiohttp_session import get_session, session_middleware
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from cryptography import fernet
from gidgethub.aiohttp import GitHubAPI
from gidgethub.apps import get_installation_access_token, get_jwt
from pydantic_settings import BaseSettings, SettingsConfigDict

from blurb_it import error, middleware, util

routes = web.RouteTableDef()


class Settings(BaseSettings):
    """App configuration, read from environment variables (e.g. ``GH_APP_ID``)."""

    model_config = SettingsConfigDict(extra="forbid", frozen=True)

    gh_app_id: str | None = None
    gh_private_key: str | None = None
    gh_client_id: str | None = None
    gh_client_secret: str | None = None
    app_url: str = ""
    app_protocol: str = "https"
    session_secret: str | None = None
    port: int | None = None
    sentry_dsn: str | None = None

    def app_context(self) -> dict:
        """Template context needed by every page (e.g. the sign-in link)."""
        return {
            "client_id": self.gh_client_id,
            "app_base_url": f"{self.app_protocol}://{self.app_url}",
        }


SETTINGS = web.AppKey("settings", Settings)


def get_settings(request: Request) -> Settings:
    return request.app[SETTINGS]


def _make_jwt(settings: Settings) -> str:
    return get_jwt(app_id=settings.gh_app_id, private_key=settings.gh_private_key)


@routes.get("/", name="home")
async def handle_get(request: Request) -> Response:
    """Render a page with a textbox and submit button."""
    # data = request.query_string
    # data2 = await request.rel_url.query['']
    request_session = await get_session(request)
    context = get_settings(request).app_context()
    if request_session.get("username") and request_session.get("token"):
        context["username"] = request_session["username"]
        location = request.app.router["add_blurb"].url_for()
        response = web.HTTPFound(location=location)
    else:
        response = aiohttp_jinja2.render_template(
            "index.html", request, context=context
        )
    return response


@routes.get("/howto", name="howto")
async def handle_howto_get(request: Request) -> Response:
    """Render a page explaining how to use blurb_it"""
    context = get_settings(request).app_context()
    response = aiohttp_jinja2.render_template("howto.html", request, context=context)
    return response


@routes.get("/install", name="install")
async def handle_install(request: Request) -> Response:
    """Render a page, ask user to install blurb_it"""
    # data = request.query_string
    # data2 = await request.rel_url.query['']
    context = get_settings(request).app_context()
    if await util.has_session(request):
        context.update(await util.get_session_context(request, context))

    response = aiohttp_jinja2.render_template("install.html", request, context=context)
    return response


@routes.get("/add_blurb", name="add_blurb")
async def handle_add_blurb_get(request: Request) -> Response:
    """Render a page with a textbox and submit button."""
    settings = get_settings(request)
    token = request.rel_url.query.get("code")
    request_session = await get_session(request)
    context = {"csrf": util.get_csrf_token(session=request_session)}

    if await util.has_session(request):
        context.update(await util.get_session_context(request, context))
        async with aiohttp.ClientSession() as session:

            gh = GitHubAPI(session, context["username"])

            jwt = _make_jwt(settings)
            try:
                await util.get_installation(gh, jwt, context["username"])
            except error.InstallationNotFound:
                return web.HTTPFound(location=request.app.router["install"].url_for())

    elif token is not None:

        async with aiohttp.ClientSession() as session:
            payload = {
                "client_id": settings.gh_client_id,
                "client_secret": settings.gh_client_secret,
                "code": token,
            }
            async with session.post(
                "https://github.com/login/oauth/access_token", data=payload
            ) as response:
                response_text = await response.text()
                access_token = get_access_token(response_text)
                gh = GitHubAPI(session, "blurb-it", oauth_token=access_token)
                response = await gh.getitem("/user")
                login_name = response["login"]
                request_session["username"] = login_name
                request_session["token"] = access_token
                context["username"] = request_session["username"]

                gh = GitHubAPI(session, context["username"])

                jwt = _make_jwt(settings)
                try:
                    await util.get_installation(gh, jwt, context["username"])
                except error.InstallationNotFound:
                    return web.HTTPFound(
                        location=request.app.router["install"].url_for()
                    )

    else:
        return web.HTTPFound(location=request.app.router["home"].url_for())

    response = aiohttp_jinja2.render_template(
        "add_blurb.html", request, context=context
    )
    return response


def get_access_token(token_str: str) -> str | None:
    for token in token_str.split("&"):
        token_split = token.split("=")
        if token_split[0] == "access_token":
            return token_split[1]
    return None


@routes.post("/add_blurb")
async def handle_add_blurb_post(request: Request) -> Response:
    settings = get_settings(request)
    if await util.has_session(request):
        session_context = await util.get_session_context(request)
        request_session = await get_session(request)
        data = await request.post()

        csrf_form = data.get("csrf", "").strip()
        if not util.compare_csrf_tokens(
            csrf_form, util.get_csrf_token(session=request_session)
        ):
            raise web.HTTPForbidden(reason="Invalid CSRF token. Please retry.")

        issue_number = data.get("issue_number", "").strip()
        section = data.get("section", "").strip()
        news_entry = data.get("news_entry", "").strip() + "\n"
        path = await util.get_misc_news_filename(issue_number, section, news_entry)
        pr_number = data.get("pr_number", "").strip()

        context = {}
        context.update(session_context)

        async with aiohttp.ClientSession() as session:
            gh = GitHubAPI(session, session_context["username"])

            jwt = _make_jwt(settings)
            try:
                installation = await util.get_installation(
                    gh, jwt, session_context["username"]
                )
            except error.InstallationNotFound:
                return web.HTTPFound(location=request.app.router["install"].url_for())
            else:
                access_token = await get_installation_access_token(
                    gh,
                    installation_id=installation["id"],
                    app_id=settings.gh_app_id,
                    private_key=settings.gh_private_key,
                )

                gh = GitHubAPI(
                    session,
                    session_context["username"],
                    oauth_token=access_token["token"],
                )
                pr = await gh.getitem(f"/repos/python/cpython/pulls/{pr_number}")
                pr_repo_full_name = pr["head"]["repo"]["full_name"]
                encoded = base64.b64encode(str.encode(news_entry))
                decoded = encoded.decode("utf-8")
                put_data = {
                    "branch": pr["head"]["ref"],
                    "content": decoded,
                    "path": path,
                    "message": "📜🤖 Added by blurb_it.",
                }
                try:
                    response = await gh.put(
                        f"/repos/{pr_repo_full_name}/contents/{path}", data=put_data
                    )
                except gidgethub.BadRequest as bac:
                    print("BadRequest")
                    print(int(bac.status_code))
                    print(bac)
                    context[
                        "pr_url"
                    ] = f"https://github.com/python/cpython/pull/{pr_number}"
                    context["pr_number"] = pr_number
                    context["status"] = "failure"
                else:
                    commit_url = response["commit"]["html_url"]
                    context["commit_url"] = commit_url
                    context["path"] = response["content"]["path"]
                    context[
                        "pr_url"
                    ] = f"https://github.com/python/cpython/pull/{pr_number}"
                    context["pr_number"] = pr_number
                    context["status"] = "success"

        template = "add_blurb.html"
        response = aiohttp_jinja2.render_template(template, request, context=context)
        return response
    else:
        return web.HTTPFound(location=request.app.router["add_blurb"].url_for())


def _build_app(settings: Settings) -> web.Application:
    sentry_sdk.init(settings.sentry_dsn)

    session_secret = settings.session_secret
    if session_secret:
        secret_key = base64.urlsafe_b64decode(session_secret.encode())
    else:
        secret_key = base64.urlsafe_b64decode(fernet.Fernet.generate_key())

    app = web.Application(
        middlewares=[
            middleware.error_middleware,
            session_middleware(EncryptedCookieStorage(secret_key)),
        ]
    )
    aiohttp_jinja2.setup(
        app, loader=jinja2.FileSystemLoader(os.path.join(os.getcwd(), "templates"))
    )
    app[SETTINGS] = settings
    app["static_root_url"] = os.path.join(os.getcwd(), "static")
    app.router.add_routes(routes)
    app.add_routes([web.static("/static", os.path.join(os.getcwd(), "static"))])
    return app


LOCALDEV_ENV_FILE = Path("ENV/localdev.env")
LOCALDEV_SECRETS_DIR = Path("ENV/secrets")


def _localdev_settings() -> Settings:
    if not LOCALDEV_ENV_FILE.is_file():
        sys.exit(f"{LOCALDEV_ENV_FILE} not found; see 'Running locally' in readme.rst.")
    return Settings(_env_file=LOCALDEV_ENV_FILE, _secrets_dir=LOCALDEV_SECRETS_DIR)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="blurb_it web app")
    parser.set_defaults(load_settings=Settings)
    sub = parser.add_subparsers()

    localdev = sub.add_parser(
        "localdev", help=f"Run with {LOCALDEV_ENV_FILE} config for local development"
    )
    localdev.set_defaults(load_settings=_localdev_settings)

    return parser.parse_args()


def main() -> None:  # pragma: no cover
    settings = _parse_args().load_settings()
    web.run_app(_build_app(settings), port=settings.port)


if __name__ == "__main__":  # pragma: no cover
    main()
