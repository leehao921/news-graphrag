-- ─────────────────────────────────────────────────────────────────────────────
-- PostgreSQL Schema 初始化
-- 儲存新聞原文、爬蟲記錄、重複去重 hash
-- ─────────────────────────────────────────────────────────────────────────────

-- 擴充套件
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";   -- 模糊字串搜尋

-- ── 新聞文章表 ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS articles (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title           TEXT NOT NULL,
    content         TEXT NOT NULL,
    summary         TEXT,
    url             TEXT UNIQUE NOT NULL,
    url_hash        CHAR(64) UNIQUE NOT NULL,   -- SHA-256 for dedup
    source          VARCHAR(50) NOT NULL,
    language        CHAR(2) DEFAULT 'zh',
    published_at    TIMESTAMPTZ NOT NULL,
    crawled_at      TIMESTAMPTZ DEFAULT NOW(),

    -- NLP 結果
    sentiment_score FLOAT CHECK (sentiment_score BETWEEN -1 AND 1),
    domains         TEXT[],                     -- ["semiconductor", "macro"]

    -- 向量庫 / 圖資料庫外鍵
    qdrant_vector_id    UUID,
    neo4j_article_id    TEXT,

    -- 狀態追蹤
    is_processed    BOOLEAN DEFAULT FALSE,
    processed_at    TIMESTAMPTZ,
    error_msg       TEXT
);

-- ── 關鍵詞表 ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS keywords (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    text            TEXT NOT NULL,
    normalized      TEXT UNIQUE NOT NULL,
    domain          VARCHAR(50) DEFAULT 'general',
    idf_score       FLOAT DEFAULT 0.5,
    qdrant_vector_id UUID,
    neo4j_keyword_id TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── 文章關鍵詞關聯表 ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS article_keywords (
    article_id      UUID REFERENCES articles(id) ON DELETE CASCADE,
    keyword_id      UUID REFERENCES keywords(id) ON DELETE CASCADE,
    tfidf_score     FLOAT NOT NULL,
    count           INTEGER DEFAULT 1,
    PRIMARY KEY (article_id, keyword_id)
);

-- ── 實體表 ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS entities (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    entity_type     VARCHAR(20) NOT NULL,
    ticker          VARCHAR(10),
    aliases         TEXT[],
    neo4j_entity_id TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS entities_name_type_idx
    ON entities(name, entity_type);

-- ── 文章實體關聯表 ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS article_entities (
    article_id      UUID REFERENCES articles(id) ON DELETE CASCADE,
    entity_id       UUID REFERENCES entities(id) ON DELETE CASCADE,
    confidence      FLOAT NOT NULL,
    count           INTEGER DEFAULT 1,
    PRIMARY KEY (article_id, entity_id)
);

-- ── 爬蟲記錄表 ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS crawl_logs (
    id              BIGSERIAL PRIMARY KEY,
    source          VARCHAR(50) NOT NULL,
    crawled_at      TIMESTAMPTZ DEFAULT NOW(),
    urls_found      INTEGER DEFAULT 0,
    urls_new        INTEGER DEFAULT 0,
    urls_duplicate  INTEGER DEFAULT 0,
    urls_failed     INTEGER DEFAULT 0,
    duration_ms     INTEGER,
    error_msg       TEXT
);

-- ── 查詢記錄表（用於評估 Retriever 效果）────────────────────────────────────
CREATE TABLE IF NOT EXISTS query_logs (
    id              BIGSERIAL PRIMARY KEY,
    query_text      TEXT NOT NULL,
    alpha           FLOAT DEFAULT 0.3,
    top_k           INTEGER DEFAULT 10,
    result_count    INTEGER,
    latency_ms      FLOAT,
    graph_expanded  BOOLEAN DEFAULT TRUE,
    transfer_keywords TEXT[],
    queried_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── 索引 ──────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS articles_published_at_idx ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS articles_source_idx ON articles(source);
CREATE INDEX IF NOT EXISTS articles_is_processed_idx ON articles(is_processed) WHERE NOT is_processed;
CREATE INDEX IF NOT EXISTS articles_title_trgm_idx ON articles USING GIN (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS articles_content_trgm_idx ON articles USING GIN (content gin_trgm_ops);

-- ── 自動更新 updated_at ───────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER keywords_updated_at
    BEFORE UPDATE ON keywords
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 完成
SELECT 'PostgreSQL schema initialized ✓' AS status;
