from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import streamlit as st

from app.digest.common import AUDIENCE, detail_line, fmt_date, group_by_topic
from app.digest.docx_export import export_docx
from app.digest.markdown import render_markdown
from app.intelligence.feedback import apply_feedback
from app.models import Publication, Source, UserProfile
from app.pipeline import run_pipeline
from app.sources import detect_source, fetch_all, load_default_sources

ROOT = Path(__file__).resolve().parents[1]
st.set_page_config(page_title="Intelligence Digest", page_icon="◈", layout="wide")

PERIODS = {"День": 1, "Неделя": 7, "Месяц": 30}
ROLE_DEFAULT_PERIOD = {"security_engineer": "День", "cio": "Месяц"}
DEFAULTS = {
    "security_engineer": ["CVE", "уязвимость", "ransomware", "эксплойт"],
    "cio": ["AI", "cloud", "regulation", "утечка данных"],
}
PRESETS = ["CVE", "уязвимость", "ransomware", "эксплойт", "Microsoft", "Kubernetes", "Exchange", "SCADA",
           "AI", "cloud", "regulation", "утечка данных", "DDoS", "фишинг"]

st.markdown("""<style>
.block-container {max-width: 1280px; padding-top: 2rem;}
.small-muted {color:#8b949e;font-size:.9rem}
.quote {border-left:3px solid #4b8bf5;padding:.2rem .8rem;color:#9aa4b2;font-style:italic;margin:.4rem 0}
</style>""", unsafe_allow_html=True)

# ───────────── состояние ─────────────
S = st.session_state
S.setdefault("sources", [s.model_dump() for s in load_default_sources()])
S.setdefault("custom_interests", [])
S.setdefault("priorities", {})
S.setdefault("liked", {})      # id публикации -> dict
S.setdefault("disliked", {})


def add_interests() -> None:
    for term in [t.strip() for t in S.get("new_interest", "").split(",") if t.strip()]:
        if term not in S.custom_interests and term not in PRESETS:
            S.custom_interests.append(term)
        if term not in S.get("interests", []):
            S["interests"] = S.get("interests", []) + [term]
    S["new_interest"] = ""


@st.cache_data(ttl=900, show_spinner="Собираю материалы из источников…")
def load_publications(active: tuple, days: int):
    sources = [Source(name=n, url=u, kind=k) for n, u, k in active]
    pubs, status = fetch_all(sources, days)
    return [p.model_dump(mode="json") for p in pubs], status


# ───────────── боковая панель ─────────────
st.sidebar.markdown("### Персонализация")
role = st.sidebar.radio("Аудитория", list(AUDIENCE), format_func=AUDIENCE.get)
if S.get("last_role") != role:
    S["interests"] = list(DEFAULTS[role])
    S["period"] = ROLE_DEFAULT_PERIOD[role]
    S["last_role"] = role
period = st.sidebar.selectbox("Период", list(PERIODS), key="period",
                              help="Ежедневный дайджест для специалистов, ежемесячный — для руководства")
options = list(dict.fromkeys(PRESETS + S.custom_interests + S.get("interests", [])))
interests = st.sidebar.multiselect("Интересы", options, key="interests")
st.sidebar.text_input("➕ Свой интерес (Enter)", key="new_interest", on_change=add_interests,
                      placeholder="например: Exchange, утечка данных, 1С",
                      help="Любое слово или фраза, на русском или английском. Несколько — через запятую.")
excl_raw = st.sidebar.text_input("Исключить (через запятую)", value="smartphone, gaming")
limit = st.sidebar.slider("Размер дайджеста", 3, 20, 8)
org_boost = st.sidebar.checkbox("Приоритет РФ / энергетика / КИИ", value=False,
                                help="Сигналы из датасета организаторов. По умолчанию выключено — ассистент универсальный.")
demo = st.sidebar.checkbox("Демо-данные (без сети)", value=False)
if st.sidebar.button("🔄 Обновить источники", width="stretch"):
    load_publications.clear()

st.sidebar.divider()
st.sidebar.markdown("### Обратная связь")
st.sidebar.caption(f"👍 {len(S.liked)} · 👎 {len(S.disliked)} — подборка подстраивается под ваши оценки.")
profile_blob = json.dumps({"interests": interests, "custom_interests": S.custom_interests, "priorities": S.priorities,
                           "liked": S.liked, "disliked": S.disliked, "sources": S.sources}, ensure_ascii=False, indent=1)
st.sidebar.download_button("💾 Сохранить профиль и источники", profile_blob, "digest_profile.json", "application/json",
                           width="stretch", help="Хранилище приложения временное — сохраните профиль, чтобы вернуться к нему.")
up = st.sidebar.file_uploader("Загрузить профиль", type="json", label_visibility="collapsed")
if up is not None and S.get("loaded_profile") != up.file_id:
    try:
        d = json.loads(up.getvalue())
        S.custom_interests = d.get("custom_interests", []); S.priorities = d.get("priorities", {})
        S.liked = d.get("liked", {}); S.disliked = d.get("disliked", {}); S.sources = d.get("sources", S.sources)
        S["interests"] = d.get("interests", interests); S["loaded_profile"] = up.file_id
        st.rerun()
    except Exception as exc:
        st.sidebar.error(f"Не удалось прочитать профиль: {exc}")
if st.sidebar.button("Сбросить оценки", width="stretch"):
    S.liked, S.disliked, S.priorities = {}, {}, {}
    st.rerun()

# ───────────── данные ─────────────
sources = [Source(**s) for s in S.sources]
days = PERIODS[period]
if demo:
    pubs = [Publication(**x) for x in json.loads((ROOT / "data/samples/publications.json").read_text(encoding="utf-8"))]
    status: list[dict] = []
else:
    active = tuple((s.name, s.url, s.kind) for s in sources if s.enabled)
    raw, status = load_publications(active, days) if active else ([], [])
    pubs = [Publication(**x) for x in raw]
    trust = {s.name: s.trust for s in sources}
    for p in pubs:
        p.source_trust = trust.get(p.source, p.source_trust)
by_id = {p.id: p for p in pubs}

profile = UserProfile(role=role, interests=interests,
                      exclusions=[x.strip() for x in excl_raw.split(",") if x.strip()], priorities=S.priorities)
liked = [Publication(**x) for x in S.liked.values()]
disliked = [Publication(**x) for x in S.disliked.values()]
events = run_pipeline(pubs, profile, limit, organizer_boost=org_boost, liked=liked, disliked=disliked)
ok_n = sum(1 for s in status if s["ok"])
meta = {"period_label": period, "generated_at": datetime.now(), "publications_in": len(pubs),
        "sources_ok": ok_n, "sources_total": len(status)}


def rate(event, positive: bool) -> None:
    lead = by_id.get(event.publication_ids[0])
    if not lead:
        return
    (S.liked if positive else S.disliked)[lead.id] = lead.model_dump(mode="json")
    (S.disliked if positive else S.liked).pop(lead.id, None)
    terms = [r for r in event.reasons if r in interests]
    if terms:
        new = apply_feedback(UserProfile(interests=interests, priorities=S.priorities), terms, positive)
        S.priorities = new.priorities
    st.toast("Учту: больше такого" if positive else "Учту: меньше такого")


# ───────────── интерфейс ─────────────
st.title("◈ Intelligence Digest")
st.caption("Ассистент ИТ/ИБ-дайджестов: источники → отбор по вашим интересам → тематические разделы со ссылками")
tab_digest, tab_sources = st.tabs(["📰 Дайджест", "🔌 Источники"])

with tab_digest:
    if demo:
        st.info("Включены демо-данные (6 вымышленных публикаций). Снимите галочку в боковой панели, чтобы работать с реальными источниками.")
    elif status and ok_n == 0:
        st.error("Ни один источник не ответил (возможно, нет доступа к сети). Проверьте вкладку «Источники» или включите демо-данные.")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Источников доступно", f"{ok_n}/{len(status)}" if status else "демо")
    m2.metric("Публикаций за период", len(pubs))
    m3.metric("Событий в дайджесте", len(events))
    m4.metric("Сжатие потока", f"{1 - len(events) / max(len(pubs), 1):.0%}")

    if not events:
        st.warning("По выбранным интересам и периоду ничего не найдено. Добавьте интерес, увеличьте период или проверьте источники.")
    for topic, items in group_by_topic(events).items():
        st.markdown(f"### {topic}")
        for e in items:
            with st.container(border=True):
                left, right = st.columns([5, 1])
                left.subheader(e.title)
                right.metric("Релевантность", f"{e.score:.0%}")
                st.caption(" · ".join(x for x in [e.category, fmt_date(e.published_at), f"источников: {len(e.links)}"] if x))
                st.write(e.summary)
                st.markdown(f"**Почему важно:** {e.why_it_matters}")
                if e.evidence:
                    st.markdown(f"<div class='quote'>{e.evidence}</div>", unsafe_allow_html=True)
                if detail_line(e):
                    st.info(detail_line(e))
                if e.reasons:
                    st.caption("Сигналы отбора: " + " · ".join(e.reasons))
                with st.expander(f"Источники ({len(e.links)})"):
                    for l in e.links:
                        d = fmt_date(l.get("published_at"))
                        st.markdown(f"- [{l['source']}: {l['title']}]({l['url']})" + (f" — {d}" if d else ""))
                lead_id = e.publication_ids[0]
                b1, b2, b3 = st.columns([1, 1, 4])
                b1.button("👍 Релевантно", key=f"up_{e.id}", on_click=rate, args=(e, True), width="stretch")
                b2.button("👎 Не то", key=f"down_{e.id}", on_click=rate, args=(e, False), width="stretch")
                if lead_id in S.liked:
                    b3.caption("Вы отметили: релевантно")
                elif lead_id in S.disliked:
                    b3.caption("Вы отметили: не релевантно")

    st.divider()
    st.markdown("### Экспорт")
    md = render_markdown(events, profile, meta)
    c1, c2 = st.columns(2)
    c1.download_button("↓ Скачать Markdown", md, "digest.md", "text/markdown", width="stretch")
    with tempfile.TemporaryDirectory() as tmp:
        data = export_docx(events, profile, Path(tmp) / "digest.docx", meta).read_bytes()
    c2.download_button("↓ Скачать DOCX", data, "digest.docx",
                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document", width="stretch")
    with st.expander("Предпросмотр Markdown"):
        st.code(md, language="markdown")

with tab_sources:
    st.markdown("#### Добавить источник")
    st.caption("Вставьте ссылку на сайт, RSS/Atom-ленту, публичный Telegram-канал (t.me/канал или @канал) или отдельную статью. "
               "Тип определяется автоматически, RSS на сайте ищется сам.")
    a1, a2, a3 = st.columns([4, 2, 1])
    new_url = a1.text_input("Ссылка", key="src_url", label_visibility="collapsed", placeholder="https://… или @канал")
    new_name = a2.text_input("Название", key="src_name", label_visibility="collapsed", placeholder="Название (необязательно)")
    if a3.button("Проверить и добавить", width="stretch") and new_url.strip():
        try:
            with st.spinner("Проверяю источник…"):
                src, sample = detect_source(new_url, new_name.strip())
            if not sample:
                st.error("Источник открылся, но материалов в нём не нашлось.")
            elif any(s["url"] == src.url for s in S.sources):
                st.warning("Такой источник уже добавлен.")
            else:
                S.sources.append(src.model_dump()); load_publications.clear()
                kind = {"rss": "RSS-лента", "telegram": "Telegram-канал", "page": "отдельная страница"}[src.kind]
                st.success(f"Добавлено: {src.name} ({kind}), найдено материалов: {len(sample)}. Пример: «{sample[0].title[:90]}»")
        except Exception as exc:
            st.error(f"Не удалось подключить источник: {type(exc).__name__}: {str(exc)[:160]}")

    st.markdown("#### Подключённые источники")
    st_by_name = {s["name"]: s for s in status}
    df = pd.DataFrame([{
        "Вкл": s["enabled"], "Название": s["name"], "Тип": s["kind"], "Доверие": s["trust"],
        "Статус": ("✅" if st_by_name[s["name"]]["ok"] else "❌") if s["name"] in st_by_name else "—",
        "Материалов": st_by_name.get(s["name"], {}).get("count", 0),
        "Ошибка": st_by_name.get(s["name"], {}).get("error", ""), "URL": s["url"],
    } for s in S.sources])
    edited = st.data_editor(
        df, hide_index=True, width="stretch", key="src_editor",
        disabled=["Название", "Тип", "Статус", "Материалов", "Ошибка", "URL"],
        column_config={"Вкл": st.column_config.CheckboxColumn(width="small"),
                       "Доверие": st.column_config.NumberColumn(min_value=0.0, max_value=1.0, step=0.05, format="%.2f")})
    changed = False
    for i, row in edited.iterrows():
        if S.sources[i]["enabled"] != bool(row["Вкл"]) or abs(S.sources[i]["trust"] - float(row["Доверие"])) > 1e-9:
            S.sources[i]["enabled"] = bool(row["Вкл"]); S.sources[i]["trust"] = float(row["Доверие"]); changed = True
    if changed:
        st.rerun()
    to_del = st.multiselect("Удалить источники", [s["name"] for s in S.sources])
    if to_del and st.button("Удалить выбранные"):
        S.sources = [s for s in S.sources if s["name"] not in to_del]
        st.rerun()
    st.caption("Доверие влияет на оценку материалов. Список источников и профиль можно сохранить кнопкой в боковой панели.")
