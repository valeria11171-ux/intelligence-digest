"""Источники: реестр, добавление пользователем, параллельный сбор и статус по каждому источнику."""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha1
from pathlib import Path
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
import yaml
from bs4 import BeautifulSoup

from app.models import Publication, Source
from app.textutils import clean_html, detect_lang

ROOT = Path(__file__).resolve().parents[1]
UA = {"User-Agent": "Mozilla/5.0 (compatible; IntelligenceDigest/2.0; +https://github.com/valeria11171-ux/intelligence-digest)"}
TIMEOUT = 12.0


def pub_id(url: str) -> str:
    return sha1(url.strip().encode()).hexdigest()[:16]


def load_default_sources(path: Path | None = None) -> list[Source]:
    path = path or ROOT / "configs" / "sources.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [Source(**s) for s in data.get("sources", [])]


def _get(url: str) -> httpx.Response:
    r = httpx.get(url, timeout=TIMEOUT, follow_redirects=True, headers=UA)
    r.raise_for_status()
    return r


# ───────────────────────── RSS / Atom ─────────────────────────
def _entry_dt(e) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        t = e.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def parse_feed(content: bytes | str, src: Source, limit: int = 40) -> list[Publication]:
    feed = feedparser.parse(content)
    out: list[Publication] = []
    for e in feed.entries[:limit]:
        link, title = (e.get("link") or "").strip(), clean_html(e.get("title", ""))
        if not link or not title:
            continue
        body = e.get("summary") or e.get("description") or ""
        if not body and e.get("content"):
            body = e["content"][0].get("value", "")
        text = clean_html(body)
        out.append(Publication(id=pub_id(link), title=title, url=link, source=src.name,
                               published_at=_entry_dt(e), text=text, language=detect_lang(title + " " + text)))
    return out


def fetch_rss(src: Source, limit: int = 40) -> list[Publication]:
    return parse_feed(_get(src.url).content, src, limit)


# ───────────────────────── Telegram (публичный web-preview t.me/s/<канал>) ─────────────────────────
def normalize_telegram(url: str) -> str | None:
    m = re.match(r"^(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z0-9_]{4,})/?", url.strip()) or \
        re.match(r"^@([A-Za-z0-9_]{4,})$", url.strip())
    return f"https://t.me/s/{m.group(1)}" if m else None


def parse_telegram(html_text: str, src: Source, limit: int = 40) -> list[Publication]:
    soup = BeautifulSoup(html_text, "html.parser")
    out: list[Publication] = []
    for msg in soup.select("div.tgme_widget_message")[-limit:]:
        post = msg.get("data-post")
        body = msg.select_one(".tgme_widget_message_text")
        if not post or not body:
            continue
        for br in body.find_all("br"):
            br.replace_with("\n")
        text = re.sub(r"[ \t]+", " ", body.get_text()).strip()
        if len(text) < 30:
            continue
        first = text.split("\n")[0].strip()
        title = first if 15 <= len(first) <= 160 else text[:140].rstrip() + "…"
        t = msg.select_one("time[datetime]")
        dt = None
        if t:
            try:
                dt = datetime.fromisoformat(t["datetime"]).astimezone(timezone.utc)
            except ValueError:
                pass
        url = f"https://t.me/{post}"
        out.append(Publication(id=pub_id(url), title=title, url=url, source=src.name,
                               published_at=dt, text=" ".join(text.split()), language=detect_lang(text)))
    return list(reversed(out))


def fetch_telegram(src: Source, limit: int = 40) -> list[Publication]:
    url = normalize_telegram(src.url)
    if not url:
        raise ValueError("Не похоже на ссылку Telegram-канала (t.me/<канал>)")
    return parse_telegram(_get(url).text, src, limit)


# ───────────────────────── Отдельная страница / автопоиск RSS ─────────────────────────
def discover_feed(html_text: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html_text, "html.parser")
    for link in soup.find_all("link", rel=lambda r: r and "alternate" in r):
        if (link.get("type") or "").lower() in ("application/rss+xml", "application/atom+xml") and link.get("href"):
            return urljoin(base_url, link["href"])
    return None


def parse_page(html_text: str, url: str, src: Source) -> list[Publication]:
    soup = BeautifulSoup(html_text, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "header", "aside"]):
        t.decompose()
    title = (soup.title.get_text(strip=True) if soup.title else "") or url
    root = soup.find("article") or soup.find("main") or soup.body or soup
    text = " ".join(p.get_text(" ", strip=True) for p in root.find_all("p")) or root.get_text(" ", strip=True)
    text = " ".join(text.split())[:6000]
    return [Publication(id=pub_id(url), title=clean_html(title), url=url, source=src.name, text=text,
                        language=detect_lang(title + " " + text))]


def fetch_page(src: Source, limit: int = 1) -> list[Publication]:
    r = _get(src.url)
    return parse_page(r.text, str(r.url), src)


FETCHERS = {"rss": fetch_rss, "telegram": fetch_telegram, "page": fetch_page}


def detect_source(url: str, name: str = "") -> tuple[Source, list[Publication]]:
    """Определяет тип по ссылке: Telegram → RSS → RSS, найденный на сайте → одиночная страница.
    Возвращает готовый Source и пробную выборку (для проверки перед добавлением)."""
    url = url.strip()
    if not re.match(r"^https?://", url) and not url.startswith("@"):
        url = "https://" + url
    host = urlparse(url).netloc or url
    if normalize_telegram(url):
        s = Source(name=name or f"Telegram — {normalize_telegram(url).rsplit('/', 1)[-1]}", url=normalize_telegram(url), kind="telegram", trust=0.7)
        return s, fetch_telegram(s)
    r = _get(url)
    s = Source(name=name or host, url=str(r.url), kind="rss")
    items = parse_feed(r.content, s)
    if items:
        return s, items
    feed_url = discover_feed(r.text, str(r.url))
    if feed_url:
        s = Source(name=name or host, url=feed_url, kind="rss")
        items = fetch_rss(s)
        if items:
            return s, items
    s = Source(name=name or host, url=str(r.url), kind="page")
    return s, parse_page(r.text, str(r.url), s)


# ───────────────────────── Параллельный сбор ─────────────────────────
def _fetch_one(src: Source) -> tuple[Source, list[Publication], dict]:
    t0 = time.time()
    try:
        items = FETCHERS[src.kind](src)
        return src, items, {"name": src.name, "kind": src.kind, "url": src.url, "ok": True,
                            "count": len(items), "error": "", "ms": int((time.time() - t0) * 1000)}
    except Exception as exc:  # статус виден пользователю, остальные источники продолжают работать
        return src, [], {"name": src.name, "kind": src.kind, "url": src.url, "ok": False,
                         "count": 0, "error": f"{type(exc).__name__}: {str(exc)[:120]}", "ms": int((time.time() - t0) * 1000)}


def fetch_all(sources: list[Source], days: int | None = None, workers: int = 8) -> tuple[list[Publication], list[dict]]:
    active = [s for s in sources if s.enabled]
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(active) or 1))) as ex:
        results = list(ex.map(_fetch_one, active))
    pubs: dict[str, Publication] = {}
    statuses = []
    for src, items, status in results:
        statuses.append(status)
        for p in items:
            p.source_trust = src.trust
            pubs.setdefault(p.id, p)
    out = list(pubs.values())
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        out = [p for p in out if p.published_at is None or p.published_at >= cutoff]
    out.sort(key=lambda p: p.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    statuses.sort(key=lambda s: (s["ok"], s["name"]))
    return out, statuses
