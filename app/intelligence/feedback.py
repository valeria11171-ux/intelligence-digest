from __future__ import annotations
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from app.models import Publication, UserProfile


def apply_feedback(profile: UserProfile, terms: list[str], positive: bool = True) -> UserProfile:
    """Меняет веса интересов профиля: 👍 усиливает, 👎 ослабляет."""
    data = profile.model_dump()
    interests = list(data["interests"]); priorities = dict(data["priorities"])
    for term in terms:
        if positive and term not in interests:
            interests.append(term)
        priorities[term] = max(0.1, min(2.0, priorities.get(term, 1.0) + (0.15 if positive else -0.25)))
    data["interests"] = interests; data["priorities"] = priorities
    return UserProfile(**data)


def feedback_adjustments(pubs: list[Publication], liked: list[Publication], disliked: list[Publication]) -> dict[str, float]:
    """Обучение на оценках: материалы, похожие на отмеченные 👍, поднимаются,
    похожие на отмеченные 👎 — опускаются (Rocchio-подобная коррекция по TF-IDF)."""
    if not pubs or not (liked or disliked):
        return {}
    docs = lambda xs: [f"{p.title}. {p.text[:1500]}" for p in xs]
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, max_features=60000)
    X = vec.fit_transform(docs(pubs) + docs(liked) + docs(disliked))
    n, nl = len(pubs), len(liked)
    P, L, D = X[:n], X[n:n + nl], X[n + nl:]
    like = cosine_similarity(P, L).max(axis=1) if nl else [0.0] * n
    dis = cosine_similarity(P, D).max(axis=1) if len(disliked) else [0.0] * n
    return {p.id: round(float(0.25 * like[i] - 0.35 * dis[i]), 4) for i, p in enumerate(pubs)}
