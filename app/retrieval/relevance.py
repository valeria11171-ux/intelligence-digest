from app.models import Publication, UserProfile
from app.textutils import term_regex


def lexical_relevance(pub: Publication, profile: UserProfile) -> tuple[float, list[str]]:
    """Совпадения интересов пользователя (любых, в т.ч. добавленных вручную) с материалом.
    Русские слова ищутся по основе, поэтому «уязвимость» находит «уязвимости/уязвимостей»."""
    hay = f"{pub.title} {pub.text}"
    excluded = [x for x in profile.exclusions if term_regex(x).search(hay)]
    if excluded:
        return 0.0, [f"excluded:{x}" for x in excluded]
    if not profile.interests:
        return 0.5, []
    hits = [x for x in profile.interests if term_regex(x).search(hay)]
    # совпадение в заголовке весит больше, чем в тексте
    in_title = {x for x in hits if term_regex(x).search(pub.title)}
    weighted = sum(profile.priorities.get(x, 1.0) * (1.5 if x in in_title else 1.0) for x in hits)
    denom = sum(profile.priorities.get(x, 1.0) for x in profile.interests) or 1
    return min(1.0, weighted / denom * 2.5), hits
