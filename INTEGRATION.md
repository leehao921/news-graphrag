# 自動化整合架構
**n8n + DolphinScheduler + FastAPI + MinIO**

---

## 一、整體數據流

```
                         ┌─────────────────────────────────────────┐
                         │         n8n 工作流引擎 (:5678)           │
                         │                                         │
  ┌──────────────┐       │  Workflow 01: RSS 入庫（每15分鐘）       │
  │  新聞來源     │──────►│  Workflow 02: 每日報告（07:30）          │
  │  42個來源    │       │  Workflow 03: 財報警報（事件觸發）        │
  └──────────────┘       └──────────────────┬──────────────────────┘
                                            │ HTTP POST
                                            ▼
                         ┌─────────────────────────────────────────┐
                         │    FastAPI 後端 (:8000)                  │
                         │                                         │
                         │  /ingest/article  ← 文章入庫            │
                         │  /report/generate ← 報告生成            │
                         │  /scrape/mops     ← MOPS爬蟲            │
                         │  /search          ← GraphRAG搜尋         │
                         └──────┬─────────────┬────────────────────┘
                                │             │
                    ┌───────────┘             └──────────────┐
                    ▼                                        ▼
        ┌──────────────────┐                    ┌──────────────────┐
        │ NLP 管線         │                    │ 報告生成管線     │
        │ jieba+GLiNER2    │                    │ Jinja2+WeasyPrint│
        └──────┬───────────┘                    └────────┬─────────┘
               │                                         │
        ┌──────┼──────────┐                              │
        ▼      ▼          ▼                              ▼
   [Qdrant] [Neo4j]  [PostgreSQL]                   [MinIO]
   向量搜尋  知識圖譜   原文+元數據                   PDF報告儲存
        │      │          │                              │
        └──────┴──────────┴──────────────────────────────┘
                                    │
                                    ▼
                         ┌──────────────────┐
                         │  WhatsApp 通知   │
                         │  （重要警報+摘要）│
                         └──────────────────┘
```

---

## 二、n8n vs DolphinScheduler 選擇指南

| 特性 | n8n | DolphinScheduler |
|------|-----|-----------------|
| **適合場景** | 事件驅動、快速整合 | 複雜 DAG、批次處理 |
| **UI** | 視覺化拖拉 | DAG 圖形編輯器 |
| **Python 整合** | Execute Command / HTTP | 原生 Python Task |
| **學習曲線** | ⭐⭐ 低 | ⭐⭐⭐ 中 |
| **資源消耗** | 低（Node.js） | 中（Java JVM） |
| **RSS 原生節點** | ✅ 有 | ❌ 需手寫 |
| **重試機制** | ✅ 有 | ✅ 有（更強大）|
| **任務依賴** | 基本 | ✅ 完整 DAG |
| **監控告警** | 基本 | ✅ SLA 監控 |
| **多機分散** | ❌ 單機 | ✅ 分散式 |
| **Mac Mini M4** | ✅ 首選 | ✅ 可用（較耗資源）|

**建議: 使用 n8n 作為主要引擎（Mac Mini 單機），DolphinScheduler 保留為未來 scale-out 方案**

---

## 三、n8n 工作流清單

| 檔案 | 名稱 | 觸發方式 | 說明 |
|------|------|---------|------|
| `01_rss_ingestion.json` | RSS 入庫管線 | 每 15 分鐘 | 爬取 42 個來源 → Redis 去重 → FastAPI 入庫 → 高優先詞警報 |
| `02_daily_report.json`  | 每日報告生成 | 週一至五 07:30 | Qdrant + Neo4j 查詢 → PDF 生成 → MinIO 儲存 → WhatsApp |
| `03_earnings_alert.json`| 財報 & 定價警報 | 多觸發 | MOPS 30分鐘 / SEC 21:00 / TrendForce 週一 |

---

## 四、快速啟動（Mac Mini 到後）

### Step 1: 啟動全棧
```bash
cd ~/news-graphrag
cp .env.example .env   # 填入密碼
docker compose up -d   # 啟動所有服務（含 n8n + MinIO）

# 等待服務就緒
docker compose ps      # 全部 healthy 後繼續
```

### Step 2: 初始化
```bash
# Ollama 拉取模型
docker exec graphrag_ollama ollama pull bge-m3
docker exec graphrag_ollama ollama pull qwen2.5:7b

# Neo4j Schema
docker exec -i graphrag_neo4j cypher-shell \
  -u neo4j -p changeme < scripts/init_neo4j_schema.cypher

# 確認 MinIO buckets 已建立
open http://localhost:9001  # minioadmin / minioadmin
# 應看到: reports / raw-articles / embeddings-backup
```

### Step 3: 匯入 n8n 工作流
```bash
open http://localhost:5678
# 1. 首次開啟 → 建立帳號（本機使用，隨便填）
# 2. 左側 Workflows → Import from file
# 3. 依序匯入:
#    n8n/workflows/01_rss_ingestion.json
#    n8n/workflows/02_daily_report.json
#    n8n/workflows/03_earnings_alert.json
# 4. 在 n8n 設定 Credentials:
#    - Redis: localhost:6379
#    - PostgreSQL: newsuser / changeme / newsdb
#    - (可選) SMTP for email
```

### Step 4: 啟動工作流
```bash
# 在 n8n UI 中逐一 Activate 工作流
# 或用 API 批次啟動:
curl -X POST http://localhost:5678/api/v1/workflows/activate \
  -H "Content-Type: application/json" \
  -d '{"ids": ["1","2","3"]}'
```

### Step 5: 驗證
```bash
# 等待 15 分鐘後確認資料進來
docker exec graphrag_postgres psql -U newsuser -d newsdb \
  -c "SELECT COUNT(*), MIN(crawled_at), MAX(crawled_at) FROM articles;"

docker exec graphrag_qdrant curl -s http://localhost:6333/collections | \
  jq '.result.collections[].points_count'

# 測試報告生成
curl -X POST http://localhost:8000/report/generate \
  -H "Content-Type: application/json" \
  -d '{"report_type":"daily_digest","date":"'$(date +%Y-%m-%d)'"}'
```

---

## 五、MinIO 儲存結構

```
MinIO Buckets:
  reports/
    ├── daily/
    │   ├── 2026-03-02.pdf    ← 每日報告
    │   ├── 2026-03-03.pdf
    │   └── ...
    ├── weekly/
    │   └── 2026-W09.pdf      ← 週報
    └── alerts/
        └── earnings-TSMC-2026-03-02.pdf  ← 財報快報

  raw-articles/
    └── 2026/03/02/
        ├── cnyes_semi_20260302_001.json
        └── reuters_tech_20260302_005.json

  embeddings-backup/
    └── qdrant_snapshot_20260302.tar.gz   ← 向量庫備份
```

---

## 六、報告類型 & 自動排程

| 報告類型 | 觸發 | 週期 | 格式 | 儲存 |
|---------|------|------|------|------|
| **每日產業日報** | n8n 07:30 | 週一~五 | PDF + HTML | MinIO + WhatsApp 摘要 |
| **財報快報** | MOPS / SEC 事件 | 即時 | PDF | MinIO + WhatsApp 緊急 |
| **定價週報** | TrendForce 週一 | 每週 | Markdown | PostgreSQL + WhatsApp |
| **地緣政治特報** | 關鍵詞觸發 | 事件 | PDF | MinIO + WhatsApp 緊急 |
| **TMF 交易摘要** | 每日 13:30 | 收盤後 | Markdown | PostgreSQL |

---

## 七、監控服務端口

| 服務 | URL | 說明 |
|------|-----|------|
| **n8n 工作流** | http://localhost:5678 | 工作流管理、執行歷史 |
| **MinIO 控制台** | http://localhost:9001 | 報告 PDF 瀏覽下載 |
| **FastAPI Docs** | http://localhost:8000/docs | API 文檔、手動測試 |
| **Qdrant Dashboard** | http://localhost:6333/dashboard | 向量集合瀏覽 |
| **Neo4j Browser** | http://localhost:7474 | 知識圖譜視覺化 |
| **DolphinScheduler** | http://localhost:12345 | （可選）DAG 管理 |
