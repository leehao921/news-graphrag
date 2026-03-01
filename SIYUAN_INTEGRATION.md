# SiYuan 思源筆記 × News GraphRAG 整合指南

> **SiYuan** 是開源、自主託管、block-based 的知識管理工具。
> 本文件說明如何將 GraphRAG 自動產生的報告、信號、研究筆記同步至 SiYuan，
> 讓知識庫形成「活文件系統」，可以像 Obsidian 一樣瀏覽、連結、標注。

---

## 架構總覽

```
┌─────────────────────────────────────────────────────────┐
│                  News GraphRAG Stack                     │
│                                                          │
│  n8n Workflows          FastAPI Backend                  │
│  ┌────────────────┐     ┌───────────────────────────┐   │
│  │ 01_rss_ingest  │────▶│ POST /ingest/article       │   │
│  │ 02_daily_report│────▶│ POST /report/generate      │   │
│  │ 03_earnings    │────▶│ POST /report/earnings      │   │
│  │ 04_siyuan_sync │────▶│ POST /knowledge/siyuan/*   │   │
│  └────────────────┘     └──────────────┬──────────────┘   │
│                                        │                  │
│  Data Layer                            ▼                  │
│  Qdrant ─── Neo4j                 SiYuanClient            │
│  Redis  ─── PostgreSQL            GraphRAGKnowledgeBase   │
│  MinIO (PDF store)                     │                  │
└────────────────────────────────────────┼──────────────────┘
                                         │ REST API
                                         ▼
                              ┌─────────────────────┐
                              │  SiYuan 思源筆記     │
                              │  http://localhost:6806│
                              │                      │
                              │  📰 Daily Reports    │
                              │  🔬 Semiconductor    │
                              │  💹 TMF Signals      │
                              │  🌏 Geopolitical     │
                              │  📊 FinTel-Graph     │
                              └─────────────────────┘
```

---

## 筆記本架構

| 筆記本 | 用途 | 自動來源 |
|--------|------|----------|
| 📰 Daily Reports | 每日市場日報 (Markdown + PDF 連結) | n8n 02 + FastAPI /report/generate |
| 🔬 Semiconductor Analysis | 半導體分析：廠商/技術/市場/政策 | n8n 01 + 03 (財報) |
| 💹 TMF Trading Signals | 交易信號日誌 (開盤/盤中/收盤快照) | n8n 04 (9:05, 13:30) |
| 🌏 Geopolitical Monitor | 地緣政治事件 (台海/美中/中東) | n8n 01 (ISW/AEI/CSIS) |
| 📊 FinTel-Graph | GraphRAG 搜尋研究筆記 | 手動 /search API 觸發 |

### 子目錄結構

```
📰 Daily Reports/
  └── 2026-03/
      ├── 2026-03-01_daily_digest
      ├── 2026-03-02_daily_digest
      └── ...

🔬 Semiconductor Analysis/
  ├── Companies/          ← 廠商 (TSMC, CXMT, Samsung...)
  ├── Technologies/       ← 技術 (HBM, DRAM, NAND...)
  ├── Markets/            ← 市場定價與供需
  └── Policies/           ← 法規政策 (出口管制, 補貼)

💹 TMF Trading Signals/
  └── 2026-03/
      └── signal_log      ← 當月所有信號 (append模式)

🌏 Geopolitical Monitor/
  ├── Taiwan/             ← 台海情勢
  ├── US-China/           ← 美中科技戰
  ├── Middle East/        ← 中東局勢
  └── Global/             ← 全球事件

📊 FinTel-Graph/
  └── Research/
      └── 2026-03/        ← 每次查詢的研究記錄
```

---

## 快速啟動

### Step 1: 啟動服務

```bash
cd /path/to/news-graphrag
docker compose up -d siyuan neo4j qdrant postgres redis
```

### Step 2: 開啟 SiYuan Web UI

```
http://localhost:6806
# Access Code: graphrag2026  (or SIYUAN_TOKEN in .env)
```

### Step 3: 初始化筆記本結構

```bash
# 方法 A — 直接用 Python CLI
python -m src.knowledge.siyuan_client --init \
    --url http://localhost:6806 \
    --token graphrag2026

# 方法 B — 透過 FastAPI (需 api 服務啟動)
curl -X POST http://localhost:8000/knowledge/siyuan/init
```

輸出示例:
```json
{
  "status": "initialized",
  "notebooks": {
    "daily_reports": "20260301000001-abc",
    "semiconductor":  "20260301000002-def"
  },
  "env_hints": {
    "SIYUAN_NB_DAILY_REPORTS": "20260301000001-abc",
    "SIYUAN_NB_SEMICONDUCTOR":  "20260301000002-def"
  }
}
```

### Step 4: 更新 .env

```env
# 將 Step 3 輸出的 ID 填入
SIYUAN_URL=http://siyuan:6806
SIYUAN_TOKEN=graphrag2026
SIYUAN_NB_DAILY_REPORTS=20260301000001-abc
SIYUAN_NB_SEMICONDUCTOR=20260301000002-def
SIYUAN_NB_TMF_SIGNALS=20260301000003-ghi
SIYUAN_NB_GEOPOLITICAL=20260301000004-jkl
SIYUAN_NB_FINTEL_GRAPH=20260301000005-mno
```

### Step 5: 啟動完整棧

```bash
docker compose up -d
```

### Step 6: 匯入 n8n Workflow 04

```
http://localhost:5678 → Workflows → Import from file
→ 選擇 n8n/workflows/04_siyuan_sync.json
```

---

## API 端點參考

| Method | Path | 用途 |
|--------|------|------|
| GET | `/knowledge/siyuan/health` | SiYuan 連線狀態 |
| POST | `/knowledge/siyuan/init` | 初始化筆記本 |
| POST | `/knowledge/siyuan/semiconductor` | 推送半導體筆記 |
| POST | `/knowledge/siyuan/geopolitical` | 推送地緣政治事件 |
| POST | `/knowledge/siyuan/tmf-signal` | 記錄 TMF 信號 |
| POST | `/knowledge/siyuan/tmf-signal-snapshot` | Redis快照→SiYuan |
| POST | `/knowledge/siyuan/daily-report` | 推送日報 |
| POST | `/knowledge/siyuan/daily-batch` | PostgreSQL批次同步 |
| POST | `/knowledge/siyuan/search-research` | 搜尋結果存為研究筆記 |

### 範例請求

```bash
# 推送半導體新聞
curl -X POST http://localhost:8000/knowledge/siyuan/semiconductor \
  -H "Content-Type: application/json" \
  -d '{
    "title": "TrendForce: DRAM 合約價 Q1 +90% QoQ",
    "content": "## 分析\nDDR5 價格大幅反彈...",
    "category": "Markets",
    "ticker": "2303"
  }'

# 記錄 TMF 交易信號
curl -X POST http://localhost:8000/knowledge/siyuan/tmf-signal \
  -H "Content-Type: application/json" \
  -d '{
    "signal_type": "BB_lower_touch",
    "price": 35200,
    "ofi_value": 185.3,
    "iv_percentile": 42.1,
    "bb_lower": 35150,
    "bb_upper": 36800,
    "reasoning": "OFI>150 + 觸及BB下緣，入場做多",
    "action": "BUY"
  }'
```

---

## SiYuan 特色功能與 GraphRAG 整合

### 雙向連結（Backlinks）
SiYuan 的 `[[文件名]]` 語法可以建立文件間的關聯。
FastAPI 在建立文件時自動插入相關連結：

```markdown
# 2026-03-01 市場日報
相關分析: [[TSMC Q1 2026 業績展望]] [[美中科技戰最新動態]]
```

### 標籤系統（Tags）
每份自動文件包含 YAML frontmatter 標籤：

```yaml
date: 2026-03-01
signal: bullish
tags: daily-report, semiconductor, taiwan-stocks
```

### 圖譜視圖（Graph View）
SiYuan 內建文件關係圖（類似 Obsidian），可視化文件連結網絡：
- 日報 → 個股分析 → 地緣政治事件
- TMF 信號 → 產業背景 → 財報數據

### SQL 查詢
SiYuan 支援對塊資料庫進行 SQL 查詢：

```sql
-- 查詢所有看多信號
SELECT id, content, hpath FROM blocks
WHERE type='d' AND content LIKE '%BUY%'
ORDER BY updated DESC LIMIT 20;

-- 查詢本週半導體筆記
SELECT id, content FROM blocks
WHERE type='d'
  AND hpath LIKE '/Semiconductor%'
  AND updated >= strftime('%s','now','-7 days') * 1000
```

### Obsidian 相容性
SiYuan 可以直接開啟 Obsidian Vault（Markdown 格式）：
1. 將 `knowledge/` 目錄掛載至 SiYuan workspace
2. SiYuan 可讀取所有現有 `.md` 文件
3. 雙向連結語法完全相容

---

## 進階：SiYuan Plugin 開發

SiYuan 支援 TypeScript/JavaScript 插件（類似 Obsidian 插件）。
未來可開發「GraphRAG 搜尋插件」：

```typescript
// 在 SiYuan 中直接呼叫 GraphRAG API
const results = await fetch('http://localhost:8000/search', {
  method: 'POST',
  body: JSON.stringify({ query: '台積電 CoWoS 產能' })
});
// 結果直接插入當前文件
```

---

## 常見問題

**Q: SiYuan 在 Docker 內，API 如何從外部存取？**  
A: SiYuan 服務 `ports: ["6806:6806"]`，直接用 `http://localhost:6806` 存取。
FastAPI 在 Docker 內用 `http://siyuan:6806`（內部服務名稱）。

**Q: 如何備份 SiYuan 資料？**  
A: 資料存於 `siyuan_workspace` volume，備份指令：
```bash
docker run --rm -v siyuan_workspace:/data -v $(pwd)/backup:/backup alpine \
  tar czf /backup/siyuan-$(date +%Y%m%d).tar.gz /data
```

**Q: 可以在手機上存取 SiYuan 嗎？**  
A: 可以。SiYuan 提供 iOS/Android App，透過 LAN 連線 `http://[mac-mini-ip]:6806`。

**Q: 與 Obsidian 的主要差異？**  
| 特性 | SiYuan | Obsidian |
|------|--------|---------|
| 開源 | ✅ 完全開源 | ❌ 核心不開源 |
| Docker 部署 | ✅ 官方支援 | ❌ 無 |
| REST API | ✅ 完整 API | ❌ 無（插件才有） |
| 中文支援 | ✅ 優秀 | 🟡 一般 |
| Block 引用 | ✅ Block ID | ✅ Heading ID |
| 自動同步費用 | 免費（自主) | $8/月 |
