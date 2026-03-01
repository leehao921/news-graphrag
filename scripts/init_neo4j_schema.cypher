// ─────────────────────────────────────────────────────────────────────────────
// Neo4j 知識圖譜 Schema 初始化
// 執行: cypher-shell -u neo4j -p changeme -f init_neo4j_schema.cypher
// ─────────────────────────────────────────────────────────────────────────────

// ── 唯一性約束 ───────────────────────────────────────────────────────────────
CREATE CONSTRAINT article_id IF NOT EXISTS
  FOR (a:Article) REQUIRE a.id IS UNIQUE;

CREATE CONSTRAINT keyword_normalized IF NOT EXISTS
  FOR (k:Keyword) REQUIRE k.normalized IS UNIQUE;

CREATE CONSTRAINT entity_name_type IF NOT EXISTS
  FOR (e:Entity) REQUIRE (e.name, e.entity_type) IS NODE KEY;

CREATE CONSTRAINT topic_id IF NOT EXISTS
  FOR (t:Topic) REQUIRE t.id IS UNIQUE;

CREATE CONSTRAINT event_id IF NOT EXISTS
  FOR (ev:Event) REQUIRE ev.id IS UNIQUE;

// ── 索引：提升查詢效能 ──────────────────────────────────────────────────────
CREATE INDEX article_published_at IF NOT EXISTS
  FOR (a:Article) ON (a.published_at);

CREATE INDEX article_source IF NOT EXISTS
  FOR (a:Article) ON (a.source);

CREATE INDEX article_sentiment IF NOT EXISTS
  FOR (a:Article) ON (a.sentiment_score);

CREATE INDEX keyword_domain IF NOT EXISTS
  FOR (k:Keyword) ON (k.domain);

CREATE INDEX entity_type IF NOT EXISTS
  FOR (e:Entity) ON (e.entity_type);

CREATE INDEX entity_ticker IF NOT EXISTS
  FOR (e:Entity) ON (e.ticker);

// ── 全文搜尋索引 ─────────────────────────────────────────────────────────────
CREATE FULLTEXT INDEX article_fulltext IF NOT EXISTS
  FOR (a:Article) ON EACH [a.title, a.summary];

CREATE FULLTEXT INDEX keyword_fulltext IF NOT EXISTS
  FOR (k:Keyword) ON EACH [k.text, k.normalized];

// ── 圖資料科學投影（GDS）預建 ───────────────────────────────────────────────
// 注意: GDS 投影在查詢時動態建立，以下為參考用途

// PageRank 投影（文章影響力分析）:
// CALL gds.graph.project('article_network',
//   'Article',
//   {PRECEDES: {orientation: 'NATURAL'}, RELATED_TO: {orientation: 'UNDIRECTED'}}
// )

// Node2Vec 投影（實體 embedding 增強）:
// CALL gds.node2vec.stream('entity_network', {
//   embeddingDimension: 128,
//   walkLength: 10,
//   iterations: 5
// })

// ── 樣板節點：預填重要實體 ──────────────────────────────────────────────────
// 台灣半導體大廠
MERGE (e:Entity {name: "台積電", entity_type: "COMPANY"})
  ON CREATE SET e.ticker = "2330", e.aliases = ["TSMC", "台積", "TSM"],
                e.created_at = datetime();

MERGE (e:Entity {name: "聯發科", entity_type: "COMPANY"})
  ON CREATE SET e.ticker = "2454", e.aliases = ["MediaTek", "MTK"],
                e.created_at = datetime();

MERGE (e:Entity {name: "鴻海", entity_type: "COMPANY"})
  ON CREATE SET e.ticker = "2317", e.aliases = ["Foxconn", "富士康"],
                e.created_at = datetime();

MERGE (e:Entity {name: "台達電", entity_type: "COMPANY"})
  ON CREATE SET e.ticker = "2308", e.aliases = ["Delta"],
                e.created_at = datetime();

MERGE (e:Entity {name: "廣達", entity_type: "COMPANY"})
  ON CREATE SET e.ticker = "2382", e.aliases = ["Quanta"],
                e.created_at = datetime();

MERGE (e:Entity {name: "聯電", entity_type: "COMPANY"})
  ON CREATE SET e.ticker = "2303", e.aliases = ["UMC"],
                e.created_at = datetime();

MERGE (e:Entity {name: "日月光", entity_type: "COMPANY"})
  ON CREATE SET e.ticker = "3711", e.aliases = ["ASE"],
                e.created_at = datetime();

// 關鍵技術關鍵詞
MERGE (k:Keyword {normalized: "hbm"})
  ON CREATE SET k.text = "HBM", k.domain = "semiconductor",
                k.idf_score = 0.95, k.created_at = datetime();

MERGE (k:Keyword {normalized: "cowos"})
  ON CREATE SET k.text = "CoWoS", k.domain = "semiconductor",
                k.idf_score = 0.92, k.created_at = datetime();

MERGE (k:Keyword {normalized: "3nm"})
  ON CREATE SET k.text = "3奈米", k.domain = "semiconductor",
                k.idf_score = 0.88, k.created_at = datetime();

MERGE (k:Keyword {normalized: "ai_chip"})
  ON CREATE SET k.text = "AI晶片", k.domain = "semiconductor",
                k.idf_score = 0.90, k.created_at = datetime();

// 地緣政治事件
MERGE (ev:Event {id: "geo_us_iran_2026"})
  ON CREATE SET ev.name = "美伊戰爭2026",
                ev.date = date("2026-03-01"),
                ev.type = "GEOPOLITICAL",
                ev.impact_sectors = ["energy", "semiconductor", "logistics"],
                ev.created_at = datetime();

MERGE (ev:Event {id: "geo_china_taiwan_threat"})
  ON CREATE SET ev.name = "中國台海威脅2026",
                ev.date = date("2026-01-01"),
                ev.type = "GEOPOLITICAL",
                ev.impact_sectors = ["semiconductor", "electronics"],
                ev.created_at = datetime();

// ── 完成確認 ─────────────────────────────────────────────────────────────────
RETURN "Schema initialized ✓" AS status;
