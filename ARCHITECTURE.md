# 新聞 GraphRAG 架構設計文件
**目標平台**: Mac Mini M4 (本機單機部署)  
**設計哲學**: 向量空間 × 圖結構 = 語意感知查詢  
**版本**: MVP v1.0 | 2026-03-02

---

## 一、核心概念：向量轉移（Vector Transfer）

```
傳統 RAG 流程:
  Query → [Embedding] → qdrant(top-k) → LLM → Answer
  問題：只找「向量相似」的文件，錯過「概念相鄰」的關係

GraphRAG 向量轉移流程:
  Query → [Embedding] → qdrant(top-k)
                              ↓
              Neo4j 圖遍歷：Article → Keywords → Entity
                              ↓
          擴充查詢向量 q' = q + α·Σ(鄰居節點向量)
                              ↓
              qdrant 二次查詢（使用轉移後的 q'）
                              ↓
                        Re-rank → LLM → Answer

效果：
  「台積電」查詢 → 圖遍歷 → 找到「CoWoS封裝」「3奈米」「黃仁勳」
  → 這些 keyword 節點的向量「拉動」原查詢向量
  → 結果包含間接相關但語意重要的新聞
```

### 向量轉移數學模型

```
q_expanded = normalize(q + α · Σ_{k ∈ N(q,G)} v_k · w(q,k))

where:
  q        = 原始查詢 embedding (1536-dim)
  N(q,G)   = 圖中與 top-k 結果相鄰的 keyword/entity 節點集合
  v_k      = keyword 節點的 embedding 向量
  w(q,k)   = 邊權重 (tf-idf × co-occurrence × temporal_decay)
  α        = 轉移強度超參數 (建議 0.2-0.4)
```

---

## 二、系統架構全景

```
┌─────────────────────────────────────────────────────────────┐
│                     MAC MINI M4 (本機)                       │
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │   新聞來源   │    │  Embedding  │    │   查詢介面   │     │
│  │             │    │   Engine    │    │             │     │
│  │ RSS/API爬蟲 │    │  BGE-M3     │    │  FastAPI    │     │
│  │ Playwright  │    │  (Ollama)   │    │  + Web UI   │     │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘     │
│         │                  │                  │            │
│         ▼                  ▼                  ▼            │
│  ┌─────────────────────────────────────────────────┐       │
│  │              處理管線 (Python)                   │       │
│  │  jieba → GLiNER2 → 關係抽取 → 圖建構             │       │
│  └──────┬──────────────────────────────────────────┘       │
│         │                                                  │
│    ┌────┴─────────────────────┐                           │
│    ▼                         ▼                            │
│  ┌───────────┐        ┌─────────────┐                     │
│  │  Qdrant   │◄──────►│   Neo4j     │                     │
│  │ (向量庫)  │  橋接  │  (圖資料庫) │                     │
│  │ Port 6333 │        │  Port 7474  │                     │
│  └───────────┘        └─────────────┘                     │
│         ▲                    ▲                            │
│         └──────────┬─────────┘                           │
│                    ▼                                      │
│          ┌─────────────────┐                             │
│          │   PostgreSQL    │  (新聞原文 + 元數據)         │
│          │   Port 5432     │                             │
│          └─────────────────┘                             │
│                                                          │
│          ┌─────────────────┐                             │
│          │     Redis       │  (快取 + 查詢去重)           │
│          │   Port 6379     │                             │
│          └─────────────────┘                             │
└─────────────────────────────────────────────────────────┘
```

---

## 三、圖資料庫 Schema（Neo4j）

### 節點類型

```cypher
// 文章節點
(:Article {
  id: "uuid",
  title: "string",
  source: "reuters|cnyes|...",
  published_at: datetime,
  vector_id: "qdrant-point-id",    // 橋接到 Qdrant
  language: "zh|en",
  sentiment: float,                // -1 to +1
  relevance_score: float
})

// 關鍵詞節點（向量轉移的核心）
(:Keyword {
  text: "台積電",
  normalized: "tsmc",
  vector_id: "qdrant-point-id",    // keyword 本身也有 embedding！
  idf_score: float,
  domain: "semiconductor|macro|geo..."
})

// 實體節點（NER 抽取）
(:Entity {
  name: "台積電",
  type: "COMPANY|PERSON|LOCATION|EVENT|POLICY",
  ticker: "2330",                  // 股票代號（如適用）
  aliases: ["TSMC", "台積"]
})

// 主題節點（LLM 自動分群）
(:Topic {
  id: "topic_001",
  label: "AI晶片供應鏈",
  keywords: ["HBM", "CoWoS", "Nvidia"],
  vector_id: "qdrant-point-id"
})

// 事件節點（跨文章實體）
(:Event {
  name: "美伊戰爭開始",
  date: date,
  type: "GEOPOLITICAL|EARNINGS|POLICY|MARKET",
  impact_sectors: ["energy", "semiconductor"]
})
```

### 邊關係（轉移路徑）

```cypher
// Article → Keyword（TF-IDF 加權）
(:Article)-[:CONTAINS_KEYWORD {tfidf: 0.87, count: 3}]→(:Keyword)

// Article → Entity（NER 信心度）
(:Article)-[:MENTIONS {confidence: 0.95, count: 2}]→(:Entity)

// Article → Topic（LLM 分群）
(:Article)-[:BELONGS_TO {score: 0.78}]→(:Topic)

// Article → Event（事件觸發）
(:Article)-[:REPORTS_ON {is_primary: true}]→(:Event)

// Keyword → Entity（詞-實體對齊）
(:Keyword)-[:REFERS_TO {weight: 0.9}]→(:Entity)

// Entity → Entity（共現關係）
(:Entity)-[:CO_OCCURS_WITH {
  frequency: 42,
  articles_count: 15,
  last_seen: datetime
}]→(:Entity)

// 時間鏈（同實體的文章序列）
(:Article)-[:PRECEDES {days_gap: 3}]→(:Article)
```

### 關鍵查詢模式

```cypher
// 向量轉移用：給定 Article ID，找2跳內的所有 Keyword/Entity
MATCH (a:Article {id: $article_id})-[:CONTAINS_KEYWORD|MENTIONS*1..2]-(neighbor)
RETURN neighbor.vector_id, neighbor.text, 
       avg(r.tfidf) as avg_weight
ORDER BY avg_weight DESC LIMIT 20

// 事件影響鏈：美伊戰爭 → 相關公司
MATCH (e:Event {name: "美伊戰爭開始"})<-[:REPORTS_ON]-(a:Article)
      -[:MENTIONS]->(ent:Entity)
RETURN ent.name, ent.ticker, count(a) as mention_count
ORDER BY mention_count DESC
```

---

## 四、Qdrant Collection Schema

```python
# Collection 1: news_articles（新聞全文 embedding）
{
  "collection_name": "news_articles",
  "vectors": {
    "dense": {"size": 1024, "distance": "Cosine"},    # BGE-M3 輸出
    "sparse": {"modifier": "idf"}                      # BM25 稀疏向量
  },
  "payload_schema": {
    "article_id": "keyword",
    "neo4j_id": "keyword",
    "source": "keyword",
    "published_at": "datetime",
    "language": "keyword",
    "domain": "keyword[]"           # ["semiconductor", "macro"]
  }
}

# Collection 2: keywords（關鍵詞 embedding，向量轉移的鄰居向量庫）
{
  "collection_name": "keywords",
  "vectors": {
    "dense": {"size": 1024, "distance": "Cosine"}
  },
  "payload_schema": {
    "text": "text",
    "normalized": "keyword",
    "domain": "keyword",
    "neo4j_id": "keyword"
  }
}

# Collection 3: topics（主題 embedding）
{
  "collection_name": "topics",
  "vectors": {"dense": {"size": 1024, "distance": "Cosine"}},
  "payload_schema": {
    "label": "text",
    "keywords": "keyword[]"
  }
}
```

---

## 五、查詢引擎：Hybrid GraphRAG Retriever

```python
# src/retriever/graph_vector_retriever.py

class GraphVectorRetriever:
    """
    核心查詢邏輯：向量搜尋 + 圖遍歷 + 向量轉移
    """
    
    def __init__(self, qdrant: QdrantClient, neo4j: Neo4jDriver, 
                 embedder: BGE_M3, alpha: float = 0.3):
        self.qdrant = qdrant
        self.neo4j = neo4j
        self.embedder = embedder
        self.alpha = alpha  # 向量轉移強度
    
    def retrieve(self, query: str, top_k: int = 10) -> list[SearchResult]:
        
        # Step 1: 查詢向量化
        q_vec = self.embedder.encode(query)  # shape: (1024,)
        
        # Step 2: Qdrant 初次搜尋（dense + sparse hybrid）
        initial_hits = self.qdrant.query_points(
            collection_name="news_articles",
            prefetch=[
                Prefetch(query=q_vec, using="dense", limit=20),
                Prefetch(query=sparse_encode(query), using="sparse", limit=20),
            ],
            query=FusionQuery(fusion=Fusion.RRF),  # Reciprocal Rank Fusion
            limit=top_k * 2
        )
        
        # Step 3: Neo4j 圖遍歷 — 找鄰居 keyword/entity 向量
        article_neo4j_ids = [h.payload["neo4j_id"] for h in initial_hits]
        neighbor_vector_ids = self._graph_expand(article_neo4j_ids)
        
        # Step 4: 載入鄰居向量（從 keywords collection）
        neighbor_vecs = self.qdrant.retrieve(
            collection_name="keywords",
            ids=neighbor_vector_ids,
            with_vectors=True
        )
        
        # Step 5: 向量轉移（核心算法）
        # q' = normalize(q + α × Σ(鄰居向量 × 邊權重))
        transfer_vec = self._compute_transfer(q_vec, neighbor_vecs)
        
        # Step 6: 用轉移後向量再次搜尋
        final_hits = self.qdrant.query_points(
            collection_name="news_articles",
            query=transfer_vec,
            using="dense",
            limit=top_k
        )
        
        # Step 7: 圖感知重排序
        return self._graph_rerank(final_hits, article_neo4j_ids)
    
    def _graph_expand(self, neo4j_ids: list[str]) -> list[str]:
        """2跳圖遍歷，返回鄰居節點的 qdrant vector_id"""
        with self.neo4j.session() as session:
            result = session.run("""
                UNWIND $ids AS article_id
                MATCH (a:Article {neo4j_id: article_id})
                      -[:CONTAINS_KEYWORD|MENTIONS]->(neighbor)
                WHERE neighbor.vector_id IS NOT NULL
                RETURN neighbor.vector_id AS vid, 
                       avg(r.tfidf) AS weight
                ORDER BY weight DESC LIMIT 30
            """, ids=neo4j_ids)
            return [row["vid"] for row in result]
    
    def _compute_transfer(self, q_vec, neighbor_vecs) -> np.ndarray:
        """向量轉移計算"""
        if not neighbor_vecs:
            return q_vec
        neighbor_matrix = np.vstack([v.vector for v in neighbor_vecs])
        transfer = neighbor_matrix.mean(axis=0)
        q_prime = q_vec + self.alpha * transfer
        return q_prime / np.linalg.norm(q_prime)  # normalize
    
    def _graph_rerank(self, hits, original_neo4j_ids) -> list[SearchResult]:
        """
        Re-rank：優先顯示與原始結果圖距離近的文章
        score_final = 0.7 * vector_score + 0.3 * graph_proximity_score
        """
        # ... PageRank-like graph proximity scoring
        pass
```

---

## 六、開源工具清單（MVP 選型）

| 層級 | 工具 | 版本 | 用途 | 理由 |
|------|------|------|------|------|
| **Embedding** | BGE-M3 | via Ollama | 中英文向量化 | 100語言支援、1024-dim、本機跑 |
| **向量庫** | Qdrant | 1.9+ | Dense+Sparse 混合搜尋 | 官方支援 RRF Fusion、Neo4j橋接 |
| **圖資料庫** | Neo4j Community | 5.x | 知識圖譜 + 圖遍歷 | 官方 QdrantNeo4jRetriever |
| **NER** | GLiNER2 | 0.2.x | 零樣本實體抽取 | 不需訓練、支援自訂類型 |
| **中文NLP** | jieba | 0.42 | 分詞 + 關鍵詞抽取 | 台灣語料相容性好 |
| **元數據庫** | PostgreSQL | 16 | 原文儲存 + 元數據 | 穩定、全文搜尋支援 |
| **快取** | Redis | 7 | 查詢去重 + 熱點快取 | 防止重複爬取 |
| **RAG框架** | LlamaIndex | 0.11+ | 編排 Retriever + LLM | 支援自訂 Retriever |
| **LLM** | Ollama(qwen2.5) | 7B | 本機問答生成 | M4 跑 7B 綽綽有餘 |
| **API** | FastAPI | 0.110+ | REST 查詢介面 | 異步、自動文檔 |
| **爬蟲** | Playwright | 1.44+ | 動態頁面新聞爬取 | JS渲染支援 |
| **排程** | APScheduler | 3.10+ | 定時爬取 + 更新圖 | 輕量、無需Celery |
| **監控** | Grafana + Prometheus | - | 系統監控 | 可選，MVP後加 |

---

## 七、Docker Compose 部署方案

```yaml
# docker-compose.yml
version: '3.9'

services:
  qdrant:
    image: qdrant/qdrant:v1.9.0
    ports: ["6333:6333", "6334:6334"]
    volumes:
      - qdrant_data:/qdrant/storage
    environment:
      QDRANT__SERVICE__GRPC_PORT: 6334
    restart: unless-stopped

  neo4j:
    image: neo4j:5.18-community
    ports: ["7474:7474", "7687:7687"]
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    environment:
      NEO4J_AUTH: neo4j/changeme
      NEO4J_PLUGINS: '["apoc", "graph-data-science"]'
      NEO4J_dbms_memory_heap_max__size: 2G
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    ports: ["5432:5432"]
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: newsdb
      POSTGRES_USER: newsuser
      POSTGRES_PASSWORD: changeme
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    restart: unless-stopped

  ollama:
    image: ollama/ollama:latest
    ports: ["11434:11434"]
    volumes:
      - ollama_models:/root/.ollama
    # Mac Mini M4: 使用 --gpus all 不適用
    # Apple Silicon 透過 Metal 自動加速
    restart: unless-stopped

volumes:
  qdrant_data:
  neo4j_data:
  neo4j_logs:
  postgres_data:
  redis_data:
  ollama_models:
```

---

## 八、資料流程：新聞入庫管線

```
新聞原文
  │
  ▼
[1] 爬蟲 (Playwright / feedparser)
    └── 去重: Redis SETNX(url_hash, 1, TTL=7d)
  │
  ▼
[2] 清洗 + 語言偵測
    └── langdetect → zh/en 分流
  │
  ▼
[3] 中文分詞 (jieba)
    └── 繁體轉換 (opencc)
    └── 停用詞過濾
  │
  ▼
[4] NER 抽取 (GLiNER2)
    └── 自訂標籤: ["公司", "人物", "地點", "政策", "事件", "產品"]
    └── 可信度閾值: > 0.7
  │
  ▼
[5] 關鍵詞抽取
    └── jieba TF-IDF top-20
    └── 去除 NER 已有的實體
  │
  ▼
[6] Embedding (BGE-M3 via Ollama API)
    └── 文章全文 embedding → Qdrant news_articles
    └── 每個 keyword embedding → Qdrant keywords
    └── 批次處理: 32 texts/batch
  │
  ▼
[7] 圖建構 (Neo4j)
    └── MERGE Article 節點
    └── MERGE Keyword 節點 (with vector_id)
    └── MERGE Entity 節點
    └── CREATE 邊關係 (with weights)
  │
  ▼
[8] 元數據入庫 (PostgreSQL)
    └── 原文 + 標題 + 摘要 + 來源 + 時間戳
```

---

## 九、目錄結構

```
news-graphrag/
├── docker-compose.yml
├── .env.example
├── pyproject.toml
│
├── src/
│   ├── ingestion/
│   │   ├── crawlers/           # RSS + Playwright 爬蟲
│   │   │   ├── rss_crawler.py
│   │   │   ├── cnyes_crawler.py
│   │   │   └── reuters_crawler.py
│   │   ├── dedup.py            # Redis 去重
│   │   └── pipeline.py         # 入庫主流程
│   │
│   ├── nlp/
│   │   ├── segmentor.py        # jieba + opencc
│   │   ├── ner.py              # GLiNER2 封裝
│   │   ├── keyword_extractor.py
│   │   └── sentiment.py        # 情感分析
│   │
│   ├── embeddings/
│   │   ├── bge_m3.py           # BGE-M3 via Ollama
│   │   └── sparse_encoder.py   # BM25 稀疏向量
│   │
│   ├── graph/
│   │   ├── schema.py           # Neo4j 節點/邊定義
│   │   ├── builder.py          # 圖建構邏輯
│   │   └── queries.py          # Cypher 查詢庫
│   │
│   ├── vector_store/
│   │   ├── qdrant_client.py    # Qdrant 操作封裝
│   │   └── collections.py      # Collection 定義
│   │
│   ├── retriever/
│   │   ├── graph_vector_retriever.py  # 核心！向量轉移
│   │   ├── reranker.py                # 重排序
│   │   └── query_expander.py          # 圖感知查詢擴充
│   │
│   ├── api/
│   │   ├── main.py             # FastAPI 入口
│   │   ├── routes/
│   │   │   ├── search.py       # /search endpoint
│   │   │   ├── ingest.py       # /ingest endpoint
│   │   │   └── graph.py        # /graph 視覺化 endpoint
│   │   └── models.py           # Pydantic 請求/回應模型
│   │
│   └── scheduler/
│       ├── jobs.py             # APScheduler 任務定義
│       └── main.py             # 排程器入口
│
├── tests/
│   ├── unit/
│   └── integration/
│
└── scripts/
    ├── init_db.py              # 初始化所有資料庫
    ├── ingest_sample.py        # 測試用：塞入樣本新聞
    └── benchmark_retriever.py  # 評估向量轉移效果
```

---

## 十、向量轉移效果評估方法

```python
# scripts/benchmark_retriever.py

# 測試集：20條有已知正確答案的問題
test_cases = [
    {
        "query": "台積電 CoWoS 封裝產能",
        "expected_keywords": ["先進封裝", "HBM", "Nvidia", "AI晶片"],
        "expected_articles": [...]
    },
    ...
]

# 評估指標
metrics = {
    "MRR@10": ...,          # Mean Reciprocal Rank
    "NDCG@10": ...,         # Normalized Discounted Cumulative Gain
    "Recall@10": ...,        # 召回率
    "transfer_gain": ...,    # 向量轉移前後 Recall 提升 %
}

# 對照組
baseline = VectorOnlyRetriever()     # 純 Qdrant 搜尋
ours = GraphVectorRetriever(alpha=0.3)

compare(baseline, ours, test_cases)
```

---

## 十一、MVP 開發順序（下週移機前可先做）

### 階段 0（本週，本機 WSL）：設計 + 規格
- [x] 架構文件（本文件）
- [ ] Pydantic 資料模型（Article, Keyword, Entity, SearchResult）
- [ ] Cypher schema 腳本
- [ ] Docker Compose 草稿
- [ ] 測試資料集（50篇手工標注新聞）

### 階段 1（Mac Mini 到後，第1天）：基礎設施
- [ ] `docker compose up` 啟動所有服務
- [ ] `scripts/init_db.py` 初始化 schema
- [ ] Ollama pull bge-m3 + qwen2.5:7b
- [ ] 連線測試（Python ping Qdrant/Neo4j/PG）

### 階段 2（第2-3天）：入庫管線
- [ ] RSS 爬蟲（財訊/Reuters/Bloomberg）
- [ ] jieba + GLiNER2 NLP 管線
- [ ] BGE-M3 embedding + Qdrant 入庫
- [ ] Neo4j 圖建構
- [ ] 塞入 1000 篇樣本新聞

### 階段 3（第4-5天）：查詢引擎
- [ ] GraphVectorRetriever 實作
- [ ] 向量轉移算法
- [ ] FastAPI `/search` endpoint
- [ ] 效果評估（對照 baseline）

### 階段 4（第2週）：問答介面
- [ ] LlamaIndex + Ollama qwen2.5 整合
- [ ] Web UI（Streamlit 或 Gradio）
- [ ] 排程爬蟲上線
- [ ] TMF 交易信號整合（新聞情感 → 市場情緒指標）

---

## 十二、與 TMF 交易系統整合

```python
# 新聞情感 → 交易信號
class NewsSignalSubsystem:
    """
    讀取 GraphRAG 問答結果，生成情感信號寫入 TMF 系統
    """
    
    def on_timer(self, interval: str) -> None:
        if interval != "news_signal_update":
            return
        
        # 查詢最近 2 小時重要新聞
        results = self.retriever.retrieve(
            query="台灣股市 半導體 重大事件",
            filters={"published_after": now() - timedelta(hours=2)}
        )
        
        # 情感聚合
        sentiment_score = aggregate_sentiment(results)  # -1 to +1
        
        # 寫入 Redis Stream (TMF 可讀取)
        redis.xadd("tmf:stream:news_sentiment", {
            "score": sentiment_score,
            "top_topics": json.dumps([r.topic for r in results[:3]]),
            "updated_at": now().isoformat()
        })
```

---

*架構設計：v1.0 | 待 Mac Mini M4 到貨後移機部署*
*下一步：建立 Pydantic 資料模型 + Docker Compose 草稿*
