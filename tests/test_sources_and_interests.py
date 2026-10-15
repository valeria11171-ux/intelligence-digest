import threading
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest

from app.digest.markdown import render_markdown
from app.intelligence.feedback import apply_feedback
from app.models import Publication, Source, UserProfile
from app.pipeline import run_pipeline
from app.sources import detect_source, fetch_all, normalize_telegram, parse_feed, parse_telegram
from app.textutils import term_regex

NOW = datetime.now(timezone.utc)


def pub(i, title, text="", days_ago=0, source="S", url=None):
    return Publication(id=str(i), title=title, url=url or f"https://x.test/{i}", source=source,
                       text=text, published_at=NOW - timedelta(days=days_ago))


FEED = """<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>
<item><title>Critical CVE-2026-1111 in Exchange</title><link>https://a.test/1</link>
<description>&lt;p&gt;Patch now. Public exploit available.&lt;/p&gt;</description><pubDate>{d}</pubDate></item></channel></rss>"""
TG = """<div class="tgme_widget_message" data-post="chan/12"><div class="tgme_widget_message_text">Уязвимость в Kubernetes: обновите кластеры сегодня.<br/>Подробности и CVE-2026-2222</div><time datetime="2026-10-14T09:00:00+00:00"></time></div>"""


def test_rss_and_telegram_parsing():
    s = Source(name="T", url="x")
    items = parse_feed(FEED.format(d="Wed, 14 Oct 2026 10:00:00 GMT"), s)
    assert items[0].text.startswith("Patch now") and "<" not in items[0].text and items[0].published_at
    tg = parse_telegram(TG, s)
    assert tg[0].url == "https://t.me/chan/12" and "Kubernetes" in tg[0].title
    assert normalize_telegram("@true_secator") == "https://t.me/s/true_secator"


@pytest.fixture()
def local_site(tmp_path):
    (tmp_path / "feed.xml").write_text(FEED.format(d=NOW.strftime("%a, %d %b %Y %H:%M:%S GMT")), encoding="utf-8")
    (tmp_path / "index.html").write_text('<html><head><title>Blog</title><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head><body></body></html>')
    (tmp_path / "article.html").write_text("<html><head><title>Post</title></head><body><article><p>Ransomware hit a hospital network last week.</p></article></body></html>")
    srv = HTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_add_source_autodetect_and_fetch_all(local_site):
    src, sample = detect_source(local_site + "/index.html", "Мой блог")      # RSS найден на странице сайта
    assert src.kind == "rss" and src.url.endswith("/feed.xml") and sample
    page, ps = detect_source(local_site + "/article.html")                    # обычная страница
    assert page.kind == "page" and "Ransomware" in ps[0].text
    bad = Source(name="Broken", url="http://127.0.0.1:1/none.xml")
    pubs, status = fetch_all([src, bad], days=3)                              # сбой одного источника не ломает остальные
    assert len(pubs) == 1 and {s["name"]: s["ok"] for s in status} == {"Мой блог": True, "Broken": False}
    assert pubs[0].source_trust == src.trust


def test_custom_interests_russian_morphology():
    assert term_regex("уязвимость").search("Найдены критические уязвимости в сервере")
    pubs = [pub(1, "Утечка данных клиентов крупного банка", "Злоумышленники опубликовали базу."),
            pub(2, "Новый смартфон со складным экраном", "Обзор камеры.")]
    ev = run_pipeline(pubs, UserProfile(interests=["утечка данных"]), organizer_boost=False)
    assert [e.title for e in ev] == [pubs[0].title] and ev[0].topic == "утечка данных"   # свой интерес = своя тема


def test_new_interest_changes_digest_and_topics():
    pubs = [pub(1, "Critical Exchange flaw exploited", "Microsoft Exchange servers attacked."),
            pub(2, "Docker image supply chain attack", "Malicious Docker images found on registry.")]
    a = run_pipeline(pubs, UserProfile(interests=["Exchange"]), organizer_boost=False)
    b = run_pipeline(pubs, UserProfile(interests=["Docker"]), organizer_boost=False)
    assert a[0].title != b[0].title


def test_exclusions_never_leak_via_semantics():
    pubs = [pub(1, "Gaming smartphone exploit", "CVE-2026-1 gaming phone vulnerability")]
    assert run_pipeline(pubs, UserProfile(interests=["CVE"], exclusions=["gaming"])) == []


def test_same_event_from_two_sources_is_merged():
    pubs = [pub(1, "Hackers exploit CVE-2026-9999 in VPN appliances", "Details.", source="A"),
            pub(2, "Массовая эксплуатация VPN: CVE-2026-9999", "Подробности.", source="B")]
    ev = run_pipeline(pubs, UserProfile(interests=["CVE"]), organizer_boost=False)
    assert len(ev) == 1 and len(ev[0].links) == 2 and ev[0].details["cve"] == ["CVE-2026-9999"]


def test_feedback_learning_reorders_digest():
    pubs = [pub(1, "Ransomware gang hits hospital", "Ransomware attack on hospital network."),
            pub(2, "Ransomware targets logistics firm", "Ransomware attack on a logistics company.")]
    base = run_pipeline(pubs, UserProfile(interests=["ransomware"]), organizer_boost=False)
    worse = run_pipeline(pubs, UserProfile(interests=["ransomware"]), organizer_boost=False, disliked=[pubs[0]])
    assert {e.title: e.score for e in worse}.get(pubs[0].title, 0) < {e.title: e.score for e in base}[pubs[0].title]
    p = apply_feedback(UserProfile(interests=["ransomware"]), ["ransomware"], False)
    assert p.priorities["ransomware"] < 1.0


def test_markdown_has_links_quote_and_sections():
    pubs = [pub(1, "Critical CVE-2026-1 in Exchange", "Critical flaw in Exchange. Public exploit exists. Patch now.", url="https://a.test/1")]
    prof = UserProfile(interests=["Exchange"])
    md = render_markdown(run_pipeline(pubs, prof, organizer_boost=False), prof, {"period_label": "День"})
    assert "Ежедневный дайджест" in md and "## Exchange" in md and "](https://a.test/1)" in md and "> " in md and "exploit" in md
