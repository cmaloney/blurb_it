import base64
import hashlib
import os
import re
import time
import secrets

from aiohttp_session import get_session

from blurb_it import error


async def get_misc_news_filename(issue_number, section, body):
    if " " in section:
        raise ValueError(f"Use underscores not spaces in section name: {section}")
    date = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime())
    nonce = await nonceify(body)
    path = f"Misc/NEWS.d/next/{section}/{date}.gh-issue-{issue_number}.{nonce}.rst"
    return path


async def nonceify(body):
    digest = hashlib.md5(body.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)[0:6].decode("ascii")


def get_app_context() -> dict:
    protocol = os.environ.get("APP_PROTOCOL", "https")
    host = os.environ.get("APP_URL", "")
    return {
        "client_id": os.environ.get("GH_CLIENT_ID"),
        "app_base_url": f"{protocol}://{host}",
    }


async def get_session_context(request, context=None):
    context = context or {}
    if await has_session(request):
        request_session = await get_session(request)
        context["username"] = request_session["username"]
        context["token"] = request_session["token"]

    return context


async def has_session(request):
    request_session = await get_session(request)
    return request_session.get("username") and request_session.get("token")


def get_csrf_token(session):
    try:
        return session["csrf"]
    except KeyError:
        session["csrf"] = csrf = create_csrf_token()
        return csrf


def create_csrf_token():
    return secrets.token_urlsafe(32)


def compare_csrf_tokens(token_a, token_b):
    return secrets.compare_digest(token_a, token_b)


async def get_existing_pr_blurb(gh, pr_number: str) -> dict | None:
    """Return {section, content} if the PR contains an existing blurb file, else None."""
    blurb_pattern = re.compile(r"Misc/NEWS\.d/next/([^/]+)/.*\.rst$")
    async for file in gh.getiter(
        f"/repos/python/cpython/pulls/{pr_number}/files",
        accept="application/vnd.github+json",
    ):
        if file["status"] == "removed":
            continue
        m = blurb_pattern.match(file["filename"])
        if m:
            section = m.group(1)
            patch = file.get("patch", "")
            lines = [
                line[1:]
                for line in patch.splitlines()
                if line.startswith("+") and not line.startswith("+++")
            ]
            content = "\n".join(lines).strip()
            return {"section": section, "content": content}
    return None


def parse_issue_number_from_title(title: str) -> str | None:
    """Extract a CPython issue number from a PR title like 'gh-12345: ...'"""
    m = re.search(r'gh-(\d+)', title, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r'bpo-(\d+)', title, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


async def get_user_cpython_prs(gh, username: str, limit: int = 5) -> list[dict]:
    """Return the most recently updated open CPython PRs authored by username."""
    query = f"is:pr+is:open+repo:python/cpython+author:{username}"
    result = await gh.getitem(
        f"/search/issues?q={query}&sort=updated&per_page={limit}",
    )
    prs = []
    for item in result.get("items", []):
        prs.append(
            {
                "number": item["number"],
                "title": item["title"],
                "issue_number": parse_issue_number_from_title(item["title"]),
            }
        )
    return prs


async def get_installation(gh, jwt, username):

    async for installation in gh.getiter(
        "/app/installations",
        jwt=jwt,
        accept="application/vnd.github.machine-man-preview+json",
    ):  # pragma: no cover
        if installation["account"]["login"] == username:
            return installation

    raise error.InstallationNotFound(
        f"Can't find installation by that user: {username}"
    )
