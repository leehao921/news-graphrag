"""
SiYuan 知識庫 API 路由
========================
掛載於 FastAPI 的 /knowledge/ prefix。
n8n workflow 04 會呼叫這些端點。
"""

from __future__ import annotations

import os
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from src.knowledge.siyuan_client import (
    SiYuanClient,
    SiYuanConfig,
    GraphRAGKnowledgeBase,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/knowledge", tags=["knowledge"])

# ─────────────────────────────────────────────────────────────────
# Client 工廠（從環境變數讀設定）
# ─────────────────────────────────────────────────────────────────

def get_siyuan_kb() -> GraphRAGKnowledgeBase:
    config = SiYuanConfig(
        base_url=os.getenv("SIYUAN_URL", "http://siyuan:6806"),
        token=os.getenv("SIYUAN_TOKEN", "graphrag2026"),
    )
    client = SiYuanClient(config)
    kb = GraphRAGKnowledgeBase(client)

    # 從環境變數還原筆記本 ID（避免每次重新查詢）
    nb_mapping = {
        "daily_reports": os.getenv("SIYUAN_NB_DAILY_REPORTS", ""),
        "semiconductor":  os.getenv("SIYUAN_NB_SEMICONDUCTOR", ""),
        "tmf_signals":    os.getenv("SIYUAN_NB_TMF_SIGNALS", ""),
        "geopolitical":   os.getenv("SIYUAN_NB_GEOPOLITICAL", ""),
        "fintel_graph":   os.getenv("SIYUAN_NB_FINTEL_GRAPH", ""),
    }
    # 過濾空值（第一次啟動尚未初始化時會動態建立）
    kb._notebook_ids = {k: v for k, v in nb_mapping.items() if v}
    return kb


# ─────────────────────────────────────────────────────────────────
# Pydantic Request/Response Models
# ─────────────────────────────────────────────────────────────────

class SemiconductorNoteReq(BaseModel):
    title: str
    content: str
    category: str = "General"   # Companies | Technologies | Markets | Policies
    ticker: Optional[str] = None

class GeopoliticalEventReq(BaseModel):
    title: str
    content: str
    region: str = "Taiwan"      # Taiwan | US-China | Middle East | Global
    impact_level: str = "medium"
    taiex_impact: Optional[str] = None

class TMFSignalReq(BaseModel):
    signal_type: str
    price: float
    ofi_value: float = 0.0
    iv_percentile: float = 50.0
    bb_lower: float = 0.0
    bb_upper: float = 0.0
    reasoning: str = ""
    action: str = "WATCH"       # WATCH | BUY | SELL | EXIT

class TMFSnapshotReq(BaseModel):
    snapshot_type: str = "open"  # open | close | mid
    timestamp: Optional[str] = None

class DailyBatchReq(BaseModel):
    date: str                    # YYYY-MM-DD
    include_signals: bool = True
    include_geo: bool = True

class SiYuanDocRes(BaseModel):
    status: str
    doc_id: str
    notebook: str = ""


# ─────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────

@router.get("/siyuan/health")
async def siyuan_health():
    """SiYuan 連線健康檢查。"""
    kb = get_siyuan_kb()
    ok = await kb.client.health_check()
    await kb.client.close()
    if not ok:
        raise HTTPException(status_code=503, detail="SiYuan unreachable")
    return {"status": "ok", "service": "siyuan"}


@router.post("/siyuan/init")
async def init_siyuan():
    """初始化 SiYuan 筆記本結構（首次部署使用）。"""
    kb = get_siyuan_kb()
    try:
        ids = await kb.initialize()
        await kb.client.close()
        return {
            "status": "initialized",
            "notebooks": ids,
            "env_hints": {
                f"SIYUAN_NB_{k.upper()}": v for k, v in ids.items()
            }
        }
    except Exception as e:
        logger.error(f"SiYuan init failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/siyuan/semiconductor", response_model=SiYuanDocRes)
async def push_semiconductor(req: SemiconductorNoteReq):
    """推送半導體分析筆記至 SiYuan。"""
    kb = get_siyuan_kb()
    try:
        doc_id = await kb.push_semiconductor_note(
            title=req.title,
            content=req.content,
            category=req.category,
            ticker=req.ticker,
        )
        await kb.client.close()
        return SiYuanDocRes(status="ok", doc_id=doc_id, notebook="semiconductor")
    except Exception as e:
        logger.error(f"Semiconductor push failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/siyuan/geopolitical", response_model=SiYuanDocRes)
async def push_geopolitical(req: GeopoliticalEventReq):
    """推送地緣政治事件至 SiYuan。"""
    kb = get_siyuan_kb()
    try:
        doc_id = await kb.push_geopolitical_event(
            title=req.title,
            content=req.content,
            region=req.region,
            impact_level=req.impact_level,
            taiex_impact=req.taiex_impact,
        )
        await kb.client.close()
        return SiYuanDocRes(status="ok", doc_id=doc_id, notebook="geopolitical")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/siyuan/tmf-signal", response_model=SiYuanDocRes)
async def push_tmf_signal(req: TMFSignalReq):
    """記錄 TMF 交易信號至 SiYuan。"""
    kb = get_siyuan_kb()
    try:
        doc_id = await kb.log_tmf_signal(
            signal_type=req.signal_type,
            price=req.price,
            ofi_value=req.ofi_value,
            iv_percentile=req.iv_percentile,
            bb_lower=req.bb_lower,
            bb_upper=req.bb_upper,
            reasoning=req.reasoning,
            action=req.action,
        )
        await kb.client.close()
        return SiYuanDocRes(status="ok", doc_id=doc_id, notebook="tmf_signals")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/siyuan/tmf-signal-snapshot")
async def tmf_signal_snapshot(req: TMFSnapshotReq, background_tasks: BackgroundTasks):
    """
    從 Redis 讀取當前 TMF 狀態並快照至 SiYuan。
    n8n 在 9:05 / 13:30 呼叫。
    """
    async def _snapshot():
        import redis.asyncio as aioredis
        r = aioredis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))

        try:
            price_raw   = await r.get("tmf:microstructure:latest")
            iv_raw      = await r.get("tmf:stream:options_iv")
            bb_lower    = float(await r.get("tmf:bb:lower") or 0)
            bb_upper    = float(await r.get("tmf:bb:upper") or 0)
            ofi_raw     = await r.get("tmf:ofi:1min")

            import json
            price_data  = json.loads(price_raw or '{}')
            iv_data     = json.loads(iv_raw or '{}')
            ofi_data    = json.loads(ofi_raw or '{}')

            kb = get_siyuan_kb()
            await kb.log_tmf_signal(
                signal_type=f"{req.snapshot_type}_snapshot",
                price=price_data.get("last_price", 0),
                ofi_value=ofi_data.get("ofi_1min", 0),
                iv_percentile=iv_data.get("iv_percentile", 50),
                bb_lower=bb_lower,
                bb_upper=bb_upper,
                reasoning=f"Auto-snapshot at market {req.snapshot_type}",
                action="WATCH",
            )
            await kb.client.close()
        except Exception as e:
            logger.error(f"TMF snapshot failed: {e}")
        finally:
            await r.aclose()

    background_tasks.add_task(_snapshot)
    return {"status": "accepted", "snapshot_type": req.snapshot_type}


@router.post("/siyuan/daily-report")
async def push_daily_report_siyuan(
    report_date: str,
    markdown_content: str,
    tmf_signal: str = "neutral",
    key_entities: list[str] = [],
    pdf_path: Optional[str] = None,
):
    """推送每日日報至 SiYuan 📰 Daily Reports 筆記本。"""
    kb = get_siyuan_kb()
    try:
        parsed_date = date.fromisoformat(report_date)
        pdf = Path(pdf_path) if pdf_path else None
        doc_id = await kb.push_daily_report(
            report_date=parsed_date,
            markdown_content=markdown_content,
            pdf_path=pdf,
            tmf_signal=tmf_signal,
            key_entities=key_entities,
        )
        await kb.client.close()
        return {"status": "ok", "doc_id": doc_id, "date": report_date}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/siyuan/daily-batch")
async def daily_batch_sync(req: DailyBatchReq, background_tasks: BackgroundTasks):
    """
    每日批次同步（n8n 07:35 觸發）：
    - 從 PostgreSQL 取出昨日文章摘要
    - 批次推送至 SiYuan 對應筆記本
    """
    async def _batch():
        import asyncpg
        dsn = os.getenv(
            "POSTGRES_DSN",
            "postgresql://newsuser:changeme@postgres:5432/newsdb"
        )
        conn = await asyncpg.connect(dsn)
        try:
            rows = await conn.fetch(
                """
                SELECT title, summary, category, ticker, source, published_at
                FROM articles
                WHERE DATE(published_at AT TIME ZONE 'Asia/Taipei') = $1::date
                  AND summary IS NOT NULL
                ORDER BY published_at DESC
                LIMIT 50
                """,
                req.date,
            )
            kb = get_siyuan_kb()

            for row in rows:
                cat = row["category"] or "general"
                content = (
                    f"**來源**: {row['source']}  \n"
                    f"**時間**: {row['published_at']}  \n\n"
                    f"{row['summary']}"
                )
                if cat in ("semiconductor", "earnings", "supply_chain"):
                    await kb.push_semiconductor_note(
                        title=row["title"],
                        content=content,
                        category="Markets",
                        ticker=row.get("ticker"),
                    )
                elif cat == "geopolitical":
                    await kb.push_geopolitical_event(
                        title=row["title"],
                        content=content,
                    )

            await kb.client.close()
            logger.info(f"Daily batch sync done: {len(rows)} articles → SiYuan")
        except Exception as e:
            logger.error(f"Daily batch sync failed: {e}")
        finally:
            await conn.close()

    background_tasks.add_task(_batch)
    return {"status": "accepted", "date": req.date}


@router.post("/siyuan/search-research")
async def save_search_to_siyuan(
    query: str,
    results: list[dict],
    graph_context: list[dict] = [],
):
    """將 GraphRAG 搜尋結果存為 SiYuan 研究筆記（FinTel-Graph 筆記本）。"""
    kb = get_siyuan_kb()
    try:
        doc_id = await kb.save_search_research(query, results, graph_context)
        await kb.client.close()
        return {"status": "ok", "doc_id": doc_id, "query": query}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
