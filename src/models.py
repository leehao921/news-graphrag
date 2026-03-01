"""
news-graphrag / src/models.py
Pydantic v2 資料模型：Article、Keyword、Entity、SearchResult
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


# ─────────────────────── Enums ───────────────────────────────────────────────

class Language(str, Enum):
    ZH = "zh"
    EN = "en"
    JA = "ja"

class EntityType(str, Enum):
    COMPANY  = "COMPANY"
    PERSON   = "PERSON"
    LOCATION = "LOCATION"
    EVENT    = "EVENT"
    POLICY   = "POLICY"
    PRODUCT  = "PRODUCT"

class Domain(str, Enum):
    SEMICONDUCTOR = "semiconductor"
    MACRO         = "macro"
    GEOPOLITICAL  = "geopolitical"
    EARNINGS      = "earnings"
    ENERGY        = "energy"
    GENERAL       = "general"

class NewsSource(str, Enum):
    CNYES   = "cnyes"
    REUTERS = "reuters"
    USNEWS  = "usnews"
    YAHOO_FINANCE = "yahoo_finance"
    TECHCRUNCH    = "techcrunch"
    DIGITIMES     = "digitimes"


# ─────────────────────── 核心資料模型 ────────────────────────────────────────

class KeywordModel(BaseModel):
    """
    Qdrant keywords collection + Neo4j Keyword 節點
    向量轉移的基本單元：每個 keyword 有自己的 embedding
    """
    id: UUID = Field(default_factory=uuid4)
    text: str                                   # 原始文字（繁體）
    normalized: str                             # 正規化（小寫、簡轉繁）
    domain: Domain = Domain.GENERAL
    idf_score: float = Field(ge=0.0, le=1.0, default=0.5)
    vector_id: Optional[str] = None             # Qdrant point id（str UUID）
    neo4j_id: Optional[str] = None

    @field_validator("normalized", mode="before")
    @classmethod
    def normalize_text(cls, v: str) -> str:
        return v.strip().lower()


class EntityModel(BaseModel):
    """
    GLiNER2 抽取的命名實體
    Neo4j Entity 節點
    """
    id: UUID = Field(default_factory=uuid4)
    name: str
    entity_type: EntityType
    confidence: float = Field(ge=0.0, le=1.0)
    ticker: Optional[str] = None                # 股票代號（公司適用）
    aliases: list[str] = Field(default_factory=list)
    neo4j_id: Optional[str] = None

    model_config = {"use_enum_values": True}


class ArticleModel(BaseModel):
    """
    新聞文章：PostgreSQL 原文 + Qdrant 向量 + Neo4j 節點
    """
    id: UUID = Field(default_factory=uuid4)
    title: str
    content: str
    summary: Optional[str] = None
    url: str
    source: NewsSource
    language: Language = Language.ZH
    published_at: datetime
    crawled_at: datetime = Field(default_factory=datetime.utcnow)

    # NLP 抽取結果
    keywords: list[KeywordModel] = Field(default_factory=list)
    entities: list[EntityModel] = Field(default_factory=list)
    domains: list[Domain] = Field(default_factory=list)
    sentiment_score: float = Field(ge=-1.0, le=1.0, default=0.0)

    # 向量庫 / 圖資料庫外鍵
    vector_id: Optional[str] = None             # Qdrant point id
    neo4j_id: Optional[str] = None

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content cannot be empty")
        return v


# ─────────────────────── 查詢 / 回應模型 ─────────────────────────────────────

class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    top_k: int = Field(default=10, ge=1, le=50)
    alpha: float = Field(default=0.3, ge=0.0, le=1.0,
                         description="向量轉移強度：0=純向量, 1=純圖")
    filters: Optional[SearchFilters] = None
    use_graph_expansion: bool = True


class SearchFilters(BaseModel):
    sources: Optional[list[NewsSource]] = None
    domains: Optional[list[Domain]] = None
    language: Optional[Language] = None
    published_after: Optional[datetime] = None
    published_before: Optional[datetime] = None
    min_sentiment: Optional[float] = None      # -1.0 to +1.0


class SearchResultItem(BaseModel):
    article_id: str
    title: str
    summary: str
    url: str
    source: str
    published_at: datetime
    sentiment_score: float
    vector_score: float                         # Qdrant 相似度
    graph_proximity_score: float                # 圖距離分數
    final_score: float                          # 融合後得分
    matched_keywords: list[str] = Field(default_factory=list)
    matched_entities: list[str] = Field(default_factory=list)
    transfer_keywords: list[str] = Field(default_factory=list)  # 向量轉移貢獻的關鍵詞


class SearchResponse(BaseModel):
    query: str
    total_results: int
    results: list[SearchResultItem]
    alpha_used: float
    graph_expanded: bool
    transfer_keywords_used: list[str]          # 本次查詢用到的轉移關鍵詞
    latency_ms: float


# ─────────────────────── 圖操作模型 ──────────────────────────────────────────

class GraphNode(BaseModel):
    neo4j_id: str
    label: str                                  # Article / Keyword / Entity / Topic
    properties: dict


class GraphEdge(BaseModel):
    source_id: str
    target_id: str
    relationship: str                           # CONTAINS_KEYWORD / MENTIONS / ...
    properties: dict = Field(default_factory=dict)


class GraphExpansionResult(BaseModel):
    """圖遍歷返回的鄰居節點，用於向量轉移計算"""
    neighbor_neo4j_id: str
    neighbor_type: str                          # Keyword / Entity / Topic
    neighbor_text: str
    vector_id: Optional[str]
    edge_weight: float                          # TF-IDF × co-occurrence
    hop_distance: int                           # 1 or 2


# ─────────────────────── 入庫管線模型 ────────────────────────────────────────

class IngestRequest(BaseModel):
    url: str
    source: NewsSource
    force_reingest: bool = False


class IngestResult(BaseModel):
    article_id: str
    status: str                                 # "ingested" / "duplicate" / "failed"
    keywords_extracted: int
    entities_extracted: int
    embedding_dim: int
    neo4j_nodes_created: int
    neo4j_edges_created: int
    latency_ms: float


# ─────────────────────── 情感信號（TMF 整合）────────────────────────────────

class NewsSentimentSignal(BaseModel):
    """寫入 Redis Stream tmf:stream:news_sentiment 的結構"""
    signal_id: UUID = Field(default_factory=uuid4)
    computed_at: datetime = Field(default_factory=datetime.utcnow)
    window_hours: int = 2
    article_count: int
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    sentiment_label: str                        # "bullish" / "bearish" / "neutral"
    top_topics: list[str] = Field(max_length=5)
    dominant_entities: list[str] = Field(max_length=5)
    confidence: float = Field(ge=0.0, le=1.0)


# ─── forward ref fix ─────────────────────────────────────────────────────────
SearchRequest.model_rebuild()
