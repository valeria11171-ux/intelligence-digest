"""Мелкие текстовые утилиты: очистка HTML, язык, цитата-доказательство."""
from __future__ import annotations
import html
import re

_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)
_WS = re.compile(r"\s+")
_CYR = re.compile(r"[а-яё]", re.I)
_SENT = re.compile(r"(?<=[.!?…])\s+")


def clean_html(raw: str) -> str:
    if not raw:
        return ""
    raw = _SCRIPT.sub(" ", raw)
    raw = re.sub(r"<br\s*/?>|</p>|</div>|</li>", ". ", raw, flags=re.I)
    text = _WS.sub(" ", html.unescape(_TAG.sub(" ", raw))).strip().replace(" .", ".")
    return re.sub(r"\.(\s*\.)+", ".", text)


def detect_lang(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "en"
    return "ru" if len(_CYR.findall(text)) / len(letters) > 0.3 else "en"


def _word_pattern(w: str) -> str:
    if _CYR.search(w) and len(w) >= 5:          # русское слово -> по основе
        cut = 3 if len(w) >= 7 else 2
        return re.escape(w[:-cut]) + r"\w*"
    return re.escape(w) + (r"\w*" if _CYR.search(w) else r"(?!\w)")


def term_regex(term: str) -> re.Pattern:
    """Регэксп интереса: русские слова ищутся по основе (уязвимость ~ уязвимости), латиница — по границам слов."""
    words = term.strip().lower().split()
    return re.compile(r"(?<!\w)" + r"[\s\-]+".join(_word_pattern(w) for w in words), re.I)


def evidence_snippet(text: str, terms: list[str], max_len: int = 260) -> str:
    """Предложение из первоисточника, подтверждающее релевантность (доказуемость)."""
    text = (text or "").strip()
    if not text:
        return ""
    sentences = [s.strip() for s in _SENT.split(text) if len(s.strip()) > 25]
    for term in terms:
        rx = term_regex(term)
        for s in sentences:
            if rx.search(s):
                return s[:max_len].rstrip() + ("…" if len(s) > max_len else "")
    first = sentences[0] if sentences else text
    return first[:max_len].rstrip() + ("…" if len(first) > max_len else "")
