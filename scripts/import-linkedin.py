#!/usr/bin/env python3
"""Import LinkedIn posts/articles into Writing/ for the portfolio site.

Sources (in order):
  1. LinkedIn Posts API (optional — needs r_member_social or r_organization_social)
  2. RSS/Atom feed_url from linkedin.config.json (optional)
  3. JSON files in linkedin-inbox/
  4. URLs listed in linkedin-urls.txt

Fetches Open Graph metadata when needed, downloads cover images into
assets/writing/, and regenerates Writing/README.md.

Dedupes via scripts/linkedin-seen.json.

See scripts/LINKEDIN-API.md for API setup and LinkedIn permission limits.
"""

from __future__ import annotations

import argparse
import codecs
import hashlib
import html as html_lib
import json
import mimetypes
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

PERMALINK_RE = re.compile(
    r"linkedin\.com/(posts|pulse|newsletter)/|/feed/update/|ugcPost",
    re.I,
)


def load_config(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"ids": []}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("ids", [])
    return data


def save_state(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def fetch(url: str, timeout: int = 45) -> Tuple[bytes, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        return resp.read(), ctype


def slugify(text: str, fallback: str = "linkedin-post") -> str:
    text = html_lib.unescape(text.strip().lower())
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return (text[:72] or fallback).rstrip("-")


def is_permalink(url: str) -> bool:
    return bool(url and PERMALINK_RE.search(url))


def stable_id(url: str, title: str = "", date: str = "", content: str = "") -> str:
    url = (url or "").strip()
    if is_permalink(url):
        m = re.search(r"activity-(\d+)", url)
        if m:
            return f"activity-{m.group(1)}"
        raw = url.split("?")[0]
    else:
        raw = f"{url}|{title}|{date}|{(content or '')[:120]}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def parse_date(value: Optional[str]) -> str:
    if not value:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    value = value.strip()
    m = re.search(r"(\d{4}-\d{2}-\d{2})", value)
    if m:
        return m.group(1)
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%d %b %Y %H:%M:%S %z",
    ):
        try:
            cleaned = value
            if cleaned.endswith(" GMT"):
                cleaned = cleaned[:-4] + " +0000"
                fmt = "%a, %d %b %Y %H:%M:%S %z"
            dt = datetime.strptime(cleaned, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def excerpt_text(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", html_lib.unescape((text or "").strip()))
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1].rsplit(" ", 1)[0]
    return cut.rstrip(".,;:") + "…"


def title_from_content(content: str, kind: str) -> str:
    content = re.sub(r"\s+", " ", (content or "").strip())
    if not content:
        return "LinkedIn article" if kind == "article" else "LinkedIn post"
    first = content.split(". ", 1)[0].strip()
    if len(first) > 90:
        first = excerpt_text(first, 90)
    return first.rstrip(".")


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def text_of(el: Optional[ET.Element]) -> str:
    if el is None:
        return ""
    parts: List[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        parts.append(text_of(child))
        if child.tail:
            parts.append(child.tail)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def first_img_src(html_fragment: str) -> str:
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_fragment or "", re.I)
    return html_lib.unescape(m.group(1)) if m else ""


def parse_feed(xml_bytes: bytes) -> List[Dict[str, Any]]:
    root = ET.fromstring(xml_bytes)
    items: List[Dict[str, Any]] = []
    root_name = local_name(root.tag).lower()

    def add_item(
        title: str,
        link: str,
        desc_html: str,
        pub: str,
        guid: str,
        image: str = "",
    ) -> None:
        items.append(
            {
                "title": title,
                "url": link or guid,
                "date": parse_date(pub),
                "content": strip_html(desc_html),
                "image": image or first_img_src(desc_html),
                "kind": (
                    "article"
                    if "/pulse/" in (link or "") or "/newsletter/" in (link or "")
                    else "post"
                ),
                "id": guid or None,
            }
        )

    if root_name == "rss":
        channel = next((c for c in root if local_name(c.tag) == "channel"), root)
        entries = [c for c in channel if local_name(c.tag) == "item"]
        for entry in entries:
            title = link = desc = pub = guid = image = ""
            for child in entry:
                name = local_name(child.tag).lower()
                if name == "title":
                    title = text_of(child)
                elif name == "link":
                    link = (child.text or "").strip()
                elif name in ("description", "summary", "content", "encoded"):
                    inner = "".join(
                        [child.text or ""]
                        + [ET.tostring(c, encoding="unicode") for c in list(child)]
                        + ([child.tail] if child.tail else [])
                    )
                    if not desc or name in ("encoded", "content"):
                        desc = inner or text_of(child)
                elif name in ("pubdate", "published", "updated", "date"):
                    pub = (child.text or "").strip()
                elif name == "guid":
                    guid = (child.text or "").strip()
                elif name == "enclosure":
                    enc = child.attrib.get("url", "")
                    etype = child.attrib.get("type", "")
                    if enc and (etype.startswith("image/") or re.search(r"\.(jpe?g|png|webp|gif)(\?|$)", enc, re.I)):
                        image = enc
                elif name in ("content", "thumbnail"):
                    # media:content / media:thumbnail
                    href = child.attrib.get("url") or child.attrib.get("href") or ""
                    if href and not image:
                        image = href
            add_item(title, link, desc, pub, guid, image)
        return items

    entries = [c for c in root if local_name(c.tag) == "entry"]
    for entry in entries:
        title = link = desc = pub = entry_id = image = ""
        for child in entry:
            name = local_name(child.tag).lower()
            if name == "title":
                title = text_of(child)
            elif name == "link":
                href = child.attrib.get("href", "").strip()
                rel = child.attrib.get("rel", "alternate")
                if href and (rel == "alternate" or not link):
                    if child.attrib.get("type", "").startswith("image/") and not image:
                        image = href
                    elif rel in ("alternate", ""):
                        link = href
                elif rel == "enclosure" and href and not image:
                    image = href
            elif name in ("summary", "content"):
                desc = ET.tostring(child, encoding="unicode") if list(child) else (child.text or "")
                desc = desc or text_of(child)
            elif name in ("published", "updated"):
                if not pub or name == "published":
                    pub = (child.text or "").strip()
            elif name == "id":
                entry_id = (child.text or "").strip()
            elif name in ("content", "thumbnail"):
                href = child.attrib.get("url") or child.attrib.get("href") or ""
                if href and not image:
                    image = href
        add_item(title, link, desc, pub, entry_id, image)
    return items


def strip_html(fragment: str) -> str:
    fragment = re.sub(r"(?is)<script.*?>.*?</script>", " ", fragment or "")
    fragment = re.sub(r"(?is)<style.*?>.*?</style>", " ", fragment)
    fragment = re.sub(r"(?s)<[^>]+>", " ", fragment)
    fragment = html_lib.unescape(fragment)
    return re.sub(r"\s+", " ", fragment).strip()


def find_meta(html: str, *names: str) -> str:
    for name in names:
        patterns = [
            rf'<meta[^>]+property=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)["\']',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(name)}["\']',
            rf'<meta[^>]+name=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)["\']',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{re.escape(name)}["\']',
        ]
        for pat in patterns:
            m = re.search(pat, html, re.I)
            if m:
                return html_lib.unescape(m.group(1).strip())
    return ""


def fully_unescape(value: str) -> str:
    prev = None
    cur = value or ""
    while prev != cur:
        prev = cur
        cur = html_lib.unescape(cur)
    return cur.strip()


def decode_escaped_json_string(raw: str) -> str:
    try:
        return json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        try:
            return codecs.decode(raw, "unicode_escape")
        except Exception:
            return raw


def extract_linkedin_body(page: str) -> str:
    # Prefer visible commentary HTML (already UTF-8) over JSON strings.
    html_patterns = [
        r'data-test-id="main-feed-activity-card__commentary"[^>]*>(.*?)</div>',
        r'class="[^"]*break-words[^"]*"[^>]*>(.*?)</(?:p|div|span)>',
    ]
    for pat in html_patterns:
        m = re.search(pat, page, re.I | re.S)
        if not m:
            continue
        text = fully_unescape(strip_html(m.group(1)))
        if len(text) > 40:
            return text

    json_patterns = [
        r'"articleBody"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"commentary"\s*:\s*\{\s*"text"\s*:\s*"((?:\\.|[^"\\])*)"',
    ]
    for pat in json_patterns:
        m = re.search(pat, page, re.I | re.S)
        if not m:
            continue
        text = fully_unescape(strip_html(decode_escaped_json_string(m.group(1))))
        if len(text) > 40:
            return text
    return ""


def enrich_from_linkedin_page(url: str) -> Dict[str, str]:
    """Pull title, description, image, and published date from a LinkedIn permalink."""
    out = {"title": "", "content": "", "image": "", "date": "", "canonical": url, "kind": ""}
    try:
        raw, _ = fetch(url)
        page = raw.decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"Could not fetch LinkedIn page {url}: {exc}", file=sys.stderr)
        return out

    title = fully_unescape(find_meta(page, "og:title", "twitter:title"))
    if title:
        title = re.sub(r"\s*\|\s*LinkedIn\s*$", "", title)
        title = re.sub(r"\s*\|\s*Zlatko Lakisic.*$", "", title, flags=re.I)
        title = re.sub(r"\s*posted on the topic.*$", "", title, flags=re.I)
        title = title.strip(" |")
    body = extract_linkedin_body(page)
    desc = fully_unescape(find_meta(page, "og:description", "description", "twitter:description"))
    content = body or desc
    image = fully_unescape(find_meta(page, "og:image", "twitter:image"))
    canonical = find_meta(page, "og:url") or url
    published = ""
    m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', page)
    if m:
        published = m.group(1)
    kind = ""
    if "/pulse/" in url or "/newsletter/" in url:
        kind = "article"
    elif "article-cover" in image:
        kind = "article"
    elif "feedshare" in image:
        kind = "post"
    return {
        "title": title,
        "content": content,
        "image": image,
        "date": parse_date(published) if published else "",
        "canonical": canonical.split("?")[0],
        "kind": kind,
    }


def guess_ext(url: str, ctype: str) -> str:
    path = urllib.parse.urlparse(url).path
    ext = Path(path).suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ext
    if ctype in mimetypes.types_map.values() or True:
        by_type = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
        }
        if ctype in by_type:
            return by_type[ctype]
    return ".jpg"


def download_image(image_url: str, dest_dir: Path, item_id: str) -> Optional[str]:
    """Download cover image; return site-relative path like ../assets/writing/...."""
    if not image_url:
        return None
    image_url = html_lib.unescape(image_url.strip())
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        data, ctype = fetch(image_url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"Image download failed ({image_url[:80]}…): {exc}", file=sys.stderr)
        return None
    if not data or not ctype.startswith("image/") and data[:8] != b"\x89PNG\r\n\x1a\n" and data[:2] != b"\xff\xd8":
        # still accept if magic looks like image
        if not (data.startswith(b"\x89PNG") or data.startswith(b"\xff\xd8") or data.startswith(b"RIFF") or data.startswith(b"GIF8")):
            print(f"Skip non-image response for {image_url[:80]}… ({ctype})", file=sys.stderr)
            return None
    ext = guess_ext(image_url, ctype)
    if data.startswith(b"\x89PNG"):
        ext = ".png"
    elif data.startswith(b"\xff\xd8"):
        ext = ".jpg"
    elif data.startswith(b"GIF8"):
        ext = ".gif"
    elif data.startswith(b"RIFF"):
        ext = ".webp"
    filename = f"{slugify(item_id, fallback='linkedin-image')}{ext}"
    path = dest_dir / filename
    path.write_bytes(data)
    # Path relative from Writing/*.md
    return f"../assets/writing/{filename}"


def load_api_items(config: Dict[str, Any], max_chars: int) -> List[Dict[str, Any]]:
    api = config.get("api") or {}
    if not api.get("enabled"):
        return []
    try:
        from linkedin_api import LinkedInApiError, fetch_author_posts_as_items
    except ImportError as exc:
        print(f"LinkedIn API module unavailable: {exc}", file=sys.stderr)
        return []

    secrets = ROOT / api.get("secrets_file", "scripts/linkedin.secrets.json")
    tokens = ROOT / api.get("tokens_file", "scripts/linkedin-tokens.json")
    try:
        items, msg = fetch_author_posts_as_items(
            author_mode=api.get("author_mode", "member"),
            organization_urn=(api.get("organization_urn") or "").strip(),
            secrets_path=secrets,
            tokens_path=tokens,
            api_version=api.get("api_version", "202502"),
            max_chars=max_chars,
            count=int(api.get("count", 50)),
        )
        print(msg)
        # Skip Open Graph re-enrichment; API already provided fields
        for item in items:
            item["_skip_enrich"] = True
        return items
    except LinkedInApiError as exc:
        print(f"LinkedIn API source skipped: {exc}", file=sys.stderr)
        print(
            "Falling back to feed / inbox / linkedin-urls.txt. "
            "See scripts/LINKEDIN-API.md.",
            file=sys.stderr,
        )
        return []


def normalize_item(raw: Dict[str, Any], max_chars: int, enrich: bool = True) -> Optional[Dict[str, Any]]:
    url = (raw.get("url") or raw.get("link") or "").strip()
    content = (raw.get("content") or raw.get("summary") or raw.get("description") or "").strip()
    content = strip_html(content)
    image = (raw.get("image") or raw.get("image_url") or "").strip()
    kind = (raw.get("kind") or "").strip().lower()
    if not kind:
        kind = "article" if "/pulse/" in url or "article-cover" in image else "post"
    if kind not in ("post", "article"):
        kind = "article" if "article" in kind else "post"
    title = fully_unescape((raw.get("title") or "").strip())
    date = ""
    if raw.get("date") or raw.get("published") or raw.get("pubDate"):
        date = parse_date(raw.get("date") or raw.get("published") or raw.get("pubDate"))

    if enrich and url and is_permalink(url):
        needs = (not title) or (not content) or (not image) or (not date)
        if needs or raw.get("enrich", True):
            meta = enrich_from_linkedin_page(url)
            title = title or meta["title"]
            content = content or meta["content"]
            image = image or meta["image"]
            date = date or meta["date"]
            if meta.get("kind"):
                kind = meta["kind"]
            if meta.get("canonical") and is_permalink(meta["canonical"]):
                url = meta["canonical"]

    title = fully_unescape(title)
    content = fully_unescape(content)
    # LinkedIn often puts only hashtags in og:title for short posts
    if not title or re.fullmatch(r"(?:\s*#\w+)+", title or ""):
        title = title_from_content(content, kind)
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not url and not content:
        return None
    if url and not is_permalink(url):
        print(
            f"Warning: not a post/article permalink (will still import): {url}",
            file=sys.stderr,
        )

    item_id = (raw.get("id") or "").strip() or stable_id(url, title, date, content)
    return {
        "id": item_id,
        "title": title,
        "url": url,
        "date": date,
        "content": content,
        "excerpt": excerpt_text(content, max_chars) if content else "",
        "kind": kind,
        "image": image,
        "image_local": (raw.get("image_local") or "").strip(),
    }


def load_inbox(inbox_dir: Path, max_chars: int) -> Tuple[List[Dict[str, Any]], List[Path]]:
    items: List[Dict[str, Any]] = []
    sources: List[Path] = []
    if not inbox_dir.exists():
        return items, sources
    for path in sorted(inbox_dir.glob("*.json")):
        if path.name.endswith(".example.json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"Skip invalid JSON {path.name}: {exc}", file=sys.stderr)
            continue
        if isinstance(data, dict):
            data = data.get("items") or data.get("posts") or [data]
        if not isinstance(data, list):
            print(f"Skip {path.name}: expected a JSON array", file=sys.stderr)
            continue
        for raw in data:
            if not isinstance(raw, dict):
                continue
            item = normalize_item(raw, max_chars)
            if item:
                items.append(item)
        sources.append(path)
    return items, sources


def load_urls_file(path: Path, max_chars: int) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    items: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        kind = "article" if "/pulse/" in line or "/newsletter/" in line else "post"
        item = normalize_item({"url": line, "kind": kind}, max_chars, enrich=True)
        if item:
            items.append(item)
    return items


def load_feed(feed_url: str, max_chars: int) -> List[Dict[str, Any]]:
    if not feed_url or not feed_url.strip():
        return []
    try:
        raw, _ = fetch(feed_url.strip())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"Feed fetch failed: {exc}", file=sys.stderr)
        return []
    try:
        parsed = parse_feed(raw)
    except ET.ParseError as exc:
        print(f"Feed parse failed: {exc}", file=sys.stderr)
        return []
    items = []
    for raw_item in parsed:
        # Enrich when feed lacks image/permalink fidelity
        item = normalize_item(raw_item, max_chars, enrich=is_permalink(raw_item.get("url") or ""))
        if item and item["url"]:
            items.append(item)
    return items


def yaml_escape(value: str) -> str:
    return (value or "").replace("\\", "\\\\").replace('"', '\\"')


def attach_images(items: List[Dict[str, Any]], assets_dir: Path, download: bool) -> None:
    for item in items:
        if item.get("image_local"):
            continue
        if download and item.get("image"):
            local = download_image(item["image"], assets_dir, item["id"])
            if local:
                item["image_local"] = local


def write_post(output_dir: Path, item: Dict[str, Any]) -> Path:
    date = item["date"]
    slug = slugify(item["title"], fallback=f"linkedin-{item['id'][:8]}")
    filename = f"{date}-{slug}.md"
    path = output_dir / filename
    if path.exists():
        # Same import id → overwrite; different id → suffix
        existing = path.read_text(encoding="utf-8")
        if f'import_id: "{item["id"]}"' not in existing and f"import_id: {item['id']}" not in existing:
            path = output_dir / f"{date}-{slug}-{item['id'][:6]}.md"

    image_src = item.get("image_local") or ""
    image_remote = item.get("image") or ""
    display_image = image_src or image_remote

    lines = [
        "---",
        f'title: "{yaml_escape(item["title"])}"',
        f"date: {date}",
        f"kind: {item['kind']}",
        "source: linkedin",
        "body_class: writing-page",
        f'linkedin_url: "{yaml_escape(item["url"])}"' if item["url"] else 'linkedin_url: ""',
        f'import_id: "{item["id"]}"',
    ]
    if display_image:
        lines.append(f'image: "{yaml_escape(display_image)}"')
    if image_remote and image_src:
        lines.append(f'image_source: "{yaml_escape(image_remote)}"')
    lines.append("---")
    lines.append("")
    lines.append(f'# {item["title"]}')
    lines.append("")
    lines.append(
        f'<p class="writing-meta"><time datetime="{date}">{date}</time> · {item["kind"].capitalize()} · '
        f'<a href="{html_lib.escape(item["url"])}">View on LinkedIn</a></p>'
        if item["url"]
        else f'<p class="writing-meta"><time datetime="{date}">{date}</time> · {item["kind"].capitalize()}</p>'
    )
    lines.append("")
    if display_image:
        lines.append('<figure class="writing-cover">')
        lines.append(
            f'<img src="{html_lib.escape(display_image)}" alt="{html_lib.escape(item["title"])}" />'
        )
        lines.append("</figure>")
        lines.append("")
    if item["excerpt"]:
        lines.append(item["excerpt"])
        lines.append("")
    if item["url"]:
        lines.append(f'**[Continue the discussion on LinkedIn →]({item["url"]})**')
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def collect_written_posts(output_dir: Path) -> List[Dict[str, Any]]:
    posts: List[Dict[str, Any]] = []
    if not output_dir.exists():
        return posts
    for path in output_dir.glob("*.md"):
        if path.name == "README.md":
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        meta: Dict[str, str] = {}
        for line in parts[1].strip().splitlines():
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            value = val.strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            meta[key.strip()] = value
        body = parts[2].strip()
        blurb = ""
        for para in re.split(r"\n\s*\n", body):
            para = para.strip()
            if (
                not para
                or para.startswith("#")
                or para.startswith("<")
                or para.startswith("**[")
                or para.startswith("![")
            ):
                continue
            blurb = strip_html(para)
            break
        posts.append(
            {
                "path": path,
                "title": meta.get("title") or path.stem,
                "date": meta.get("date") or "",
                "kind": meta.get("kind") or "post",
                "linkedin_url": meta.get("linkedin_url") or "",
                "image": meta.get("image") or "",
                "blurb": blurb,
                "rel": f"./{path.name}",
                "html_rel": f"./{path.stem}.html",
            }
        )
    posts.sort(key=lambda p: (p["date"] or "", p["title"] or ""), reverse=True)
    return posts


def write_index(output_dir: Path, profile_url: str, posts: List[Dict[str, Any]]) -> None:
    # No YAML front matter: GitHub Pages treats Writing/README.md as the folder index
    # (same pattern as Recommendations/). Front matter would publish only README.html.
    # Emit HTML for entries — kramdown does not process Markdown nested inside HTML blocks.
    snippet_chars = 160
    lines = [
        "# Writing",
        "",
        "[← Back to Main Portfolio](../index.md)",
        "",
    ]
    if not posts:
        lines.extend(
            [
                "_Nothing published here yet._",
                "",
            ]
        )
    else:
        lines.append('<div class="writing-feed">')
        lines.append("")
        for post in posts:
            title = html_lib.escape(post["title"])
            blurb = excerpt_text(post.get("blurb") or "", snippet_chars)
            blurb_html = html_lib.escape(blurb)
            page_href = html_lib.escape(post.get("html_rel") or post["rel"].replace(".md", ".html"))
            linkedin = (post.get("linkedin_url") or "").strip()
            linkedin_href = html_lib.escape(linkedin)
            # Prefer LinkedIn for title + primary CTA; local page is optional archive
            primary_href = linkedin_href or page_href

            lines.append('<article class="writing-entry">')
            if post.get("image"):
                lines.append(
                    f'<a class="writing-entry-media" href="{primary_href}">'
                    f'<img src="{html_lib.escape(post["image"])}" alt="" /></a>'
                )
            lines.append('<div class="writing-entry-body">')
            lines.append(
                f'<p class="writing-meta"><time datetime="{html_lib.escape(post["date"])}">'
                f'{html_lib.escape(post["date"])}</time> · {html_lib.escape(post["kind"].capitalize())}</p>'
            )
            lines.append(f'<h3><a href="{primary_href}">{title}</a></h3>')
            if blurb_html:
                lines.append(f"<p>{blurb_html}</p>")
            actions = []
            if linkedin:
                actions.append(
                    f'<a href="{linkedin_href}">Read on LinkedIn →</a>'
                )
            actions.append(f'<a href="{page_href}">Archive →</a>')
            lines.append(
                '<p class="writing-entry-actions">' + " · ".join(actions) + "</p>"
            )
            lines.append("</div>")
            lines.append("</article>")
            lines.append("")
        lines.append("</div>")
        lines.append("")
    (output_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def remove_posts_by_ids(output_dir: Path, ids: List[str]) -> None:
    idset = set(ids)
    for path in output_dir.glob("*.md"):
        if path.name == "README.md":
            continue
        text = path.read_text(encoding="utf-8")
        for iid in idset:
            if f'import_id: "{iid}"' in text or f"import_id: {iid}" in text:
                path.unlink()
                print(f"Removed stale {path.relative_to(ROOT)}")
                break


def main() -> int:
    parser = argparse.ArgumentParser(description="Import LinkedIn content into Writing/")
    parser.add_argument(
        "--config",
        default=str(ROOT / "scripts" / "linkedin.config.json"),
        help="Path to linkedin.config.json",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be imported")
    parser.add_argument(
        "--rebuild-index",
        action="store_true",
        help="Only regenerate Writing/README.md from existing posts",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch and overwrite posts for URLs/feed items even if already seen",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    config = load_config(config_path)

    output_dir = ROOT / config.get("output_dir", "Writing")
    inbox_dir = ROOT / config.get("inbox_dir", "scripts/linkedin-inbox")
    state_path = ROOT / config.get("state_file", "scripts/linkedin-seen.json")
    urls_file = ROOT / config.get("urls_file", "scripts/linkedin-urls.txt")
    assets_dir = ROOT / config.get("assets_dir", "assets/writing")
    max_chars = int(config.get("excerpt_max_chars", 420))
    profile_url = config.get("profile_url", "https://www.linkedin.com/in/zlatko-lakisic/")
    feed_url = (config.get("feed_url") or "").strip()
    download_images = bool(config.get("download_images", True))

    if args.rebuild_index:
        posts = collect_written_posts(output_dir)
        write_index(output_dir, profile_url, posts)
        print(f"Updated {output_dir.relative_to(ROOT)}/README.md ({len(posts)} post(s))")
        return 0

    state = load_state(state_path)
    seen = set(state.get("ids") or [])

    candidates: List[Dict[str, Any]] = []
    api_items = load_api_items(config, max_chars)
    candidates.extend(api_items)
    candidates.extend(load_feed(feed_url, max_chars))
    inbox_items, inbox_sources = load_inbox(inbox_dir, max_chars)
    candidates.extend(inbox_items)
    candidates.extend(load_urls_file(urls_file, max_chars))

    ordered: List[Dict[str, Any]] = []
    seen_batch = set()
    for item in candidates:
        if item["id"] in seen_batch:
            continue
        seen_batch.add(item["id"])
        ordered.append(item)

    if args.refresh:
        new_items = ordered
    else:
        new_items = [i for i in ordered if i["id"] not in seen]

    urls_configured = any(
        line.strip() and not line.strip().startswith("#")
        for line in (urls_file.read_text(encoding="utf-8").splitlines() if urls_file.exists() else [])
    )
    if not api_items and not feed_url and not inbox_items and not urls_configured:
        print("No sources configured.")
        print("  • Enable LinkedIn API in scripts/linkedin.config.json (see LINKEDIN-API.md), or")
        print("  • Set feed_url, or")
        print("  • Drop *.json into scripts/linkedin-inbox/, or")
        print("  • Add post/article URLs to scripts/linkedin-urls.txt")

    if args.dry_run:
        print(
            f"Would import {len(new_items)} item(s) "
            f"({len(ordered)} from sources, {len(seen)} already seen)"
        )
        for item in new_items:
            img = "img" if item.get("image") else "no-img"
            print(f"  - {item['date']} [{item['kind']}/{img}] {item['title'][:70]}")
            print(f"    {item['url']}")
        return 0

    attach_images(new_items, assets_dir, download_images)

    output_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for item in new_items:
        path = write_post(output_dir, item)
        seen.add(item["id"])
        written += 1
        print(f"Wrote {path.relative_to(ROOT)}")

    # Drop old demo placeholder posts if present
    remove_posts_by_ids(
        output_dir,
        [
            "demo-connected-care-2026-06",
            "demo-mcp-boundary-2026-07",
            "demo-presales-architecture-2026-07",
        ],
    )
    for demo_id in (
        "demo-connected-care-2026-06",
        "demo-mcp-boundary-2026-07",
        "demo-presales-architecture-2026-07",
    ):
        seen.discard(demo_id)

    state["ids"] = sorted(seen)
    state["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_state(state_path, state)

    if inbox_sources and new_items:
        processed = inbox_dir / "processed"
        processed.mkdir(parents=True, exist_ok=True)
        for src in inbox_sources:
            dest = processed / src.name
            if dest.exists():
                dest = processed / f"{src.stem}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{src.suffix}"
            shutil.move(str(src), str(dest))
            print(f"Moved inbox {src.name} → processed/")

    posts = collect_written_posts(output_dir)
    write_index(output_dir, profile_url, posts)
    print(f"Updated {output_dir.relative_to(ROOT)}/README.md ({len(posts)} post(s))")
    print(f"Imported {written} item(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
