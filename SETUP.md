# Mac Mini M4 設置指南

> **前置條件**: Mac Mini M4 到貨後，按此順序執行

---

## 第一天：基礎設施（30 分鐘）

### 1. 安裝 Docker Desktop for Mac（Apple Silicon）
```bash
# 下載 Apple Silicon 版本：
# https://docs.docker.com/desktop/install/mac-install/
# 安裝後確認：
docker --version && docker compose version
```

### 2. Clone 專案
```bash
git clone <your-repo> ~/news-graphrag
cd ~/news-graphrag

# 設定環境變數
cp .env.example .env
# 編輯 .env，設定密碼
nano .env
```

### 3. 啟動所有服務（僅核心，不含應用）
```bash
docker compose up -d qdrant neo4j postgres redis
docker compose ps   # 確認全部 healthy
```

### 4. 安裝 Ollama + 拉取模型（15-20 分鐘）
```bash
docker compose up -d ollama
sleep 15  # 等 Ollama 啟動

# 拉取模型（M4 本地跑，Metal 加速）
docker exec graphrag_ollama ollama pull bge-m3        # ~670MB
docker exec graphrag_ollama ollama pull qwen2.5:7b    # ~4.7GB

# 測試 embedding
curl http://localhost:11434/api/embeddings \
  -d '{"model":"bge-m3","prompt":"台積電 CoWoS 封裝"}' | jq .embedding | head -c 100
```

### 5. 初始化資料庫 Schema
```bash
# PostgreSQL（自動在 docker-compose 啟動時執行）
docker exec graphrag_postgres psql -U newsuser -d newsdb \
  -c "SELECT COUNT(*) FROM articles;"  # 應返回 0

# Neo4j Schema
docker exec -i graphrag_neo4j cypher-shell \
  -u neo4j -p changeme \
  < scripts/init_neo4j_schema.cypher

# 驗證 Neo4j
docker exec graphrag_neo4j cypher-shell \
  -u neo4j -p changeme \
  "MATCH (e:Entity) RETURN e.name, e.ticker LIMIT 5;"
```

### 6. 連線測試
```bash
cd ~/news-graphrag
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python3 scripts/connection_test.py
# Expected output:
# ✓ Qdrant: connected (version: 1.9.0)
# ✓ Neo4j: connected (7 entities pre-loaded)
# ✓ PostgreSQL: connected (0 articles)
# ✓ Redis: PONG
# ✓ Ollama bge-m3: embedding dim=1024
# ✓ Ollama qwen2.5:7b: model loaded
```

---

## 第二天：入庫管線（4 小時）

```bash
# 測試 NLP 管線
python3 scripts/test_nlp_pipeline.py \
  --text "台積電宣布2026年CoWoS封裝產能將增加50%，供應Nvidia AI晶片需求"
# Expected: keywords=[CoWoS, 封裝, 台積電], entities=[台積電/COMPANY, Nvidia/COMPANY]

# 塞入 100 篇樣本新聞（測試用）
python3 scripts/ingest_sample.py --count 100

# 驗證入庫結果
python3 scripts/verify_ingestion.py
# Expected:
# Articles in PostgreSQL: 100
# Vectors in Qdrant: 100 (news_articles) + ~850 (keywords)
# Nodes in Neo4j: ~100 Article + ~850 Keyword + ~200 Entity
# Edges in Neo4j: ~2000
```

---

## 第三天：查詢引擎

```bash
# 啟動 API
docker compose up -d api

# 測試查詢
curl -s -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "台積電 CoWoS 供應 Nvidia",
    "top_k": 5,
    "alpha": 0.3,
    "use_graph_expansion": true
  }' | jq .

# 對照測試（關閉向量轉移）
curl -s -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "台積電 CoWoS 供應 Nvidia",
    "top_k": 5,
    "alpha": 0.0,
    "use_graph_expansion": false
  }' | jq .

# 評估向量轉移效果
python3 scripts/benchmark_retriever.py
# 預期：alpha=0.3 比 alpha=0.0 的 Recall@10 高 15-25%
```

---

## 服務端口速查

| 服務 | URL | 說明 |
|------|-----|------|
| Qdrant Dashboard | http://localhost:6333/dashboard | 向量搜尋 UI |
| Neo4j Browser | http://localhost:7474 | 圖資料庫 UI |
| API Docs | http://localhost:8000/docs | FastAPI Swagger |
| API ReDoc | http://localhost:8000/redoc | 可讀文檔 |
| Ollama | http://localhost:11434 | LLM API |

---

## 常用維護命令

```bash
# 查看資料量
docker exec graphrag_qdrant curl -s http://localhost:6333/collections | jq '.result.collections[].points_count'
docker exec graphrag_neo4j cypher-shell -u neo4j -p changeme "MATCH (n) RETURN labels(n)[0] as label, count(*) as cnt ORDER BY cnt DESC;"
docker exec graphrag_postgres psql -U newsuser -d newsdb -c "SELECT COUNT(*) FROM articles WHERE is_processed;"

# 清除所有資料（重設）
docker compose down -v  # ⚠️ 危險！

# 備份 Neo4j
docker exec graphrag_neo4j neo4j-admin database dump neo4j > backup_neo4j_$(date +%Y%m%d).dump

# 備份 Qdrant
docker exec graphrag_qdrant curl -X POST http://localhost:6333/snapshots
```
