#!/usr/bin/env python3
"""LinkedIn Marketing / Community Management API helpers for the portfolio importer.

Reading *personal* posts requires the closed `r_member_social` scope (LinkedIn is
not accepting new access requests). Organization posts need
`r_organization_social` (Community Management product + page admin).

This module:
  1. Completes local OAuth (`linkedin-oauth.py` / `authorize()`)
  2. Calls Posts API author finder
  3. Maps posts into the same dict shape used by `import-linkedin.py`
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
DEFAULT_SECRETS = SCRIPTS / "linkedin.secrets.json"
DEFAULT_TOKENS = SCRIPTS / "linkedin-tokens.json"
DEFAULT_API_VERSION = "202502"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
API_BASE = "https://api.linkedin.com/rest"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
ME_URL = "https://api.linkedin.com/v2/me"

# Prefer organization read if available; member read is closed for most apps.
DEFAULT_SCOPES = "openid profile email w_member_social r_organization_social"


class LinkedInApiError(RuntimeError):
    def __init__(self, message: str, status: int = 0, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _form_encode(data: Dict[str, str]) -> bytes:
    return urllib.parse.urlencode(data).encode("utf-8")


def exchange_code(secrets: Dict[str, str], code: str) -> Dict[str, Any]:
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": secrets["redirect_uri"],
        "client_id": secrets["client_id"],
        "client_secret": secrets["client_secret"],
    }
    req = urllib.request.Request(
        TOKEN_URL,
        data=_form_encode(payload),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        token = json.loads(resp.read().decode("utf-8"))
    token["obtained_at"] = int(time.time())
    if "expires_in" in token:
        token["expires_at"] = token["obtained_at"] + int(token["expires_in"])
    return token


def refresh_token(secrets: Dict[str, str], tokens: Dict[str, Any]) -> Dict[str, Any]:
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise LinkedInApiError("No refresh_token available; re-run OAuth.")
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": secrets["client_id"],
        "client_secret": secrets["client_secret"],
    }
    req = urllib.request.Request(
        TOKEN_URL,
        data=_form_encode(payload),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        refreshed = json.loads(resp.read().decode("utf-8"))
    tokens.update(refreshed)
    tokens["obtained_at"] = int(time.time())
    if "expires_in" in refreshed:
        tokens["expires_at"] = tokens["obtained_at"] + int(refreshed["expires_in"])
    return tokens


def ensure_access_token(
    secrets_path: Path = DEFAULT_SECRETS,
    tokens_path: Path = DEFAULT_TOKENS,
) -> str:
    secrets = load_json(secrets_path)
    tokens = load_json(tokens_path)
    if not secrets.get("client_id") or not secrets.get("client_secret"):
        raise LinkedInApiError(
            f"Missing LinkedIn app credentials. Copy {DEFAULT_SECRETS.name.replace('.json', '.example.json')} "
            f"to {secrets_path.name} and fill client_id / client_secret."
        )
    if not tokens.get("access_token"):
        raise LinkedInApiError(
            "No access token. Run: python3 scripts/linkedin-oauth.py"
        )
    expires_at = int(tokens.get("expires_at") or 0)
    if expires_at and time.time() > expires_at - 120:
        try:
            tokens = refresh_token(secrets, tokens)
            save_json(tokens_path, tokens)
        except (urllib.error.HTTPError, LinkedInApiError) as exc:
            raise LinkedInApiError(
                f"Token refresh failed ({exc}). Re-run: python3 scripts/linkedin-oauth.py"
            ) from exc
    return str(tokens["access_token"])


def api_request(
    method: str,
    path: str,
    access_token: str,
    *,
    api_version: str = DEFAULT_API_VERSION,
    query: Optional[Dict[str, str]] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Any:
    url = path if path.startswith("http") else f"{API_BASE}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query, doseq=True, safe=':%,')}"
    data = None
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": api_version,
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise LinkedInApiError(
            f"LinkedIn API {method} {url} failed HTTP {exc.code}: {err_body[:500]}",
            status=exc.code,
            body=err_body,
        ) from exc


def get_member_person_urn(access_token: str, api_version: str = DEFAULT_API_VERSION) -> str:
    """Return urn:li:person:{id} for the authenticated member."""
    # OpenID userinfo (Sign In with LinkedIn)
    try:
        req = urllib.request.Request(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            info = json.loads(resp.read().decode("utf-8"))
        sub = info.get("sub")
        if sub:
            return f"urn:li:person:{sub}"
    except urllib.error.HTTPError:
        pass

    # Legacy /v2/me
    try:
        req = urllib.request.Request(
            ME_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "X-Restli-Protocol-Version": "2.0.0",
                "LinkedIn-Version": api_version,
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            me = json.loads(resp.read().decode("utf-8"))
        mid = me.get("id")
        if mid:
            return f"urn:li:person:{mid}"
    except urllib.error.HTTPError as exc:
        raise LinkedInApiError(
            f"Could not resolve member URN ({exc.code}). Ensure openid/profile scopes are granted."
        ) from exc
    raise LinkedInApiError("Could not resolve member person URN from token.")


def find_posts_by_author(
    access_token: str,
    author_urn: str,
    *,
    count: int = 50,
    start: int = 0,
    api_version: str = DEFAULT_API_VERSION,
    view_context: str = "AUTHOR",
) -> Dict[str, Any]:
    # LinkedIn expects Rest.li encoded author query param.
    author_encoded = urllib.parse.quote(author_urn, safe="")
    path = (
        f"/posts?author={author_encoded}&q=author"
        f"&count={int(count)}&start={int(start)}"
        f"&sortBy=LAST_MODIFIED&viewContext={view_context}"
    )
    return api_request("GET", path, access_token, api_version=api_version)


def strip_little_text(commentary: str) -> str:
    """Convert LinkedIn little text / mention markup to plain text."""
    text = commentary or ""
    text = re.sub(r"@\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\{hashtag\|\\?#\|([^}]+)\}", r"#\1", text)
    text = re.sub(r"\{[^|]+\|[^|]+\|([^}]+)\}", r"\1", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def post_permalink(post_id: str) -> str:
    post_id = (post_id or "").strip()
    if not post_id:
        return ""
    encoded = urllib.parse.quote(post_id, safe="")
    return f"https://www.linkedin.com/feed/update/{encoded}"


def _media_image_url(access_token: str, media_urn: str, api_version: str) -> str:
    if not media_urn:
        return ""
    encoded = urllib.parse.quote(media_urn, safe="")
    # Images API (preferred for urn:li:image:*)
    if "image:" in media_urn or media_urn.startswith("urn:li:image:"):
        try:
            data = api_request(
                "GET",
                f"/images/{encoded}",
                access_token,
                api_version=api_version,
            )
            return (
                data.get("downloadUrl")
                or data.get("download_url")
                or (data.get("originalUrl") if isinstance(data.get("originalUrl"), str) else "")
                or ""
            )
        except LinkedInApiError:
            return ""
    # Generic digital media asset
    try:
        data = api_request(
            "GET",
            f"/assets/{encoded}",
            access_token,
            api_version=api_version,
        )
        # Best-effort shapes
        for key in ("downloadUrl", "download_url", "url"):
            if isinstance(data.get(key), str):
                return data[key]
        recipes = data.get("recipes") or data.get("identifiers") or []
        if isinstance(recipes, list) and recipes:
            first = recipes[0]
            if isinstance(first, dict):
                return first.get("identifier") or first.get("url") or ""
    except LinkedInApiError:
        return ""
    return ""


def extract_image_from_post(
    post: Dict[str, Any],
    access_token: str,
    api_version: str,
) -> str:
    content = post.get("content") or {}
    if not isinstance(content, dict):
        return ""

    # Single media
    media = content.get("media")
    if isinstance(media, dict):
        mid = media.get("id") or ""
        url = _media_image_url(access_token, mid, api_version)
        if url:
            return url

    # Multi-image — take first
    multi = content.get("multiImage") or content.get("multiimage")
    if isinstance(multi, dict):
        images = multi.get("images") or []
        if images and isinstance(images[0], dict):
            mid = images[0].get("id") or ""
            url = _media_image_url(access_token, mid, api_version)
            if url:
                return url

    # Article / link share thumbnail
    article = content.get("article") or content.get("landingPage")
    if isinstance(article, dict):
        thumb = article.get("thumbnail") or article.get("thumbnailUrn") or ""
        if isinstance(thumb, str) and thumb.startswith("http"):
            return thumb
        if isinstance(thumb, str) and thumb.startswith("urn:"):
            url = _media_image_url(access_token, thumb, api_version)
            if url:
                return url
        if isinstance(thumb, dict):
            mid = thumb.get("id") or ""
            url = _media_image_url(access_token, mid, api_version)
            if url:
                return url
    return ""


def post_to_import_item(
    post: Dict[str, Any],
    access_token: str,
    *,
    api_version: str,
    max_chars: int,
) -> Optional[Dict[str, Any]]:
    post_id = post.get("id") or ""
    if post.get("lifecycleState") and post.get("lifecycleState") != "PUBLISHED":
        return None

    commentary = strip_little_text(post.get("commentary") or "")
    content = post.get("content") or {}
    kind = "post"
    title = ""
    if isinstance(content, dict) and content.get("article"):
        kind = "article"
        article = content["article"] if isinstance(content["article"], dict) else {}
        title = (article.get("title") or "").strip()
    if not title:
        # First sentence / excerpt as title
        title = commentary.split(". ", 1)[0].strip()[:90] or "LinkedIn post"

    published = post.get("publishedAt") or post.get("createdAt")
    if isinstance(published, (int, float)):
        date = datetime.fromtimestamp(published / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    else:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    url = post_permalink(post_id)
    image = extract_image_from_post(post, access_token, api_version)

    # Stable id from share/ugcPost numeric part
    m = re.search(r":(\d+)$", post_id)
    item_id = f"api-{m.group(1)}" if m else f"api-{hashlib.sha1(post_id.encode()).hexdigest()[:16]}"

    excerpt = commentary
    if len(excerpt) > max_chars:
        cut = excerpt[: max_chars - 1].rsplit(" ", 1)[0]
        excerpt = cut.rstrip(".,;:") + "…"

    return {
        "id": item_id,
        "title": title,
        "url": url,
        "date": date,
        "content": commentary,
        "excerpt": excerpt,
        "kind": kind,
        "image": image,
        "image_local": "",
        "source": "linkedin-api",
        "api_urn": post_id,
    }


def fetch_author_posts_as_items(
    *,
    author_mode: str = "member",
    organization_urn: str = "",
    secrets_path: Path = DEFAULT_SECRETS,
    tokens_path: Path = DEFAULT_TOKENS,
    api_version: str = DEFAULT_API_VERSION,
    max_chars: int = 420,
    count: int = 50,
) -> Tuple[List[Dict[str, Any]], str]:
    """Fetch posts and map to importer items. Returns (items, status_message)."""
    access_token = ensure_access_token(secrets_path, tokens_path)

    if author_mode == "organization":
        if not organization_urn:
            raise LinkedInApiError(
                "api.organization_urn is required when api.author_mode=organization "
                "(example: urn:li:organization:123456)."
            )
        author_urn = organization_urn
        needed = "r_organization_social"
    else:
        author_urn = get_member_person_urn(access_token, api_version)
        needed = "r_member_social"

    try:
        payload = find_posts_by_author(
            access_token,
            author_urn,
            count=count,
            api_version=api_version,
        )
    except LinkedInApiError as exc:
        hint = ""
        if exc.status in (401, 403, 400) or "r_member_social" in (exc.body or "").lower():
            hint = (
                f"\n\nLinkedIn blocked author post reads for {author_urn}. "
                f"Required scope: `{needed}`.\n"
                "As of 2026, `r_member_social` is a closed permission "
                "(LinkedIn is not accepting new requests). "
                "Organization reads need Community Management API approval "
                "plus `r_organization_social`.\n"
                "Docs: https://learn.microsoft.com/en-us/linkedin/marketing/lms-faq"
            )
        raise LinkedInApiError(str(exc) + hint, status=exc.status, body=exc.body) from exc

    elements = payload.get("elements") or []
    items: List[Dict[str, Any]] = []
    for post in elements:
        if not isinstance(post, dict):
            continue
        item = post_to_import_item(
            post, access_token, api_version=api_version, max_chars=max_chars
        )
        if item:
            items.append(item)

    msg = (
        f"API returned {len(items)} post(s) for {author_urn} "
        f"(raw elements={len(elements)})."
    )
    return items, msg


def authorize_local(
    secrets_path: Path = DEFAULT_SECRETS,
    tokens_path: Path = DEFAULT_TOKENS,
    scopes: str = DEFAULT_SCOPES,
) -> Dict[str, Any]:
    secrets = load_json(secrets_path)
    for key in ("client_id", "client_secret", "redirect_uri"):
        if not secrets.get(key) or str(secrets[key]).startswith("YOUR_"):
            raise LinkedInApiError(
                f"Fill {key} in {secrets_path}. See linkedin.secrets.example.json."
            )

    redirect = secrets["redirect_uri"]
    parsed = urlparse(redirect)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8765
    path = parsed.path or "/callback"

    params = {
        "response_type": "code",
        "client_id": secrets["client_id"],
        "redirect_uri": redirect,
        "scope": scopes,
        "state": hashlib.sha1(str(time.time()).encode()).hexdigest()[:16],
    }
    auth_link = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    result: Dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            qs = parse_qs(urlparse(self.path).query)
            if self.path.startswith(path):
                if qs.get("error"):
                    result["error"] = qs.get("error_description", qs["error"])[0]
                else:
                    result["code"] = (qs.get("code") or [""])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h1>LinkedIn auth complete</h1>"
                    b"<p>You can close this tab and return to the terminal.</p>"
                    b"</body></html>"
                )
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, fmt, *args):  # noqa: A003
            return

    print("Open this URL in your browser and approve access:\n")
    print(auth_link)
    print(f"\nWaiting on {redirect} …")
    server = HTTPServer((host, port), Handler)
    while "code" not in result and "error" not in result:
        server.handle_request()
    server.server_close()

    if result.get("error"):
        raise LinkedInApiError(f"OAuth error: {result['error']}")
    if not result.get("code"):
        raise LinkedInApiError("OAuth did not return an authorization code.")

    tokens = exchange_code(secrets, result["code"])
    save_json(tokens_path, tokens)
    print(f"Saved tokens → {tokens_path.relative_to(ROOT)}")
    print("Scopes/token ready. Probe with: python3 scripts/linkedin-oauth.py --probe")
    return tokens


def probe(api_cfg: Optional[Dict[str, Any]] = None) -> int:
    api_cfg = api_cfg or {}
    try:
        access = ensure_access_token()
        print("✓ access_token present")
        try:
            person = get_member_person_urn(access, api_cfg.get("api_version", DEFAULT_API_VERSION))
            print(f"✓ member URN: {person}")
        except LinkedInApiError as exc:
            print(f"✗ member URN: {exc}")
            return 1

        mode = api_cfg.get("author_mode", "member")
        org = api_cfg.get("organization_urn", "")
        author = org if mode == "organization" else person
        print(f"Probing Posts API author finder for {author} …")
        try:
            data = find_posts_by_author(
                access,
                author,
                count=3,
                api_version=api_cfg.get("api_version", DEFAULT_API_VERSION),
            )
            n = len(data.get("elements") or [])
            print(f"✓ Posts API OK — {n} element(s) in first page")
            return 0
        except LinkedInApiError as exc:
            print(f"✗ Posts API failed: {exc}")
            print(
                "\nThis usually means LinkedIn has not granted post-read access "
                "(`r_member_social` for personal posts is currently closed)."
            )
            return 2
    except LinkedInApiError as exc:
        print(f"✗ {exc}")
        return 1
