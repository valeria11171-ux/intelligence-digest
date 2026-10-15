"""CLI: python -m app.cli --audience tech --period day --out artifacts/digest.md [--docx] [--demo]"""
from __future__ import annotations
import argparse, json
from datetime import datetime
from pathlib import Path
from app.digest.docx_export import export_docx
from app.digest.markdown import render_markdown
from app.models import Publication, UserProfile
from app.pipeline import run_pipeline
from app.sources import detect_source, fetch_all, load_default_sources

PERIODS = {"day": ("День", 1), "week": ("Неделя", 7), "month": ("Месяц", 30)}
DEFAULT_INTERESTS = {"tech": ["CVE", "уязвимость", "ransomware", "эксплойт"], "mgmt": ["AI", "cloud", "regulation", "утечка"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Генератор ИТ/ИБ-дайджеста")
    ap.add_argument("--audience", choices=["tech", "mgmt"], default="tech")
    ap.add_argument("--period", choices=list(PERIODS), default=None, help="по умолчанию: tech=day, mgmt=month")
    ap.add_argument("--interests", help="через запятую; можно любые, напр. 'Exchange,Kubernetes,утечка данных'")
    ap.add_argument("--exclude", default="", help="исключения через запятую")
    ap.add_argument("--add-source", action="append", default=[], help="URL сайта/RSS/Telegram-канала (можно несколько раз)")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--organizer-boost", action="store_true", help="приоритет РФ/энергетика/КИИ")
    ap.add_argument("--demo", action="store_true", help="использовать встроенный демо-корпус (без сети)")
    ap.add_argument("--out", default="artifacts/digest.md")
    ap.add_argument("--docx", action="store_true", help="дополнительно сохранить DOCX")
    a = ap.parse_args(argv)

    period = a.period or ("day" if a.audience == "tech" else "month")
    label, days = PERIODS[period]
    role = "security_engineer" if a.audience == "tech" else "cio"
    interests = [x.strip() for x in (a.interests or ",".join(DEFAULT_INTERESTS[a.audience])).split(",") if x.strip()]
    profile = UserProfile(role=role, interests=interests, exclusions=[x.strip() for x in a.exclude.split(",") if x.strip()])

    meta = {"period_label": label, "generated_at": datetime.now()}
    if a.demo:
        root = Path(__file__).resolve().parents[1]
        pubs = [Publication(**x) for x in json.loads((root / "data/samples/publications.json").read_text(encoding="utf-8"))]
    else:
        sources = load_default_sources()
        for url in a.add_source:
            try:
                sources.append(detect_source(url)[0])
            except Exception as exc:
                print(f"! не удалось добавить {url}: {exc}")
        pubs, status = fetch_all(sources, days)
        meta.update(sources_ok=sum(s["ok"] for s in status), sources_total=len(status))
        for s in status:
            print(("✓" if s["ok"] else "✗"), s["name"], s["count"], s["error"])
    meta["publications_in"] = len(pubs)
    events = run_pipeline(pubs, profile, a.limit, organizer_boost=a.organizer_boost)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(events, profile, meta), encoding="utf-8")
    if a.docx:
        export_docx(events, profile, out.with_suffix(".docx"), meta)
    print(f"Публикаций: {len(pubs)} → событий: {len(events)} → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
