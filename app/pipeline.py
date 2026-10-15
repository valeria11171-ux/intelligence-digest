from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha1

from app.intelligence.clustering import cluster_events
from app.intelligence.deduplication import deduplicate
from app.intelligence.extraction import executive_tags, technical_card
from app.intelligence.feedback import feedback_adjustments
from app.intelligence.organizer_rules import infer_category, organizer_importance
from app.intelligence.scoring import final_score
from app.models import DigestEvent, Publication, UserProfile
from app.retrieval.relevance import lexical_relevance
from app.retrieval.semantic import semantic_scores
from app.textutils import evidence_snippet

MIN_SCORE = 0.38
CATEGORY_TOPIC = {"Уязвимость": "Уязвимости", "Атака": "Атаки и инциденты", "Инфо": "Прочее"}


def _novelty(p: Publication, now: datetime) -> float:
    if not p.published_at:
        return 0.6
    dt = p.published_at if p.published_at.tzinfo else p.published_at.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - dt).total_seconds() / 86400)
    return round(max(0.3, 1.0 - 0.7 * min(age_days, 30) / 30), 3)


def _summary(text: str, title: str, max_len: int = 420) -> str:
    text = (text or "").strip()
    if not text:
        return title
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[: end + 1] if end > 160 else cut.rstrip() + "…"


def run_pipeline(
    publications: list[Publication],
    profile: UserProfile,
    limit: int = 10,
    *,
    organizer_boost: bool = True,
    liked: list[Publication] | None = None,
    disliked: list[Publication] | None = None,
) -> list[DigestEvent]:
    """Отбор → группировка по событиям → тематические разделы по интересам пользователя.
    organizer_boost=False — универсальный режим без приоритета РФ/энергетики/КИИ.
    liked/disliked — материалы, оценённые пользователем (обучение на обратной связи)."""
    now = datetime.now(timezone.utc)
    pubs = deduplicate(list({p.url: p for p in publications}.values()))
    sem = semantic_scores(pubs, profile)
    adj = feedback_adjustments(pubs, liked or [], disliked or [])
    ranked: list[tuple[Publication, float, list[str], list[str]]] = []
    for p in pubs:
        lex, hits = lexical_relevance(p, profile)
        if hits and hits[0].startswith("excluded:"):
            continue
        sem_s = min(1.0, max(0.0, sem.get(p.id, 0.0) - 0.08) * 3) * 0.85
        rel = max(lex, sem_s)
        if rel < 0.08:
            continue
        importance, org = organizer_importance(p, organizer_boost)
        extra = list(org)
        if adj.get(p.id, 0) > 0.05:
            extra.append("похоже на понравившееся")
        elif adj.get(p.id, 0) < -0.05:
            extra.append("похоже на отклонённое")
        score = final_score(relevance=rel, importance=importance, user_interest=max(lex, rel * 0.8),
                            novelty=_novelty(p, now), source_trust=p.source_trust) + adj.get(p.id, 0.0)
        score = round(min(1.0, max(0.0, score)), 4)
        if score >= MIN_SCORE:
            ranked.append((p, score, hits, extra))
    ranked.sort(key=lambda x: x[1], reverse=True)
    selected = ranked[: max(limit * 5, limit)]
    meta = {p.id: (s, h, x) for p, s, h, x in selected}

    events: list[DigestEvent] = []
    for items in cluster_events([x[0] for x in selected]):
        items.sort(key=lambda p: meta[p.id][0], reverse=True)
        lead = items[0]
        score = meta[lead.id][0]
        weight: dict[str, float] = defaultdict(float)
        for p in items:
            for h in meta[p.id][1]:
                weight[h] += meta[p.id][0]
        hits = sorted(weight, key=weight.get, reverse=True)
        extra = sorted({r for p in items for r in meta[p.id][2]})
        category = infer_category(lead)
        topic = hits[0] if hits else CATEGORY_TOPIC[category]

        card = dict(technical_card(lead))
        card["cve"] = sorted({c for p in items for c in technical_card(p)["cve"]})
        card["exploit_available"] = any(technical_card(p)["exploit_available"] for p in items)
        tags = sorted({t for p in items for t in executive_tags(p)})
        details = {"tags": tags} if profile.role == "cio" else card
        if profile.role == "cio":
            why = ("Бизнес-сигналы: " + "; ".join(tags[:4])) if tags else "Соответствует интересам руководителя"
        else:
            why = f"Совпадает с интересами: {', '.join(hits[:4])}" if hits else "Технически релевантно профилю"
            if card.get("exploit_available"):
                why += "; есть упоминание exploit/PoC"
        dts = [p.published_at for p in items if p.published_at]
        events.append(DigestEvent(
            id=sha1("".join(sorted(p.id for p in items)).encode()).hexdigest()[:12],
            title=lead.title, category=category, topic=topic,
            summary=_summary(lead.text, lead.title), why_it_matters=why,
            evidence=evidence_snippet(lead.text, hits or profile.interests),
            score=score, publication_ids=[p.id for p in items], sources=[p.url for p in items],
            reasons=list(dict.fromkeys(hits + extra)), details=details,
            links=[{"title": p.title, "url": p.url, "source": p.source,
                    "published_at": p.published_at.isoformat() if p.published_at else ""} for p in items],
            published_at=max(dts) if dts else None,
        ))
    return sorted(events, key=lambda e: e.score, reverse=True)[:limit]
