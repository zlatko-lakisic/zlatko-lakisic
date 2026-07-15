#!/usr/bin/env python3
"""Import LinkedIn posts/articles into Writing/ for the portfolio site.

Sources (in order):
  1. RSS/Atom feed_url from linkedin.config.json (optional)
  2. JSON files in linkedin-inbox/
  3. URLs listed in linkedin-urls.txt

Dedupes via scripts/linkedin-seen.json. Regenerates Writing/README.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "zlatko-lakisic-portfolio-linkedin-import/1.0 (+https://github.com/zlatko-lakisic/zlatko-lakisic)"


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


def fetch(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def slugify(text: str, fallback: str = "linkedin-post") -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return (text[:72] or fallback).rstrip("-")


def stable_id(url: str, title: str = "", date: str = "", content: str = "") -> str:
    url = (url or "").strip()
    # Distinct post/article permalinks are enough; profile landing pages are not.
    if url and re.search(r"/(posts|pulse|newsletter|feed/update|ugcPost)/", url, re.I):
        raw = url
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
    text = re.sub(r"\s+", " ", (text or "").strip())
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
    if not first.endswith((".", "!", "?")):
        # keep as headline fragment
        pass
    else:
        first = first.rstrip(".")
    return first


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


def parse_feed(xml_bytes: bytes) -> List[Dict[str, Any]]:
    root = ET.fromstring(xml_bytes)
    items: List[Dict[str, Any]] = []
    root_name = local_name(root.tag).lower()

    if root_name == "rss":
        channel = next((c for c in root if local_name(c.tag) == "channel"), root)
        entries = [c for c in channel if local_name(c.tag) == "item"]
        for entry in entries:
            title = ""
            link = ""
            desc = ""
            pub = ""
            guid = ""
            for child in entry:
                name = local_name(child.tag).lower()
                if name == "title":
                    title = text_of(child)
                elif name == "link":
                    link = (child.text or "").strip()
                elif name in ("description", "summary", "content", "encoded"):
                    desc = text_of(child) or desc
                elif name in ("pubdate", "published", "updated", "date"):
                    pub = (child.text or "").strip()
                elif name == "guid":
                    guid = (child.text or "").strip()
            items.append(
                {
                    "title": title,
                    "url": link or guid,
                    "date": parse_date(pub),
                    "content": desc,
                    "kind": "article" if "/pulse/" in (link or "") or "/newsletter/" in (link or "") else "post",
                    "id": guid or None,
                }
            )
        return items

    # Atom
    entries = [c for c in root if local_name(c.tag) == "entry"]
    for entry in entries:
        title = ""
        link = ""
        desc = ""
        pub = ""
        entry_id = ""
        for child in entry:
            name = local_name(child.tag).lower()
            if name == "title":
                title = text_of(child)
            elif name == "link":
                href = child.attrib.get("href", "").strip()
                rel = child.attrib.get("rel", "alternate")
                if href and (rel == "alternate" or not link):
                    link = href
            elif name in ("summary", "content"):
                desc = text_of(child) or desc
            elif name in ("published", "updated"):
                if not pub or name == "published":
                    pub = (child.text or "").strip()
            elif name == "id":
                entry_id = (child.text or "").strip()
        items.append(
            {
                "title": title,
                "url": link or entry_id,
                "date": parse_date(pub),
                "content": desc,
                "kind": "article" if "/pulse/" in (link or "") or "/newsletter/" in (link or "") else "post",
                "id": entry_id or None,
            }
        )
    return items


def strip_html(html: str) -> str:
    html = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    html = re.sub(r"(?is)<style.*?>.*?</style>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = re.sub(r"&nbsp;", " ", html)
    html = re.sub(r"&amp;", "&", html)
    html = re.sub(r"&quot;", '"', html)
    html = re.sub(r"&#39;", "'", html)
    html = re.sub(r"&lt;", "<", html)
    html = re.sub(r"&gt;", ">", html)
    return re.sub(r"\s+", " ", html).strip()


def meta_from_html(html: str) -> Tuple[str, str]:
    def find_meta(*names: str) -> str:
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
                    return strip_html(m.group(1))
        return ""

    title = find_meta("og:title", "twitter:title")
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = strip_html(m.group(1)) if m else ""
    desc = find_meta("og:description", "description", "twitter:description")
    return title, desc


def normalize_item(raw: Dict[str, Any], max_chars: int) -> Optional[Dict[str, Any]]:
    url = (raw.get("url") or raw.get("link") or "").strip()
    content = (raw.get("content") or raw.get("summary") or raw.get("description") or "").strip()
    content = strip_html(content)
    kind = (raw.get("kind") or "post").strip().lower()
    if kind not in ("post", "article"):
        kind = "article" if "article" in kind else "post"
    title = (raw.get("title") or "").strip()
    if not title:
        title = title_from_content(content, kind)
    date = parse_date(raw.get("date") or raw.get("published") or raw.get("pubDate"))
    if not url and not content:
        return None
    item_id = (raw.get("id") or "").strip() or stable_id(url, title, date, content)
    return {
        "id": item_id,
        "title": title,
        "url": url,
        "date": date,
        "content": content,
        "excerpt": excerpt_text(content, max_chars) if content else "",
        "kind": kind,
        "demo": bool(raw.get("demo")),
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
        title, desc = "", ""
        try:
            html = fetch(line).decode("utf-8", errors="replace")
            title, desc = meta_from_html(html)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"Could not fetch metadata for {line}: {exc}", file=sys.stderr)
        kind = "article" if "/pulse/" in line or "/newsletter/" in line else "post"
        items.append(
            normalize_item(
                {
                    "title": title,
                    "url": line,
                    "content": desc,
                    "kind": kind,
                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                },
                max_chars,
            )
        )
    return [i for i in items if i]


def load_feed(feed_url: str, max_chars: int) -> List[Dict[str, Any]]:
    if not feed_url or not feed_url.strip():
        return []
    try:
        raw = fetch(feed_url.strip())
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
        item = normalize_item(raw_item, max_chars)
        if item and item["url"]:
            items.append(item)
    return items


def yaml_escape(value: str) -> str:
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    return value


def write_post(output_dir: Path, item: Dict[str, Any]) -> Path:
    date = item["date"]
    slug = slugify(item["title"], fallback=f"linkedin-{item['id'][:8]}")
    filename = f"{date}-{slug}.md"
    path = output_dir / filename
    # Avoid clobbering different ids that slug-collide
    if path.exists():
        path = output_dir / f"{date}-{slug}-{item['id'][:6]}.md"

    lines = [
        "---",
        f'title: "{yaml_escape(item["title"])}"',
        f"date: {date}",
        f"kind: {item['kind']}",
        "source: linkedin",
        f'linkedin_url: "{yaml_escape(item["url"])}"' if item["url"] else 'linkedin_url: ""',
        f'import_id: "{item["id"]}"',
    ]
    if item.get("demo"):
        lines.append("demo: true")
    lines.append("---")
    lines.append("")
    lines.append(f"# {item['title']}")
    lines.append("")
    if item.get("demo"):
        lines.append("> Sample import for preview — replace by configuring `feed_url` or dropping real items into `scripts/linkedin-inbox/`.")
        lines.append("")
    if item["excerpt"]:
        lines.append(item["excerpt"])
        lines.append("")
    if item["url"]:
        lines.append(f"**[Discuss on LinkedIn →]({item['url']})**")
        lines.append("")
    else:
        lines.append("*No LinkedIn URL provided for this item.*")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def collect_written_posts(output_dir: Path) -> List[Dict[str, Any]]:
    posts: List[Dict[str, Any]] = []
    if not output_dir.exists():
        return posts
    for path in output_dir.glob("*.md"):
        if path.name.upper() == "README.MD" or path.name == "README.md":
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
            meta[key.strip()] = val.strip().strip('"')
        body = parts[2].strip()
        # first non-heading, non-blockquote paragraph as blurb
        blurb = ""
        for para in re.split(r"\n\s*\n", body):
            para = para.strip()
            if not para or para.startswith("#") or para.startswith(">") or para.startswith("**["):
                continue
            blurb = para
            break
        posts.append(
            {
                "path": path,
                "title": meta.get("title") or path.stem,
                "date": meta.get("date") or "",
                "kind": meta.get("kind") or "post",
                "linkedin_url": meta.get("linkedin_url") or "",
                "demo": meta.get("demo") == "true",
                "blurb": blurb,
                "rel": f"./{path.name}",
            }
        )
    posts.sort(key=lambda p: (p["date"], p["title"]), reverse=True)
    return posts


def write_index(output_dir: Path, profile_url: str, posts: List[Dict[str, Any]]) -> None:
    lines = [
        "# Writing",
        "",
        "[← Back to Main Portfolio](../index.md)",
        "",
        "Selected LinkedIn posts and articles mirrored here for the portfolio — comments and reactions stay on LinkedIn.",
        "",
        f"Profile: [{profile_url.replace('https://', '')}]({profile_url})",
        "",
        "---",
        "",
    ]
    if not posts:
        lines.extend(
            [
                "_No imported items yet. Run `./scripts/import-linkedin.sh` after setting `feed_url` or adding inbox JSON._",
                "",
            ]
        )
    else:
        lines.append("| Date | Type | Title |")
        lines.append("| :--- | :--- | :--- |")
        for post in posts:
            kind = post["kind"].capitalize()
            demo = " *(demo)*" if post.get("demo") else ""
            lines.append(f"| {post['date']} | {kind}{demo} | [{post['title']}]({post['rel']}) |")
        lines.append("")
        lines.append("## Recent")
        lines.append("")
        for post in posts[:12]:
            lines.append(f"### [{post['title']}]({post['rel']})")
            lines.append("")
            if post["blurb"]:
                lines.append(post["blurb"])
                lines.append("")
            if post["linkedin_url"]:
                lines.append(f"[Discuss on LinkedIn →]({post['linkedin_url']})")
                lines.append("")
    path = output_dir / "README.md"
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Import LinkedIn content into Writing/")
    parser.add_argument(
        "--config",
        default=str(ROOT / "scripts" / "linkedin.config.json"),
        help="Path to linkedin.config.json",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be imported")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    config = load_config(config_path)

    output_dir = ROOT / config.get("output_dir", "Writing")
    inbox_dir = ROOT / config.get("inbox_dir", "scripts/linkedin-inbox")
    state_path = ROOT / config.get("state_file", "scripts/linkedin-seen.json")
    urls_file = ROOT / config.get("urls_file", "scripts/linkedin-urls.txt")
    max_chars = int(config.get("excerpt_max_chars", 420))
    profile_url = config.get("profile_url", "https://www.linkedin.com/in/zlatko-lakisic/")
    feed_url = (config.get("feed_url") or "").strip()

    state = load_state(state_path)
    seen = set(state.get("ids") or [])

    candidates: List[Dict[str, Any]] = []
    candidates.extend(load_feed(feed_url, max_chars))
    inbox_items, inbox_sources = load_inbox(inbox_dir, max_chars)
    candidates.extend(inbox_items)
    candidates.extend(load_urls_file(urls_file, max_chars))

    # Prefer first occurrence of each id
    ordered: List[Dict[str, Any]] = []
    seen_batch = set()
    for item in candidates:
        if item["id"] in seen_batch:
            continue
        seen_batch.add(item["id"])
        ordered.append(item)

    new_items = [i for i in ordered if i["id"] not in seen]

    if not feed_url and not inbox_items and not any(
        line.strip() and not line.strip().startswith("#") for line in (urls_file.read_text(encoding="utf-8").splitlines() if urls_file.exists() else [])
    ):
        print("No sources configured.")
        print("  • Set feed_url in scripts/linkedin.config.json (RSS.app → your LinkedIn activity), or")
        print("  • Drop *.json into scripts/linkedin-inbox/, or")
        print("  • Add URLs to scripts/linkedin-urls.txt")

    if args.dry_run:
        print(f"Would import {len(new_items)} new item(s) ({len(ordered)} total from sources, {len(seen)} already seen)")
        for item in new_items:
            print(f"  - {item['date']} [{item['kind']}] {item['title'][:80]}")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for item in new_items:
        path = write_post(output_dir, item)
        seen.add(item["id"])
        written += 1
        print(f"Wrote {path.relative_to(ROOT)}")

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
    print(f"Imported {written} new item(s).")
    if not feed_url:
        print("Tip: add an RSS feed_url to scripts/linkedin.config.json for hands-off pulls.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
