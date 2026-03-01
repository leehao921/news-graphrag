"""
GraphRAG FastAPI 主應用
供 n8n 工作流呼叫的後端核心 API

端點:
  POST /ingest/article          ← n8n RSS 入庫管線
  POST /report/generate         ← n8n 每日報告生成
  POST /report/earnings-analysis← n8n 財報分析
  POST /scrape/mops             ← MOPS 重大訊息爬蟲
  POST /scrape/trendforce-pricing ← TrendForce 定價爬蟲
  POST /search                  ← GraphRAG 向量轉移搜尋
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

log = logging.getLogger(__name__)


# ─────────────────── Lifespan ────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """啟動時初始化連線"""
    log.info("GraphRAG API 啟動中...")
    # TODO: 初始化 Qdrant, Neo4j, PostgreSQL 連線池
    yield
    log.info("GraphRAG API 關閉")


app = FastAPI(
    title="GraphRAG News API",
    description="新聞 GraphRAG 後端：入庫 + 搜尋 + 報告生成 + SiYuan 知識庫同步",
    version="1.1.0",
    lifespan=lifespan,
)

# ─── SiYuan 知識庫路由 ─────────────────────────────────────────────────────
from src.api.knowledge_routes import router as knowledge_router  # noqa: E402
app.include_router(knowledge_router)


# ─────────────────── 請求模型 ────────────────────────────────────────────────

class IngestArticleRequest(BaseModel):
    title: str
    content: str
    url: str
    source: str
    published_at: Optional[str] = None
    language: Optional[str] = "zh"


class ReportRequest(BaseModel):
    report_type: str = "daily_digest"
    date: str
    articles: Optional[list] = None
    hot_entities: Optional[list] = None
    format: str = "pdf"
    include_sections: list[str] = [
        "executive_summary",
        "semiconductor_supply_chain",
        "earnings_highlights",
        "geopolitical_events",
        "market_signals",
        "tmf_trading_implications",
    ]


class EarningsAnalysisRequest(BaseModel):
    company: str
    form_type: str
    filing_url: str
    analysis_focus: list[str] = ["taiwan_supply_chain", "ai_chip_demand"]


class MOPSScrapeRequest(BaseModel):
    tickers: list[str] = ["2330", "2454"]
    lookback_hours: int = 1


class TrendForcePricingRequest(BaseModel):
    products: list[str] = ["DRAM", "NAND", "HBM"]


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    alpha: float = 0.3
    use_graph_expansion: bool = True


# ─────────────────── 入庫端點 ────────────────────────────────────────────────

@app.post("/ingest/article")
async def ingest_article(req: IngestArticleRequest, background: BackgroundTasks):
    """
    n8n RSS 管線呼叫：
    接收文章 → 去重 → NLP → Embedding → Qdrant + Neo4j + PG
    """
    try:
        # 非同步處理（立即回應 n8n，背景處理）
        background.add_task(_process_article, req)
        return {
            "status": "queued",
            "url": req.url,
            "message": "文章已加入處理佇列",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _process_article(req: IngestArticleRequest):
    """背景執行：完整 NLP + Embedding + 圖建構"""
    from src.nlp.segmentor import segment_text
    from src.nlp.ner import extract_entities
    from src.nlp.keyword_extractor import extract_keywords
    from src.embeddings.bge_m3 import embed_text
    from src.vector_store.qdrant_client import store_article
    from src.graph.builder import add_article_to_graph

    text = f"{req.title}\n\n{req.content}"
    segments = segment_text(text)
    entities = extract_entities(text)
    keywords = extract_keywords(segments, top_k=20)
    vector = await embed_text(text)

    article_id = await store_article({
        "title": req.title,
        "content": req.content,
        "url": req.url,
        "source": req.source,
        "published_at": req.published_at,
        "keywords": [k.text for k in keywords],
        "entities": [e.name for e in entities],
        "vector": vector,
    })

    await add_article_to_graph(article_id, entities, keywords)
    log.info(f"✅ 文章處理完成: {req.url[:60]}")


# ─────────────────── 報告生成端點 ────────────────────────────────────────────

@app.post("/report/generate")
async def generate_report(req: ReportRequest):
    """
    n8n 每日報告觸發：
    查詢 Qdrant + Neo4j → LLM 摘要 → Jinja2 → WeasyPrint PDF
    返回: { pdf_path, html, executive_summary, article_count }
    """
    from src.report.generator import ReportGenerator

    generator = ReportGenerator()
    result = await generator.generate(
        report_type=req.report_type,
        date=req.date,
        articles=req.articles or [],
        hot_entities=req.hot_entities or [],
        sections=req.include_sections,
        output_format=req.format,
    )

    return {
        "report_date": req.date,
        "title": f"半導體 + 台股 產業日報 {req.date}",
        "executive_summary": result["executive_summary"],
        "article_count": result["article_count"],
        "minio_path": result.get("minio_path"),
        "report_html": result.get("html", ""),
        "pdf_bytes": result.get("pdf_b64"),  # Base64 encoded PDF
    }


@app.post("/report/earnings-analysis")
async def earnings_analysis(req: EarningsAnalysisRequest):
    """
    財報公告分析：
    下載 SEC 文件 → LLM 分析 → 台灣供應鏈影響評估
    """
    # 台灣影響評估邏輯
    taiwan_keywords = {
        "tsmc": 10, "advanced packaging": 8, "cowos": 9, "hbm": 8,
        "wafer": 7, "foundry": 8, "supply chain": 6, "taiwan": 9,
    }

    # 簡化版：回傳結構化分析
    impact_score = 5  # 1-10，實際由 LLM 計算
    tmf_direction = "NEUTRAL"

    return {
        "company": req.company,
        "form_type": req.form_type,
        "summary": f"【待實作】{req.company} {req.form_type} 財報分析",
        "taiwan_supply_chain_impact": "待分析",
        "taiwan_impact_score": impact_score,
        "tmf_direction": tmf_direction,
        "key_points": [],
        "analyzed_at": datetime.now().isoformat(),
    }


# ─────────────────── 爬蟲端點 ────────────────────────────────────────────────

@app.post("/scrape/mops")
async def scrape_mops(req: MOPSScrapeRequest):
    """
    MOPS 公開資訊觀測站重大訊息爬蟲
    Playwright 動態爬取，過濾目標股票的最新公告
    """
    # TODO: Playwright 爬蟲實作
    return {
        "status": "ok",
        "tickers_checked": req.tickers,
        "new_announcements": [],
        "scraped_at": datetime.now().isoformat(),
    }


@app.post("/scrape/trendforce-pricing")
async def scrape_trendforce_pricing(req: TrendForcePricingRequest):
    """
    TrendForce 記憶體定價爬蟲
    每週一更新 DRAM/NAND/HBM 定價趨勢
    """
    # TODO: 定價爬蟲實作
    return {
        "status": "ok",
        "dram_qoq_change": 0.0,
        "nand_qoq_change": 0.0,
        "hbm_status": "待取得",
        "tw_memory_impact": "中性",
        "updated_at": datetime.now().isoformat(),
    }


# ─────────────────── 搜尋端點 ────────────────────────────────────────────────

@app.post("/search")
async def search(req: SearchRequest):
    """
    GraphRAG 向量轉移搜尋
    Qdrant dense+sparse + Neo4j 圖遍歷 + 向量轉移
    """
    # TODO: 整合 GraphVectorRetriever
    return {
        "query": req.query,
        "results": [],
        "transfer_keywords": [],
        "latency_ms": 0.0,
    }


# ─────────────────── 健康檢查 ─────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "graphrag-api",
        "time": datetime.now().isoformat(),
    }
