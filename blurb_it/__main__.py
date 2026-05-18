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

from blurb_it import error, middleware, util

routes = web.RouteTableDef()


sentry_sdk.init(os.environ.get("SENTRY_DSN"))


def _make_jwt() -> str:
    return get_jwt(
        app_id=os.getenv("GH_APP_ID"), private_key=os.getenv("GH_PRIVATE_KEY")
    )


@routes.get("/", name="home")
async def handle_get(request: Request) -> Response:
    """Render a page with a textbox and submit button."""
    # data = request.query_string
    # data2 = await request.rel_url.query['']
    request_session = await get_session(request)
    context = util.get_app_context()
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
    context = util.get_app_context()
    response = aiohttp_jinja2.render_template("howto.html", request, context=context)
    return response


@routes.get("/install", name="install")
async def handle_install(request: Request) -> Response:
    """Render a page, ask user to install blurb_it"""
    # data = request.query_string
    # data2 = await request.rel_url.query['']
    context = util.get_app_context()
    if await util.has_session(request):
        context.update(await util.get_session_context(request, context))

    response = aiohttp_jinja2.render_template("install.html", request, context=context)
    return response


@routes.get("/add_blurb", name="add_blurb")
async def handle_add_blurb_get(request: Request) -> Response:
    """Render a page with a textbox and submit button."""
    token = request.rel_url.query.get("code")
    request_session = await get_session(request)
    context = {"csrf": util.get_csrf_token(session=request_session)}

    try:
        if await util.has_session(request):
            context.update(await util.get_session_context(request, context))
            async with aiohttp.ClientSession() as session:

                gh = GitHubAPI(session, context["username"])

                jwt = _make_jwt()
                try:
                    await util.get_installation(gh, jwt, context["username"])
                except error.InstallationNotFound:
                    return web.HTTPFound(location=request.app.router["install"].url_for())

        elif token is not None:

            async with aiohttp.ClientSession() as session:
                payload = {
                    "client_id": os.environ.get("GH_CLIENT_ID"),
                    "client_secret": os.environ.get("GH_CLIENT_SECRET"),
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

                    jwt = _make_jwt()
                    try:
                        await util.get_installation(gh, jwt, context["username"])
                    except error.InstallationNotFound:
                        return web.HTTPFound(
                            location=request.app.router["install"].url_for()
                        )

        else:
            return web.HTTPFound(location=request.app.router["home"].url_for())

    except aiohttp.ClientConnectorCertificateError:
        raise web.HTTPInternalServerError(
            reason=(
                "SSL certificate verification failed when connecting to GitHub. "
                "On macOS with Python from python.org, run: "
                'open "/Applications/Python 3.x/Install Certificates.command" '
                "(replace 3.x with your Python version)."
            )
        )

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

            jwt = _make_jwt()
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
                    app_id=os.getenv("GH_APP_ID"),
                    private_key=os.getenv("GH_PRIVATE_KEY"),
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


def _build_app() -> web.Application:
    session_secret = os.environ.get("SESSION_SECRET")
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
    app["static_root_url"] = os.path.join(os.getcwd(), "static")
    app.router.add_routes(routes)
    app.add_routes([web.static("/static", os.path.join(os.getcwd(), "static"))])
    return app


def _do_run(_args=None) -> None:  # pragma: no cover
    port = os.environ.get("PORT")
    if port is not None:
        port = int(port)
    web.run_app(_build_app(), port=port)


def _load_config_from_toml(config_filename: str) -> None:
    import tomllib

    with open(config_filename, "rb") as f:
        config = tomllib.load(f)

    required = {
        "app_url": None,
        "github_app_id": "GH_APP_ID",
        "github_private_key_path": None,
        "github_client_id": "GH_CLIENT_ID",
        "github_client_secret": "GH_CLIENT_SECRET",
        "port": "PORT",
    }

    have = set(config.keys())
    needed = set(required.keys())
    if needed != have:
        missing = needed - have
        extra = have - needed
        print(f"Invalid config: missing={missing}, extra={extra}", file=sys.stderr)
        sys.exit(1)

    for k, v in required.items():
        if v is not None:
            os.environ[v] = str(config[k])

    key_path = Path(config["github_private_key_path"])
    if not key_path.is_absolute():
        key_path = Path("ENV") / key_path
    os.environ["GH_PRIVATE_KEY"] = key_path.read_text(encoding="ascii")
    os.environ["APP_PROTOCOL"] = "http"
    os.environ["APP_URL"] = f"{config['app_url']}:{config['port']}"

    cookie_key_file = Path("ENV") / "cookie_secret.key"
    if cookie_key_file.exists():
        cookie_fernet_key = cookie_key_file.read_bytes().strip()
    else:
        cookie_fernet_key = fernet.Fernet.generate_key()
        cookie_key_file.write_bytes(cookie_fernet_key)
    os.environ["SESSION_SECRET"] = cookie_fernet_key.decode()


def _do_localdev(args: argparse.Namespace) -> None:  # pragma: no cover
    _load_config_from_toml(args.config_file)
    _do_run()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="blurb_it web app")
    parser.set_defaults(action=_do_run)
    sub = parser.add_subparsers(dest="subcommand")

    localdev = sub.add_parser(
        "localdev", help="Run with TOML config for local development"
    )
    localdev.add_argument("--config-file", "-c", default="ENV/localdev.toml")
    localdev.set_defaults(action=_do_localdev)

    return parser.parse_args()


def main() -> None:  # pragma: no cover
    args = _parse_args()
    args.action(args)


if __name__ == "__main__":  # pragma: no cover
    main()
