"""Update every Pulse news site in this repo.

The main site lives in the repo root; sister sites live in sub-folders
(pharma/, startups/, ...). Any folder with its own feeds.json is treated
as a site. For each one this script:
  * reads its RSS/Atom feeds and keeps relevant, tagged headlines,
  * merges them into that folder's news.json (old items age out),
  * writes the latest headlines into that folder's index.html so search
    engines can read them without JavaScript.
Finally it writes one sitemap.xml listing every site.

Uses only Python's standard library, so there is nothing to install.
Only headlines, a short snippet, source, date and link are kept.
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
IST = timezone(timedelta(hours=5, minutes=30))
ATOM = "{http://www.w3.org/2005/Atom}"
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
START, END = "<!--NEWS-START-->", "<!--NEWS-END-->"


# ---------- helpers ----------

def clean(text):
    text = html.unescape(TAG_RE.sub(" ", text or ""))
    return SPACE_RE.sub(" ", text).strip()


def norm_key(title):
    return re.sub(r"[^a-z0-9]", "", title.lower())[:90]


def parse_date(value):
    value = clean(value)
    if not value:
        return datetime.now(timezone.utc)
    try:  # RSS style: "Wed, 07 Oct 2026 10:00:00 GMT"
        d = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        d = None
    if d is None:
        try:  # Atom style: "2026-10-07T10:00:00Z"
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            d = None
    if d is None:  # Fierce style: "Oct 7, 2026 2:29pm" (US Eastern)
        try:
            d = datetime.strptime(value.upper(), "%b %d, %Y %I:%M%p")
            d = d.replace(tzinfo=timezone(timedelta(hours=-4)))
        except ValueError:
            return datetime.now(timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def text_of(el):
    """Full text of an element, including any HTML tags some feeds put inside."""
    return "".join(el.itertext()) if el is not None else ""


def parse_feed(xml_bytes):
    """Return a list of dicts with title, link, summary, date, source from RSS or Atom."""
    root = ET.fromstring(xml_bytes)
    entries = []
    for it in root.iter("item"):  # RSS 2.0
        link = (it.findtext("link") or "").strip()
        if not link:  # some feeds put the link only inside the title's <a>
            a = it.find("title/a")
            link = a.get("href", "") if a is not None else ""
        entries.append({
            "title": text_of(it.find("title")),
            "link": link,
            "summary": text_of(it.find("description")),
            "date": it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date"),
            "source": it.findtext("source"),
        })
    for it in root.iter(ATOM + "entry"):  # Atom
        link_el = it.find(ATOM + "link[@rel='alternate']")
        if link_el is None:
            link_el = it.find(ATOM + "link")
        entries.append({
            "title": text_of(it.find(ATOM + "title")),
            "link": link_el.get("href", "") if link_el is not None else "",
            "summary": text_of(it.find(ATOM + "summary")) or text_of(it.find(ATOM + "content")),
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


# ---------- one site ----------

class Site:
    def __init__(self, folder):
        self.folder = folder
        self.cfg = json.loads((folder / "feeds.json").read_text(encoding="utf-8"))
        self.name = self.cfg.get("site_title", folder.name)

    def _low(self, text):
        return " " + text.lower() + " "  # padding lets words like " ai " match at the edges

    def tag_item(self, text):
        low = self._low(text)
        tags = [name for name, words in self.cfg["tags"].items() if any(w in low for w in words)]
        return tags or ["General"]

    def relevant(self, text):
        low = self._low(text)
        return any(w in low for w in self.cfg["must_match_any"])

    def excluded(self, title, source):
        """Skip paywalled outlets (by source name) and unwanted title markers like 'STAT+'."""
        src = source.strip().lower()
        if any(src == x.lower() for x in self.cfg.get("exclude_sources", [])):
            return True
        low = title.lower()
        return any(x.lower() in low for x in self.cfg.get("exclude_any", []))

    def to_items(self, entries, feed_name):
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
            if not self.relevant(text) or self.excluded(title, source):
                continue
            items.append({
                "title": title,
                "link": link,
                "source": source,
                "snippet": snippet,
                "date": parse_date(e["date"]).isoformat(),
                "tags": self.tag_item(text),
            })
        return items

    def fetch_all(self):
        items = []
        for feed in self.cfg["feeds"]:
            try:
                entries = parse_feed(fetch(feed["url"]))
            except Exception as exc:  # one bad feed never stops the run
                print(f"  !! {feed['name']}: {exc}", file=sys.stderr)
                continue
            new = self.to_items(entries, feed["name"])
            print(f"  {feed['name']}: {len(entries)} entries, {len(new)} kept")
            items += new
        return items

    def build(self, new_items):
        out = self.folder / "news.json"
        old = []
        if out.exists():
            try:
                old = json.loads(out.read_text(encoding="utf-8")).get("items", [])
            except Exception:
                old = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.cfg["keep_days"])
        merged = {}
        for item in old + new_items:  # newer copy overwrites older one
            if datetime.fromisoformat(item["date"]) < cutoff:
                continue
            if self.excluded(item["title"], item["source"]):  # also clears out stories saved before a source was blocked
                continue
            merged[norm_key(item["title"])] = item
        items = sorted(merged.values(), key=lambda i: i["date"], reverse=True)[: self.cfg["max_items"]]
        out.write_text(json.dumps({
            "title": self.cfg["site_title"],
            "tagline": self.cfg["site_tagline"],
            "updated": datetime.now(timezone.utc).isoformat(),
            "tags": list(self.cfg["tags"].keys()),
            "items": items,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  Wrote {len(items)} items to {out.relative_to(ROOT)}")
        self.write_static_html(items)

    def write_static_html(self, items, limit=60):
        """Put the latest headlines into index.html so search engines can read
        them without JavaScript. The page's script swaps in the full list."""
        page_path = self.folder / "index.html"
        if not page_path.exists():
            return
        page = page_path.read_text(encoding="utf-8")
        if START not in page or END not in page:
            print(f"  !! {page_path.relative_to(ROOT)} has no NEWS markers; skipped", file=sys.stderr)
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
        page_path.write_text(before + START + "\n" + "\n".join(parts) + "\n" + END + after, encoding="utf-8")


# ---------- all sites ----------

def find_sites():
    sites = [Site(ROOT)] if (ROOT / "feeds.json").exists() else []
    for sub in sorted(p for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith(".")):
        if (sub / "feeds.json").exists():
            sites.append(Site(sub))
    return sites


def write_sitemap(sites):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = []
    for s in sites:
        url = s.cfg.get("site_url")
        if url:
            pri = "1.0" if s.folder == ROOT else "0.7"
            rows.append(f"  <url><loc>{html.escape(url)}</loc><lastmod>{today}</lastmod>"
                        f"<changefreq>hourly</changefreq><priority>{pri}</priority></url>")
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(rows) + "\n</urlset>\n", encoding="utf-8")


def main():
    sites = find_sites()
    for s in sites:
        print(f"== {s.name}")
        s.build(s.fetch_all())
    write_sitemap(sites)


if __name__ == "__main__":
    main()
