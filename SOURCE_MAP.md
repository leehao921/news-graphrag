# 新聞來源地圖
**版本**: v1.0 | **來源總數**: 42個 | **自動爬取**: 28個

---

## 一、架構總覽

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      新聞來源四層架構                                    │
│                                                                         │
│  Layer 1 RSS（免費即時）    Layer 2 Scrape     Layer 3 API              │
│  ┌──────────────────┐     ┌──────────────┐    ┌──────────────┐         │
│  │ 鉅亨 / Reuters   │     │ MOPS 重大訊息│    │ SEC EDGAR    │         │
│  │ EE Times         │     │ TSMC IR Page │    │ Yahoo Finance│         │
│  │ TrendForce Press │     │ TrendForce   │    │ SOX Index    │         │
│  │ ISW / AEI        │     │ 財報日曆     │    │              │         │
│  │ Chip Wars        │     │              │    │              │         │
│  └──────────────────┘     └──────────────┘    └──────────────┘         │
│          ↓ feedparser            ↓ Playwright        ↓ httpx           │
│                                                                         │
│                    ┌────────────────────────┐                          │
│  Layer 4 Premium   │  人工上傳 / Email解析  │                          │
│                    │ Gartner / IC Insights  │                          │
│                    │ MS研究報告 / DigiTimes │                          │
│                    └────────────────────────┘                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 二、來源地圖（按領域）

### 🔬 半導體技術 × 產業鏈

| 優先級 | 來源 | 語言 | 層級 | 更新頻率 | 訂閱 |
|--------|------|------|------|---------|------|
| ⭐⭐⭐ | **TrendForce** | 中/英 | L1+L2 | 週 | 免費 |
| ⭐⭐⭐ | **EE Times** | 英 | L1 | 每小時 | 免費 |
| ⭐⭐⭐ | **DigiTimes Asia** | 中/英 | L1 | 每小時 | 摘要免費 |
| ⭐⭐⭐ | **SemiAnalysis** | 英 | L1 | 週 | 部分付費 |
| ⭐⭐ | Tom's Hardware Semi | 英 | L1 | 每小時 | 免費 |
| ⭐⭐ | TechInsights Blog | 英 | L1 | 每日 | 免費 |
| ⭐⭐ | Chip Wars (Substack) | 英 | L1 | 週 | 免費 |
| ⭐⭐ | SEMI Global Update | 英 | L1 | 週 | 免費 |
| ⭐⭐ | Fabricated Knowledge | 英 | L1 | 週 | 部分付費 |
| ⭐ | Semiconductor Digest | 英 | L1 | 每日 | 免費 |
| 💎 | Gartner 季報 | 英 | L4 | 季 | **付費** |
| 💎 | IC Insights | 英 | L4 | 季 | **付費** |
| 💎 | DigiTimes Research | 中 | L4 | 月/季 | **付費** |

**關鍵指標涵蓋**:
- DRAM/NAND 定價（TrendForce 月報）
- HBM 需求預測（TrendForce + SemiAnalysis）
- CoWoS 先進封裝產能（DigiTimes + TechInsights）
- 製程節點進展（EE Times + Tom's Hardware）
- BB Ratio 設備訂單（SEMI）

---

### 📊 台灣本地財經 × 財報

| 優先級 | 來源 | 語言 | 層級 | 更新頻率 | 特色 |
|--------|------|------|------|---------|------|
| ⭐⭐⭐ | **MOPS 公開資訊觀測站** | 中 | L2 | 即時 | 法定公告，最權威 |
| ⭐⭐⭐ | **鉅亨網半導體** | 中 | L1 | 15分 | 個股即時，含評論 |
| ⭐⭐⭐ | **台積電 IR** | 中/英 | L2 | 月/季 | 月營收/法說會 |
| ⭐⭐ | MoneyDJ | 中 | L1 | 30分 | 法說會轉播 |
| ⭐⭐ | 工商時報 | 中 | L1 | 每日 | 深度分析 |
| ⭐⭐ | 科技新報 | 中 | L1 | 每小時 | AI/半導體全面 |
| ⭐⭐ | 聯發科 IR | 中/英 | L2 | 月/季 | |
| ⭐ | 電子時報中文版 | 中 | L1 | 每小時 | 供應鏈情報 |

**財報重要日程（2026 Q1 預計）**:
```
3月中旬  → TSMC 2月營收（月10日前公告）
4月中旬  → TSMC Q1 2026 法說會
4月下旬  → MediaTek Q1 2026 法說會
（各公司法說會時間見 MOPS）
```

**MOPS 目標追蹤清單** (Top10電子股):
```
2330 台積電 | 2454 聯發科 | 2317 鴻海 | 2308 台達電
2382 廣達   | 2303 聯電   | 3711 日月光 | 3034 聯詠
2379 瑞昱   | 2412 中華電（無期貨）
```

---

### 🌐 國際財經 × 宏觀

| 優先級 | 來源 | 語言 | 層級 | 更新頻率 |
|--------|------|------|------|---------|
| ⭐⭐⭐ | **Reuters Technology** | 英 | L1 | 15分 |
| ⭐⭐⭐ | **SEC EDGAR** | 英 | L3 | 每日 | 
| ⭐⭐⭐ | **Yahoo Finance 財報日曆** | 英 | L2 | 每日 |
| ⭐⭐ | Financial Times Tech | 英 | L1 | 每小時 |
| ⭐⭐ | Wall Street Journal Tech | 英 | L1 | 每小時 |
| ⭐⭐ | Axios Technology | 英 | L1 | 每小時 |
| ⭐ | Seeking Alpha 半導體 | 英 | L2 | 每日 |

**SEC 財報追蹤對象**:
```
TSM (TSMC ADR)  | NVDA (NVIDIA)  | INTC (Intel)
MU (Micron)     | QCOM (Qualcomm)| AMD
AVGO (Broadcom) | ASML           | AMAT (Applied Materials)
KLAC (KLA Corp) | LRCX (Lam Research)
```

---

### 🌏 地緣政治 × 國際事件

| 優先級 | 來源 | 特色 | 頻率 |
|--------|------|------|------|
| ⭐⭐⭐ | **ISW 中台週報** | 台海軍事動態，最詳細 | 週 |
| ⭐⭐⭐ | **AEI 中台情勢** | 政策研究，台灣視角 | 週/月 |
| ⭐⭐ | CSIS 科技政策 | 出口管制/晶片戰爭 | 每日 |
| ⭐⭐ | The Diplomat 亞洲 | 印太地區政治 | 每日 |
| ⭐⭐ | Council on Foreign Relations | 全球視角 | 每日 |
| ⭐ | War on the Rocks | 軍事分析 | 週 |
| ⭐ | Geopolitical Monitor | 地緣政治專刊 | 週 |

**關鍵詞過濾規則**（節省爬取量）:
```python
geopolitics_keywords = [
    # 台海
    "Taiwan Strait", "台海", "軍演", "解放軍", "PLA",
    # 晶片管制
    "export control", "BIS", "Entity List", "chip ban",
    "CHIPS Act", "晶片法案",
    # 供應鏈
    "supply chain", "decoupling", "friend-shoring",
    # 中美貿易
    "tariff", "關稅", "制裁", "sanctions",
    # 能源/戰爭（影響台積電電費/氦氣供應）
    "US-Iran", "Hormuz", "oil price"
]
```

---

## 三、投資信號來源優先矩陣

```
高時效性
    ▲
    │   Reuters/鉅亨 ───→ MOPS重大訊息
    │   （通用財經）       （法定公告）
    │
    │   TrendForce ─────→ SemiAnalysis
    │   （定價/供需）       （深度分析）
    │
    │   ISW/AEI ────────→ FT/WSJ
    │   （地緣政治）        （全球宏觀）
    │
    └──────────────────────────────────→ 高分析深度
         快訊                           報告
```

**信號分類對應**:
| 信號類型 | 主要來源 | 反應速度 |
|---------|---------|---------|
| 月營收爆冷/超預期 | MOPS → 鉅亨 | < 1小時 |
| 法說會指引修訂 | MOPS → Reuters | < 30分鐘 |
| DRAM 漲跌預告 | TrendForce | T+1 週 |
| HBM 訂單消息 | DigiTimes/SemiAnalysis | T+1-3天 |
| 出口管制新法規 | Reuters → WSJ | < 1小時 |
| 台海演習升級 | ISW/AEI → Reuters | < 2小時 |
| AI 晶片需求變化 | SemiAnalysis/EE Times | T+3-7天 |
| 費城半導體指數 | Yahoo Finance | 即時 |

---

## 四、RSS Feed 端點速查

```yaml
# 可直接塞進 feedparser 的端點
rss_endpoints:
  # 台灣即時
  cnyes_semi:   "https://news.cnyes.com/news/cat/SEMICONDUCTOR/rss"
  cnyes_tw:     "https://news.cnyes.com/news/cat/TWSTOCK/rss"
  technews:     "https://technews.tw/feed/"
  technews_ai:  "https://technews.tw/category/ai/feed/"
  ctee:         "https://ctee.com.tw/feed/"
  moneydj:      "https://www.moneydj.com/rss/news.xml"
  digitimes_tw: "https://www.digitimes.com.tw/rss/news.xml"
  
  # 國際半導體
  eetimes:      "https://www.eetimes.com/feed/"
  tomshardware: "https://www.tomshardware.com/feeds/all"
  digitimes_en: "https://www.digitimes.com/rss/daily.xml"
  trendforce:   "https://www.trendforce.com/rss/presscenter.xml"
  semi_org:     "https://www.semi.org/en/rss/blog-newsletter-rss-feeds.xml"
  semianalysis: "https://www.semianalysis.com/feed"
  chip_wars:    "https://amritaroy.substack.com/feed"
  fab_knowledge:"https://www.fabricatedknowledge.com/feed"
  techinsights: "https://www.techinsights.com/blog/rss"
  semi_digest:  "https://www.semiconductor-digest.com/feed/"
  
  # 國際財經
  reuters_tech:   "https://feeds.reuters.com/reuters/technologyNews"
  reuters_mkt:    "https://feeds.reuters.com/reuters/businessNews"
  axios_tech:     "https://api.axios.com/feed/technology"
  ft_tech:        "https://www.ft.com/technology?format=rss"
  wsj_tech:       "https://feeds.a.dj.com/rss/RSSWSJD.xml"
  
  # 地緣政治
  isw:            "https://understandingwar.org/rss.xml"
  aei:            "https://www.aei.org/feed/"
  csis:           "https://www.csis.org/rss.xml"
  diplomat:       "https://thediplomat.com/feed/"
  cfr:            "https://www.cfr.org/rss/tech.xml"
  war_on_rocks:   "https://warontherocks.com/feed/"
```

---

## 五、下週 Mac Mini 整合優先順序

```
第1天安裝:
  ✅ feedparser + 所有 L1 RSS（立即跑通）
  ✅ 驗證去重（Redis SETNX）

第2天:
  ✅ MOPS 爬蟲（Playwright）
  ✅ TrendForce 新聞爬蟲
  ✅ SEC EDGAR API

第3天:
  ✅ NLP 管線（jieba + GLiNER2 + BGE-M3 embedding）
  ✅ Neo4j 圖建構
  ✅ 第一次向量轉移搜尋測試

第2週:
  ⬜ TSMC IR 財報 PDF 解析
  ⬜ 財報日曆事件觸發爬蟲
  ⬜ 地緣政治關鍵詞警報
```

---

*Source: `config/sources.yaml` + `config/crawl_schedule.yaml`*  
*42個來源 | 28個自動爬取 | 14個人工上傳*
