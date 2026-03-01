# OpenClaw × 開源向量搜尋整合分析

> **目標**: 以自主開源的 embedding 方案取代付費 API，
> 並將 OpenClaw 的 memory_search 與 news-graphrag 知識庫
> 整合為**同一語義空間**（unified semantic space）。

---

## 一、為什麼「同一語義空間」是核心目標

```
當前痛點：
  memory_search("TMF OFI 策略")
    → 只搜尋 memory/*.md 的關鍵詞
    → 找不到 Qdrant 裡的半導體新聞
    → 找不到 SiYuan 裡的日報分析

理想狀態：
  memory_search("TMF OFI 策略")
    → 搜尋 memory/*.md  (OpenClaw 日常記憶)
    → + Qdrant news_articles  (GraphRAG 新聞)
    → + SiYuan 知識庫
    → 結果按語義相關度統一排序

實現條件：所有文件用「同一個 embedding 模型」
  → 向量可以跨庫比較 cosine similarity
```

---

## 二、架構選項完整評估

### Path A：Ollama 直連（零程式碼）

```
OpenClaw ──POST /v1/embeddings──▶ Ollama :11434
config: provider=openai, remote.baseUrl=http://localhost:11434/v1
```

**模型選擇**（Ollama 可直接 pull）：
| 模型 | 維度 | 特點 | 適合 |
|------|------|------|------|
| `nomic-embed-text` | 768 | 英文強，速度快 | 英文為主的記憶 |
| `mxbai-embed-large` | 1024 | 質量高，英文優先 | 英文知識庫 |
| `bge-m3` | 1024 | **多語言**，dense+sparse | ✅ 中英混合（你的場景） |
| `all-minilm` | 384 | 極輕量 | 快速原型 |

**與 GraphRAG 的對齊**：如果 GraphRAG 也用 `bge-m3`（已計畫），
則兩個系統的向量空間完全一致，可以跨庫搜尋。

**優點**：0 行程式碼，5 分鐘啟用  
**缺點**：依賴 Ollama 服務；BGE-M3 在 Ollama 上需特別驗證格式

---

### Path B：Local GGUF（純離線）

```
OpenClaw ──node-llama-cpp──▶ .gguf 本地模型檔
config: provider=local, local.modelPath=hf:BAAI/...
```

OpenClaw 內建 node-llama-cpp，支援直接從 HuggingFace 下載 GGUF：

```jsonc
"memory": {
  "provider": "local",
  "local": {
    "modelPath": "hf:ggml-org/embeddinggemma-300m-qat-q8_0-GGUF/embeddinggemma-300m-qat-Q8_0.gguf",
    "modelCacheDir": "~/.openclaw/model-cache"
  }
}
```

**優點**：完全離線，無服務依賴，OpenClaw 原生支援  
**缺點**：
- GGUF 格式的 embedding 模型選擇少（BGE-M3 無官方 GGUF）
- 無法與 Qdrant（sentence-transformers 格式）對齊向量空間
- 不支援中文的模型很有限

---

### Path C：Embedding Bridge（推薦整合路線）⭐

```
OpenClaw ──POST /v1/embeddings──▶ Bridge API :11235
                                      │
                         sentence-transformers
                         BGE-M3 / multilingual-e5
                                      │
                    (同一個模型) ←────┘
                         Qdrant GraphRAG
```

這是**核心方案**。用一個輕量 FastAPI 服務：
1. 對 OpenClaw 暴露 OpenAI 相容的 `/v1/embeddings`
2. 後端用 sentence-transformers 跑任何 HuggingFace 模型
3. 與 GraphRAG 用完全相同的模型 → 統一語義空間
4. 加入 cross-corpus 搜尋端點（可選增強）

**實作細節見下方 Section 三**

---

### Path D：QMD + Qdrant（最進階，完整替換）

```
OpenClaw ──spawn─▶ qmd-qdrant.py search "query"
(qmd backend)           │
                   Qdrant :6333
                   collection: openclaw_memory
                        │
                   BGE-M3 (Ollama/ST)
```

完全繞過 OpenClaw 的 SQLite，用 Qdrant 作為記憶後端：
- 一個 Qdrant 實例同時管理：news_articles + openclaw_memory + keywords
- 真正的 hybrid search（dense + sparse BM25 RRF）
- 圖譜增強：Neo4j 關係 → 向量查詢擴展

**優點**：最強大，全面整合，Qdrant 原生 hybrid 比 SQLite 強很多  
**缺點**：需要實作 qmd CLI 介面（~300 行 Python）

---

## 三、Path C 完整實作設計

### 3.1 整體資料流

```
┌─────────────────────────────────────────────────────────────┐
│                  統一語義平台（Mac Mini M4）                  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Embedding Bridge  :11235                 │  │
│  │                                                       │  │
│  │  POST /v1/embeddings       ← OpenClaw（記憶索引）     │  │
│  │  POST /v1/embeddings       ← GraphRAG（文章入庫）     │  │
│  │  POST /embed/batch         ← SiYuan 文件索引           │  │
│  │                                                       │  │
│  │  sentence-transformers: BGE-M3 (1024-dim)            │  │
│  │  + 請求快取（Redis）                                   │  │
│  │  + 批次處理（max 32 texts/request）                    │  │
│  └──────────────────────────────────────────────────────┘  │
│        │                    │                              │
│        ▼                    ▼                              │
│  ┌──────────┐      ┌─────────────────┐                    │
│  │ SQLite   │      │    Qdrant       │                    │
│  │ OpenClaw │      │ openclaw_memory │                    │
│  │ memory   │      │ news_articles   │                    │
│  │ (~70KB)  │      │ keywords/topics │                    │
│  └──────────┘      └─────────────────┘                    │
│                              │                              │
│                    ┌─────────────────┐                    │
│                    │    Neo4j        │                    │
│                    │ 知識圖譜        │                    │
│                    └─────────────────┘                    │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 增強：Cross-Corpus 搜尋

當 `memory_search` 在 SQLite 找不到足夠結果時，
Bridge 提供額外端點，可跨 Qdrant 知識庫搜尋：

```
GET /cross-search?q=TMF+OFI+策略&min_score=0.6
→ [
    { source: "memory", path: "memory/2026-03-01.md", score: 0.82 },
    { source: "news",   title: "TrendForce HBM 分析", score: 0.71 },
    { source: "siyuan", doc: "TMF Signals/2026-03", score: 0.68 }
  ]
```

---

## 四、OpenClaw Config 對應設定

### Path A 設定（立即可用）
```jsonc
// openclaw.json
"memory": {
  "provider": "openai",
  "model": "bge-m3",
  "remote": {
    "baseUrl": "http://localhost:11434/v1",
    "apiKey": "ollama"
  },
  "query": {
    "maxResults": 8,
    "minScore": 0.30,
    "hybrid": {
      "enabled": true,
      "vectorWeight": 0.75,
      "textWeight": 0.25,
      "mmr": { "enabled": true, "lambda": 0.7 },
      "temporalDecay": { "enabled": true, "halfLifeDays": 14 }
    }
  },
  "extraPaths": [
    "knowledge/semiconductor",
    "knowledge/vendor",
    "knowledge/trading"
  ]
}
```

### Path C 設定（Bridge 啟動後）
```jsonc
"memory": {
  "provider": "openai",
  "model": "BAAI/bge-m3",
  "remote": {
    "baseUrl": "http://localhost:11235/v1",
    "apiKey": "local-bridge"
  }
  // 其他設定同 Path A
}
```

### Path D 設定（QMD + Qdrant）
```jsonc
"memory": {
  "backend": "qmd",
  "qmd": {
    "command": "python3 /path/to/qmd_qdrant.py",
    "searchMode": "vsearch",
    "collections": [
      { "path": "~/.openclaw/workspace", "pattern": "MEMORY.md" },
      { "path": "~/.openclaw/workspace/memory", "pattern": "**/*.md" }
    ],
    "update": { "interval": "5m", "embedInterval": "60m" },
    "limits": { "maxResults": 8, "maxSnippetChars": 700 }
  }
}
```

---

## 五、決策樹

```
你現在有什麼？
│
├─ 只有 WSL2（Mac Mini 還沒到）
│   └─ → Path A（Ollama）：快速驗證，無需額外服務
│
├─ Mac Mini 到了，想要最簡單整合
│   └─ → Path A + extraPaths：利用現有 Ollama
│
├─ 想要 OpenClaw memory 和 GraphRAG 語義對齊
│   └─ → Path C（Bridge）：統一向量空間，最高價值
│
└─ 想要終極整合，Qdrant 管理一切
    └─ → Path D（QMD + Qdrant）：最強，最複雜
```

---

## 六、各路線時程評估

| Path | 實作時間 | 維護成本 | 語義統一 | 跨庫搜尋 |
|------|----------|----------|----------|----------|
| A Ollama 直連 | 10分鐘 | 極低 | ✅（同模型） | ❌ |
| B Local GGUF | 5分鐘 | 極低 | ❌（格式不同） | ❌ |
| C Embedding Bridge | 2-3小時 | 低 | ✅✅ | ✅ |
| D QMD + Qdrant | 1-2天 | 中 | ✅✅✅ | ✅✅ |

**建議執行順序**：A → C → D（漸進式）
