# 思源筆記 知識庫結構設計
**SiYuan Knowledge Base — GraphRAG + TMF 整合**

---

## 一、筆記本架構（Notebook Hierarchy）

```
📔 GraphRAG 知識庫                  ← 主筆記本
│
├── 📁 每日報告/                    ← n8n 07:30 自動生成
│   ├── 2026/
│   │   ├── 03/
│   │   │   ├── 2026-03-02.md      ← 含執行摘要+TMF信號+新聞摘錄
│   │   │   └── 2026-03-03.md
│   │   └── ...
│   └── 📋 報告索引.md              ← 自動更新的報告清單
│
├── 📁 公司/                        ← 從 Neo4j 實體自動建立
│   ├── 🏭 半導體/
│   │   ├── 台積電 (2330).md        ← 含: 財報歷史 / 重要事件 / 新聞引用
│   │   ├── 聯發科 (2454).md
│   │   ├── 聯電 (2303).md
│   │   └── 日月光 (3711).md
│   ├── 🏭 IDM/
│   │   ├── Intel.md
│   │   ├── Micron.md
│   │   └── Samsung Memory.md
│   └── 🏭 設備材料/
│       ├── ASML.md
│       └── Applied Materials.md
│
├── 📁 技術概念/                    ← 關鍵技術節點（Neo4j Keyword）
│   ├── HBM.md                      ← 含: 定義 / 市場規模 / 主要廠商
│   ├── CoWoS 先進封裝.md
│   ├── DRAM 記憶體.md
│   ├── 3奈米製程.md
│   └── AI 晶片.md
│
├── 📁 地緣政治事件/                ← 重大事件紀錄
│   ├── 美伊戰爭 2026.md
│   ├── 晶片出口管制歷程.md
│   └── 台海風險追蹤.md
│
├── 📁 財報分析/                    ← SEC EDGAR + MOPS 財報
│   ├── TSMC/
│   │   ├── 2026-Q1 法說會.md
│   │   └── 月營收追蹤.md
│   └── MediaTek/
│       └── 2026-Q1 法說會.md
│
├── 📁 市場定價數據/                ← TrendForce 週報
│   ├── DRAM 定價歷史.md
│   ├── NAND 定價歷史.md
│   └── HBM 供需分析.md
│
├── 📁 TMF 交易日誌/                ← 交易決策記錄
│   ├── 2026/
│   │   └── 03/
│   │       └── 2026-03-02.md      ← OFI / IV / 進出場決策
│   └── 策略績效追蹤.md
│
└── 📁 策略知識庫/                  ← 策略文件（手動維護）
    ├── TMF V21 架構.md
    ├── 3口保守策略規則.md
    ├── 選擇權投機框架.md
    └── GraphRAG 架構概覽.md       ← 連結 ARCHITECTURE.md
```

---

## 二、頁面模板設計

### 公司頁面模板
```markdown
# {{公司名稱}} ({{股票代號}})

## 基本資料
- **類型**: 晶圓代工 / IDM / 設計 / 封裝 / 設備
- **市值**: NT$X 兆 / US$X B
- **主要產品**: [[HBM]], [[CoWoS]], [[3奈米製程]]
- **TAIEX 權重**: X%

## 最新財報
| 季度 | 營收 | YoY | EPS | 法說會日期 |
|------|------|-----|-----|-----------|
| 2026 Q1 | | | | |

## 重要新聞（自動同步）
{{news_citations}}

## 圖譜連結
- 客戶: [[NVIDIA]], [[AMD]]
- 競爭對手: [[三星]], [[Intel Foundry]]
- 關鍵技術: [[CoWoS]], [[3奈米製程]]

## 交易相關
- TMF 影響係數: X
- 近期 OFI 趨勢: 
```

### 每日報告模板
```markdown
# 📊 {{date}} 半導體產業日報

> 由 GraphRAG News System 自動生成 | {{article_count}} 則新聞

## 執行摘要
{{executive_summary}}

## TMF 期貨信號
- **方向**: 📈 偏多 / ⚖️ 中性 / 📉 偏空
- **信心度**: X%
- **多頭因素**: 
- **空頭因素**: 

## 半導體供應鏈
{{supply_chain_news}}

## 財報亮點
{{earnings_news}}

## 地緣政治
{{geopolitical_news}}

## 今日熱門實體
{{hot_entities}}

---
*[📥 完整 PDF 報告](minio://reports/daily/{{date}}.pdf)*
```

### TMF 交易日誌模板
```markdown
# 🎯 {{date}} TMF 交易日誌

## 開盤前分析（08:45）
- ATM IV: X% (X%ile)
- 15分 BB: 下緣 X / 上緣 X
- OFI 趨勢: 

## 交易記錄
| 時間 | 動作 | 口數 | 價格 | OFI | IV | 理由 |
|------|------|------|------|-----|----|----|
| 09:XX | BUY | 1 | | | | |

## 收盤覆盤
- 最終 PnL: +/- X pt
- 決策品質: ⭐⭐⭐
- 改善點: 

## 關聯新聞
{{related_news}}
```

---

## 三、雙向同步邏輯

```
GraphRAG → SiYuan (寫入)          SiYuan → GraphRAG (讀取)
─────────────────────────          ─────────────────────────
每日報告 → 筆記頁面                手動標注 → Neo4j 標籤更新
Neo4j 實體 → 公司/技術頁面          筆記連結 → 圖譜邊關係補充
新聞摘錄 → 引用區塊                人工洞察 → 策略規則更新
財報數據 → 表格區塊
TMF 決策 → 日誌區塊
```

---

## 四、SiYuan API 端點速查

```
Base URL: http://localhost:6806
Auth: Authorization: Token {SIYUAN_TOKEN}

筆記本:
  GET  /api/notebook/lsNotebooks         列出所有筆記本
  POST /api/notebook/createNotebook      建立筆記本
  POST /api/notebook/openNotebook        開啟筆記本

文件:
  POST /api/filetree/createDoc           建立文件（Markdown）
  POST /api/filetree/getDoc              讀取文件
  POST /api/filetree/searchDocs          搜尋文件

區塊:
  POST /api/block/insertBlock            插入區塊
  POST /api/block/appendBlock            附加區塊
  POST /api/block/updateBlock            更新區塊
  POST /api/block/getBlockBreadcrumb     取得區塊麵包屑

SQL 查詢（強大功能！）:
  POST /api/sql/query                    SQL 查詢內建 SQLite
  例: SELECT * FROM blocks WHERE content LIKE '%台積電%' LIMIT 10

屬性:
  POST /api/attr/setBlockAttrs           設定區塊屬性（用於標記來源 URL）
  POST /api/attr/getBlockAttrs           讀取區塊屬性
```
