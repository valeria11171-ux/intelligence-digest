from __future__ import annotations
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from app.models import Publication, UserProfile


def semantic_scores(publications: list[Publication], profile: UserProfile) -> dict[str, float]:
    """Лёгкая «семантика» без загрузки моделей: символьные n-граммы TF-IDF
    (устойчивы к русской морфологии и опечаткам). Подходит для любых новых интересов."""
    if not publications:
        return {}
    query = " ".join(profile.interests) or profile.role
    docs = [f"{p.title}. {p.text[:2000]}" for p in publications]
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, max_features=60000)
    X = vec.fit_transform([query] + docs)
    scores = cosine_similarity(X[0:1], X[1:]).ravel()
    return {p.id: float(s) for p, s in zip(publications, scores)}
