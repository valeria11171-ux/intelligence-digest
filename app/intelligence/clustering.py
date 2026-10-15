from __future__ import annotations
from collections import defaultdict
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from app.models import Publication

def cluster_by_topic(publications: list[Publication], threshold: float=.88) -> dict[str,list[Publication]]:
    if not publications:return {}
    docs=[f'{p.title} {p.text[:1200]}' for p in publications]
    X=TfidfVectorizer(ngram_range=(1,2),analyzer='word',min_df=1,max_features=10000).fit_transform(docs)
    sim=cosine_similarity(X); seen=set(); clusters=[]
    for i,p in enumerate(publications):
        if i in seen:continue
        group=[i]; seen.add(i)
        for j in range(i+1,len(publications)):
            if j not in seen and sim[i,j]>=threshold: group.append(j);seen.add(j)
        clusters.append([publications[k] for k in group])
    def label(items):
        text=' '.join(p.title.lower() for p in items)
        rules=[('vulnerabilities',r'cve|уязвим|vulnerab'),('ransomware',r'ransomware|шифроваль'),('attacks',r'атак|campaign|malware|phishing'),('ai',r'\bai\b|llm|нейросет'),('cloud',r'cloud|kubernetes|облач')]
        return next((n for n,pat in rules if re.search(pat,text)), 'other')
    out={}
    for n,items in enumerate(clusters,1):
        base=label(items); key=base if base not in out else f'{base}-{n}'; out[key]=items
    return out


_CVE_RE = re.compile(r"CVE-\d{4}-\d{4,7}", re.I)


def cluster_events(publications: list[Publication], threshold: float = .5) -> list[list[Publication]]:
    """Объединяет публикации об одном событии: общий CVE ИЛИ высокая тематическая близость
    (union-find, поэтому транзитивно). Работает для RU и EN."""
    n = len(publications)
    if n <= 1:
        return [list(publications)] if n else []
    docs = [f"{p.title} {p.title} {p.text[:800]}" for p in publications]
    X = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1, max_features=20000).fit_transform(docs)
    sim = cosine_similarity(X)
    cves = [set(c.upper() for c in _CVE_RE.findall(f"{p.title} {p.text}")) for p in publications]
    parent = list(range(n))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for i in range(n):
        for j in range(i + 1, n):
            if sim[i, j] >= threshold or (cves[i] & cves[j]):
                parent[find(j)] = find(i)
    groups: dict[int, list[Publication]] = defaultdict(list)
    for i, p in enumerate(publications):
        groups[find(i)].append(p)
    return list(groups.values())
