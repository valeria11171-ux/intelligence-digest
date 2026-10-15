from __future__ import annotations
from collections import Counter
from datetime import datetime
from app.models import DigestEvent, UserProfile

AUDIENCE = {"security_engineer": "ИБ / ИТ специалист", "cio": "Руководитель"}


def group_by_topic(events: list[DigestEvent]) -> dict[str, list[DigestEvent]]:
    """Тематические разделы; порядок — по максимальной оценке события в разделе."""
    groups: dict[str, list[DigestEvent]] = {}
    for e in sorted(events, key=lambda x: x.score, reverse=True):
        groups.setdefault(e.topic or "Прочее", []).append(e)
    return groups


def fmt_date(iso_or_dt) -> str:
    if not iso_or_dt:
        return ""
    dt = iso_or_dt if isinstance(iso_or_dt, datetime) else datetime.fromisoformat(iso_or_dt)
    return dt.strftime("%d.%m.%Y")


def detail_line(e: DigestEvent) -> str:
    d, bits = e.details or {}, []
    if d.get("cve"):
        bits.append("CVE: " + ", ".join(d["cve"]))
    if d.get("cvss") is not None:
        bits.append(f"CVSS: {d['cvss']}")
    if d.get("exploit_available"):
        bits.append("есть exploit/PoC")
    if d.get("tags"):
        bits.append("Бизнес-сигналы: " + ", ".join(d["tags"]))
    return " · ".join(bits)


def key_figures(events: list[DigestEvent]) -> dict:
    cats = Counter(e.category for e in events)
    return {"events": len(events), "publications": sum(len(e.publication_ids) for e in events),
            "vulnerabilities": cats.get("Уязвимость", 0), "attacks": cats.get("Атака", 0),
            "with_exploit": sum(1 for e in events if (e.details or {}).get("exploit_available"))}
