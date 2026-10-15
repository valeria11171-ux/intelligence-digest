from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

class Publication(BaseModel):
    id: str
    title: str
    url: str
    source: str
    published_at: datetime | None = None
    text: str = ""
    language: str | None = None
    source_trust: float = 0.8

class Source(BaseModel):
    """Источник материалов. kind: rss | telegram | page."""
    name: str
    url: str
    kind: Literal["rss", "telegram", "page"] = "rss"
    trust: float = Field(default=0.8, ge=0, le=1)
    enabled: bool = True

class UserProfile(BaseModel):
    role: str = "security_engineer"
    interests: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    priorities: dict[str, float] = Field(default_factory=dict)

class Assessment(BaseModel):
    publication_id: str
    relevance: float = Field(ge=0, le=1)
    importance: float = Field(ge=0, le=1)
    novelty: float = Field(default=0.5, ge=0, le=1)
    source_trust: float = Field(default=0.7, ge=0, le=1)
    category: str
    reasons: list[str] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)
    entities: list[str] = Field(default_factory=list)
    final_score: float = Field(ge=0, le=1)

class DigestEvent(BaseModel):
    id: str
    title: str
    category: str
    summary: str
    why_it_matters: str
    score: float
    publication_ids: list[str]
    sources: list[str]
    reasons: list[str] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)
    topic: str = ""
    evidence: str = ""
    links: list[dict] = Field(default_factory=list)  # {title,url,source,published_at}
    published_at: datetime | None = None
