"""Fetch IP / tech-transfer news from RSS/Atom feeds and write news.json.

Uses only Python's standard library, so there is nothing to install.
Keeps only headline, short snippet, source, date and link (no full articles).
Merges with the existing news.json so older items stay until they age out.
"""
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "feeds.json").read_text(encoding="utf-8"))
OUT = ROOT / "news.json"

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
ATOM = "{http://www.w3.org/2005/Atom}"


def clean(text):
    text = html.unescape(TAG_RE.sub(" ", text or ""))
    return SPACE_RE.sub(" ", text).strip()


def norm_key(title):
    return re.sub(r"[^a-z0-9]", "", title.lower())[:90]


def parse_date(value):
    value = (value or "").strip()
    if not value:
        return datetime.now(timezone.utc)
    try:  # RSS style: "Wed, 07 Oct 2026 10:00:00 GMT"
        d = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:  # Atom style: "2026-10-07T10:00:00Z"
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def parse_feed(xml_bytes):
    """Return a list of dicts with title, link, summary, date from RSS or Atom."""
    root = ET.fromstring(xml_bytes)
    entries = []
    for it in root.iter("item"):  # RSS 2.0
        entries.append({
            "title": it.findtext("title"),
            "link": (it.findtext("link") or "").strip(),
            "summary": it.findtext("description"),
            "date": it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date"),
            "source": it.findtext("source"),
        })
    for it in root.iter(ATOM + "entry"):  # Atom
        link_el = it.find(ATOM + "link[@rel='alternate']")
        if link_el is None:
            link_el = it.find(ATOM + "link")
        entries.append({
            "title": it.findtext(ATOM + "title"),
            "link": link_el.get("href", "") if link_el is not None else "",
            "summary": it.findtext(ATOM + "summary") or it.findtext(ATOM + "content"),
            "date": it.findtext(ATOM + "published") or it.findtext(ATOM + "updated"),
            "source": None,
        })
    return entries


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (IP-News-Bot)"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()


def split_google_title(title, feed_name, source_el):
    # Google News titles look like "Headline - Publisher"
    if feed_name.startswith("Google News") and " - " in title:
        head, _, pub = title.rpartition(" - ")
        if head and len(pub) < 60:
            return head.strip(), clean(source_el) or pub.strip()
    return title, feed_name


def tag_item(text):
    low = text.lower()
    tags = [name for name, words in CONFIG["tags"].items() if any(w in low for w in words)]
    return tags or ["General"]


def relevant(text):
    low = text.lower()
    return any(w in low for w in CONFIG["must_match_any"])


def to_items(entries, feed_name):
    items = []
    for e in entries:
        raw_title, link = clean(e["title"]), e["link"]
        if not raw_title or not link:
            continue
        title, source = split_google_title(raw_title, feed_name, e["source"])
        snippet = clean(e["summary"])
        # Google News summaries just repeat the headline; drop those
        if norm_key(snippet).startswith(norm_key(title)[:40]):
            snippet = ""
        if len(snippet) > 220:
            snippet = snippet[:217].rsplit(" ", 1)[0] + "…"
        text = f"{title} {snippet}"
        if not relevant(text):
            continue
        items.append({
            "title": title,
            "link": link,
            "source": source,
            "snippet": snippet,
            "date": parse_date(e["date"]).isoformat(),
            "tags": tag_item(text),
        })
    return items


def fetch_all():
    items = []
    for feed in CONFIG["feeds"]:
        try:
            entries = parse_feed(fetch(feed["url"]))
        except Exception as exc:  # one bad feed never stops the run
            print(f"!! {feed['name']}: {exc}", file=sys.stderr)
            continue
        new = to_items(entries, feed["name"])
        print(f"{feed['name']}: {len(entries)} entries, {len(new)} kept")
        items += new
    return items


def build(new_items):
    old = []
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8")).get("items", [])
        except Exception:
            old = []

    cutoff = datetime.now(timezone.utc) - timedelta(days=CONFIG["keep_days"])
    merged = {}
    for item in old + new_items:  # newer copy overwrites older one
        if datetime.fromisoformat(item["date"]) < cutoff:
            continue
        merged[norm_key(item["title"])] = item

    items = sorted(merged.values(), key=lambda i: i["date"], reverse=True)[: CONFIG["max_items"]]
    OUT.write_text(json.dumps({
        "title": CONFIG["site_title"],
        "tagline": CONFIG["site_tagline"],
        "updated": datetime.now(timezone.utc).isoformat(),
        "tags": list(CONFIG["tags"].keys()),
        "items": items,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Wrote {len(items)} items to {OUT.name}")
    write_static_html(items)
    write_sitemap()


IST = timezone(timedelta(hours=5, minutes=30))
PAGE = ROOT / "index.html"
START, END = "<!--NEWS-START-->", "<!--NEWS-END-->"


def write_static_html(items, limit=60):
    """Put the latest headlines straight into index.html so search engines
    can read them without running JavaScript. The page's script replaces
    this list with the full, filterable one when it loads."""
    if not PAGE.exists():
        return
    page = PAGE.read_text(encoding="utf-8")
    if START not in page or END not in page:
        print("!! index.html has no NEWS markers; skipped static headlines", file=sys.stderr)
        return
    esc = lambda s: html.escape(str(s), quote=True)
    parts, last_day = [], ""
    for i in items[:limit]:
        d = datetime.fromisoformat(i["date"]).astimezone(IST)
        day = d.strftime("%A %-d %B")
        if day != last_day:
            parts.append(f'<div class="day">{esc(day)}</div>')
            last_day = day
        chips = "".join(
            f'<span class="chip{" india" if t == "India" else ""}">{esc(t)}</span>' for t in i["tags"])
        snippet = f'<p class="snippet">{esc(i["snippet"])}</p>' if i["snippet"] else ""
        parts.append(
            f'<article><a class="title" href="{esc(i["link"])}" target="_blank" rel="noopener">{esc(i["title"])}</a>'
            f'<div class="meta">{esc(i["source"])} · <time datetime="{esc(i["date"])}">{d.strftime("%-I:%M %p").lower()}</time></div>'
            f'{snippet}<div class="chips">{chips}</div></article>')
    before, rest = page.split(START, 1)
    after = rest.split(END, 1)[1]
    PAGE.write_text(before + START + "\n" + "\n".join(parts) + "\n" + END + after, encoding="utf-8")
    print(f"Wrote {min(len(items), limit)} headlines into {PAGE.name}")


def write_sitemap():
    url = CONFIG.get("site_url")
    if not url:
        return
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{html.escape(url)}</loc><lastmod>{today}</lastmod>"
        "<changefreq>hourly</changefreq><priority>1.0</priority></url>\n"
        "</urlset>\n", encoding="utf-8")


if __name__ == "__main__":
    build(fetch_all())
