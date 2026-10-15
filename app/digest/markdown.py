from __future__ import annotations
from datetime import datetime
from app.digest.common import AUDIENCE, detail_line, fmt_date, group_by_topic, key_figures
from app.models import DigestEvent, UserProfile


def render_markdown(events: list[DigestEvent], profile: UserProfile, meta: dict | None = None) -> str:
    """meta: {period_label, generated_at, publications_in, sources_ok, sources_total}"""
    meta = meta or {}
    title = "Ежемесячный дайджест" if meta.get("period_label") == "Месяц" else "Ежедневный дайджест" if meta.get("period_label") == "День" else "Дайджест"
    L = [f"# {title} ИТ/ИБ — {AUDIENCE.get(profile.role, profile.role)}", ""]
    L.append(f"*Сформирован: {(meta.get('generated_at') or datetime.now()).strftime('%d.%m.%Y %H:%M')}"
             + (f" · период: {meta['period_label']}" if meta.get("period_label") else "") + "*  ")
    L.append(f"*Интересы: {', '.join(profile.interests) or 'не заданы'}*")
    if meta.get("sources_total"):
        L.append(f"  \n*Источники: {meta.get('sources_ok', 0)} из {meta['sources_total']} доступны · "
                 f"просмотрено публикаций: {meta.get('publications_in', 0)}*")
    L.append("")
    if profile.role == "cio" or meta.get("period_label") == "Месяц":
        k = key_figures(events)
        L += ["## Ключевые цифры", "",
              f"- Событий в дайджесте: **{k['events']}** (на основе {k['publications']} публикаций)",
              f"- Уязвимости: **{k['vulnerabilities']}**, атаки и инциденты: **{k['attacks']}**, с публичным exploit/PoC: **{k['with_exploit']}**", ""]
        top = sorted(events, key=lambda e: e.score, reverse=True)[:3]
        if top:
            L += ["## Главное", ""] + [f"{i}. **{e.title}** — {e.why_it_matters}" for i, e in enumerate(top, 1)] + [""]
    if not events:
        L += ["_По заданным интересам и периоду релевантных материалов не найдено._", ""]
    for topic, items in group_by_topic(events).items():
        L += [f"## {topic}", ""]
        for e in items:
            date = fmt_date(e.published_at)
            L += [f"### {e.title}", "", f"*{e.category}" + (f" · {date}" if date else "") + f" · релевантность {e.score:.0%}*", "", e.summary, ""]
            L.append(f"**Почему важно:** {e.why_it_matters}")
            if detail_line(e):
                L.append(f"  \n**Детали:** {detail_line(e)}")
            if e.evidence:
                L += ["", f"> {e.evidence}"]
            L += ["", f"**Источники ({len(e.links) or len(e.sources)}):**"]
            if e.links:
                for l in e.links:
                    d = fmt_date(l.get("published_at"))
                    L.append(f"- [{l['source']}: {l['title']}]({l['url']})" + (f" — {d}" if d else ""))
            else:
                L += [f"- {s}" for s in e.sources]
            L.append("")
    return "\n".join(L)
