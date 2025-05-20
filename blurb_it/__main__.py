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

    if await util.has_session(request):
        context.update(await util.get_session_context(request, context))
        async with aiohttp.ClientSession() as session:

            gh = GitHubAPI(session, context["username"])

            jwt = get_jwt(
                app_id=os.getenv("GH_APP_ID"), private_key=os.getenv("GH_PRIVATE_KEY")
            )
            try:
                await util.get_installation(gh, jwt, context["username"])
            except error.InstallationNotFound:
                return web.HTTPFound(location=request.app.router["install"].url_for())

            if pr_number_start := request.query.get("pr_number_start"):
                context['current_pr'] = await gh.getitem(
                    f"/repos/python/cpython/pulls/{pr_number_start}",
                    jwt=jwt,
                    accept="application/vnd.github+json"
                )
                # have a gh and a jwt....
                print(f"TODO: Get PR info|{context['current_pr']=}")

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

                jwt = get_jwt(
                    app_id=os.getenv("GH_APP_ID"),
                    private_key=os.getenv("GH_PRIVATE_KEY"),
                )
                try:
                    await util.get_installation(gh, jwt, context["username"])
                except error.InstallationNotFound:
                    return web.HTTPFound(
                        location=request.app.router["install"].url_for()
                    )

                if pr_number_start := request.query.get("pr_number_start"):
                    context['current_pr'] = await gh.getitem(
                        f"/repos/python/cpython/pulls/{pr_number_start}",
                        jwt=jwt,
                        accept="application/vnd.github+json"
                    )
                    # have a gh and a jwt....
                    print(f"TODO: Get PR info|{context['current_pr']=}")

    else:
        return web.HTTPFound(location=request.app.router["home"].url_for())

    print("TODO: Get general user pr list")

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

            jwt = get_jwt(
                app_id=os.getenv("GH_APP_ID"), private_key=os.getenv("GH_PRIVATE_KEY")
            )
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

def do_run_env_vars():
    fernet_key = fernet.Fernet.generate_key()
    secret_key = base64.urlsafe_b64decode(fernet_key)

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
    port = os.environ.get("PORT")
    if port is not None:
        port = int(port)
    app.router.add_routes(routes)
    app.add_routes([web.static("/static", os.path.join(os.getcwd(), "static"))])
    web.run_app(app, port=port)


def do_config_from_toml(config_filename):
    """Load TOML config and set env vars to run."""
    # TODO: Requires 3.11+
    import tomllib
    with open(config_filename, 'rb') as file:
        config = tomllib.load(file)

    # Turn TOML into environment variables
    have = set(config.keys())
    required = {
        "app_url": "APP_URL",
        "github_app_id": "GH_APP_ID",
        "github_private_key_path": None,
        "github_client_id": "GH_CLIENT_ID",
        "github_client_secret": "GH_CLIENT_SECRET",
        "port": "PORT",
    }

    # Produce a nice error if a config key is mistyped
    needed_config_keys = set(required.keys())
    if needed_config_keys != have:
        missing = needed_config_keys - have
        extra = have - needed_config_keys
        print(f"Invalid config|{missing=}|{extra=}")
        sys.exit(1)

    for k, v in required.items():
        if v is None:
            continue
        os.environ[v] = str(config[k])

    config_key_path = Path(config['github_private_key_path'])
    if not config_key_path.is_absolute():
        config_key_path = Path("ENV") / config_key_path
    private_key = config_key_path.read_text()
    os.environ['GH_PRIVATE_KEY'] = private_key
    os.environ["APP_PROTOCOL"] = "http"
    os.environ["APP_URL"] = f"{config['app_url']}:{config['port']}"

def do_localdev(args):
    do_config_from_toml(args.config_file)
    do_run_env_vars()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.set_defaults(action=lambda args: do_run_env_vars)
    sub = parser.add_subparsers(dest="subcommand", required=False)

    # User friendly local development setup
    localdev = sub.add_parser("localdev")
    localdev.add_argument("--config-file", "-c", default="ENV/localdev.toml")
    localdev.set_defaults(action=do_localdev)

    # TODO: Add `setup` subcommand that will guide through creating Github App
    # credentials and writing localdev.toml config.

    return parser.parse_args()

def do_main():
    args = parse_args()
    args.action(args)

if __name__ == "__main__":  # pragma: no cover
    do_main()