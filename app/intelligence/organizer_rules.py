"""Deterministic organizer-aligned signals used before/alongside an LLM judge."""
from __future__ import annotations
import re
from app.models import Publication

ENERGY = ("энергет", "energy", "scada", "ics", "кии", "critical infrastructure", "промышлен")
RUSSIA = ("росси", " рф", "russia", "russian")
EXPLOIT = ("exploit", "эксплойт", "poc", "proof of concept", "known exploited")
CVE = re.compile(r"CVE-\d{4}-\d{4,7}", re.I)


def infer_category(pub: Publication) -> str:
    text = f"{pub.title} {pub.text}".lower()
    if CVE.search(text) or any(x in text for x in ("cve", "уязвим", "vulnerab", "cvss")): return "Уязвимость"
    if any(x in text for x in ("атак", "campaign", "threat actor", "ransomware", "фишинг", "malware")): return "Атака"
    return "Инфо"


def organizer_importance(pub: Publication, boost: bool = True) -> tuple[float, list[str]]:
    """boost=False — универсальный режим (без приоритета РФ/энергетики/КИИ)."""
    text = f" {pub.title} {pub.text}".lower()
    cat = infer_category(pub)
    reasons: list[str] = []
    score = 0.45
    if boost and any(x in text for x in RUSSIA): score += .15; reasons.append("РФ")
    if boost and any(x in text for x in ENERGY): score += .20; reasons.append("энергетика/КИИ/промышленность")
    if cat == "Уязвимость" and any(x in text for x in EXPLOIT): score += .20; reasons.append("есть exploit/PoC")
    if any(x in text for x in ("critical", "критичес", "cvss 9", "cvss: 9", "cvss 10")): score += .10; reasons.append("критическая тяжесть")
    return min(score, 1.0), reasons
