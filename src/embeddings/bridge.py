"""
Embedding Bridge — OpenAI 相容的開源 Embedding API
====================================================
提供 /v1/embeddings 端點，讓 OpenClaw 可以用
sentence-transformers 任何 HuggingFace 模型。

核心設計：
  1. OpenAI 相容格式（OpenClaw 直接對接）
  2. BGE-M3 多語言（與 Qdrant GraphRAG 同一向量空間）
  3. Redis 快取（避免重複 embed 相同文字）
  4. Cross-corpus 搜尋端點（記憶 + 新聞 + 知識庫）

啟動：
  uvicorn src.embeddings.bridge:app --host 0.0.0.0 --port 11235
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Optional, Union

import numpy as np
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# 模型設定
# ─────────────────────────────────────────────────────────────────

MODEL_NAME = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
CACHE_TTL = int(os.getenv("EMBED_CACHE_TTL", "86400"))        # 1天
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/1") # DB 1 (隔離)
MAX_BATCH = int(os.getenv("EMBED_MAX_BATCH", "32"))
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")

# ─────────────────────────────────────────────────────────────────
# 全域狀態
# ─────────────────────────────────────────────────────────────────

_model: Optional[SentenceTransformer] = None
_redis: Optional[aioredis.Redis] = None
_model_lock = asyncio.Lock()


async def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        async with _model_lock:
            if _model is None:
                logger.info(f"Loading embedding model: {MODEL_NAME}")
                # 在 thread pool 裡載入（避免阻塞 event loop）
                loop = asyncio.get_event_loop()
                _model = await loop.run_in_executor(
                    None, lambda: SentenceTransformer(MODEL_NAME)
                )
                dim = _model.get_sentence_embedding_dimension()
                logger.info(f"Model loaded: {MODEL_NAME} (dim={dim})")
    return _model


async def get_redis() -> Optional[aioredis.Redis]:
    global _redis
    if _redis is None:
        try:
            _redis = aioredis.from_url(REDIS_URL, decode_responses=False)
            await _redis.ping()
            logger.info("Redis cache connected")
        except Exception as e:
            logger.warning(f"Redis unavailable, caching disabled: {e}")
            _redis = None
    return _redis


# ─────────────────────────────────────────────────────────────────
# 快取工具
# ─────────────────────────────────────────────────────────────────

def _cache_key(model: str, text: str) -> str:
    h = hashlib.sha256(f"{model}:{text}".encode()).hexdigest()[:16]
    return f"embed:v1:{h}"


async def _get_cached(texts: list[str], model: str) -> dict[int, list[float]]:
    """從 Redis 批次取快取，回傳 {index: embedding}。"""
    r = await get_redis()
    if not r:
        return {}
    keys = [_cache_key(model, t) for t in texts]
    try:
        values = await r.mget(*keys)
        result = {}
        for i, v in enumerate(values):
            if v is not None:
                result[i] = json.loads(v)
        return result
    except Exception:
        return {}


async def _set_cached(texts: list[str], embeddings: list[list[float]], model: str):
    """批次寫入 Redis 快取。"""
    r = await get_redis()
    if not r:
        return
    pipe = r.pipeline()
    for text, emb in zip(texts, embeddings):
        key = _cache_key(model, text)
        pipe.setex(key, CACHE_TTL, json.dumps(emb))
    try:
        await pipe.execute()
    except Exception as e:
        logger.warning(f"Cache write failed: {e}")


# ─────────────────────────────────────────────────────────────────
# 核心 Embedding 函數
# ─────────────────────────────────────────────────────────────────

async def embed_texts(texts: list[str], model_name: str = MODEL_NAME) -> list[list[float]]:
    """
    批次 embed 文字，優先從 Redis 快取取。
    BGE-M3 特殊處理：encode 時加 instruction prefix（查詢 vs 文件）。
    """
    if not texts:
        return []

    # 1. 查快取
    cached = await _get_cached(texts, model_name)
    miss_indices = [i for i in range(len(texts)) if i not in cached]

    embeddings: dict[int, list[float]] = dict(cached)

    # 2. 批次 embed miss 的文字
    if miss_indices:
        model = await get_model()
        miss_texts = [texts[i] for i in miss_indices]

        # BGE-M3 encode（自動處理 dense embedding）
        loop = asyncio.get_event_loop()
        raw_embeddings = await loop.run_in_executor(
            None,
            lambda: model.encode(
                miss_texts,
                batch_size=min(MAX_BATCH, len(miss_texts)),
                normalize_embeddings=True,  # L2 normalize → cosine = dot product
                show_progress_bar=False,
            ),
        )

        new_embeddings = {
            miss_indices[j]: raw_embeddings[j].tolist()
            for j in range(len(miss_indices))
        }
        embeddings.update(new_embeddings)

        # 3. 寫快取
        new_texts = [texts[i] for i in miss_indices]
        new_vecs = [new_embeddings[i] for i in miss_indices]
        await _set_cached(new_texts, new_vecs, model_name)

    return [embeddings[i] for i in range(len(texts))]


# ─────────────────────────────────────────────────────────────────
# FastAPI 應用
# ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 預熱模型（啟動時就載入，避免第一次請求慢）
    logger.info("Warming up embedding model...")
    try:
        await embed_texts(["warmup text: 台灣半導體產業分析"])
        logger.info("Embedding Bridge ready")
    except Exception as e:
        logger.error(f"Warmup failed: {e}")
    yield
    # Cleanup
    if _redis:
        await _redis.aclose()


app = FastAPI(
    title="Embedding Bridge",
    description="OpenAI 相容的開源 Embedding API（BGE-M3 / sentence-transformers）",
    version="1.0.0",
    lifespan=lifespan,
)


# ─────────────────────────────────────────────────────────────────
# OpenAI 相容端點（OpenClaw 需要這個格式）
# ─────────────────────────────────────────────────────────────────

class EmbedRequest(BaseModel):
    """OpenAI /v1/embeddings 格式。"""
    model: str = MODEL_NAME
    input: Union[str, list[str]]  # 單字串或字串陣列
    encoding_format: str = "float"


class EmbedData(BaseModel):
    object: str = "embedding"
    index: int
    embedding: list[float]


class EmbedResponse(BaseModel):
    object: str = "list"
    data: list[EmbedData]
    model: str
    usage: dict


@app.post("/v1/embeddings", response_model=EmbedResponse)
async def create_embeddings(req: EmbedRequest):
    """
    OpenAI 相容的 /v1/embeddings。
    OpenClaw 設定 provider=openai + remote.baseUrl=http://localhost:11235/v1 即可對接。
    """
    # 統一成 list
    texts = [req.input] if isinstance(req.input, str) else req.input
    if not texts:
        raise HTTPException(status_code=400, detail="input is empty")

    t0 = time.perf_counter()
    try:
        vectors = await embed_texts(texts, req.model)
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    elapsed = time.perf_counter() - t0
    total_tokens = sum(len(t.split()) for t in texts)  # 估算

    logger.debug(f"Embedded {len(texts)} texts in {elapsed:.3f}s")

    return EmbedResponse(
        data=[
            EmbedData(index=i, embedding=vec)
            for i, vec in enumerate(vectors)
        ],
        model=req.model,
        usage={
            "prompt_tokens": total_tokens,
            "total_tokens": total_tokens,
        },
    )


# ─────────────────────────────────────────────────────────────────
# 批次端點（GraphRAG 入庫用）
# ─────────────────────────────────────────────────────────────────

class BatchEmbedRequest(BaseModel):
    texts: list[str]
    model: str = MODEL_NAME
    normalize: bool = True


@app.post("/embed/batch")
async def batch_embed(req: BatchEmbedRequest):
    """高吞吐批次 embed（GraphRAG 文章入庫時使用）。"""
    if len(req.texts) > 512:
        raise HTTPException(status_code=400, detail="Max 512 texts per batch")
    vectors = await embed_texts(req.texts, req.model)
    return {"embeddings": vectors, "dim": len(vectors[0]) if vectors else 0}


# ─────────────────────────────────────────────────────────────────
# Cross-Corpus 搜尋端點（關鍵增強功能）
# ─────────────────────────────────────────────────────────────────

class CrossSearchRequest(BaseModel):
    query: str
    min_score: float = Field(default=0.55, ge=0.0, le=1.0)
    limit: int = Field(default=10, ge=1, le=50)
    sources: list[str] = Field(default=["news", "memory"])
    # news | memory | siyuan | all


@app.post("/cross-search")
async def cross_corpus_search(req: CrossSearchRequest):
    """
    跨語料庫語義搜尋：同時搜尋 Qdrant 新聞 + OpenClaw 記憶。
    
    這是「統一語義空間」的核心端點：
    因為所有語料都用同一個 BGE-M3 模型 embed，
    cosine similarity 可以跨庫比較。
    
    供 FastAPI /search 端點或 n8n workflow 呼叫。
    """
    try:
        from qdrant_client import AsyncQdrantClient
        from qdrant_client.models import ScoredPoint
    except ImportError:
        raise HTTPException(status_code=503, detail="qdrant-client not installed")

    query_vec = (await embed_texts([req.query]))[0]
    client = AsyncQdrantClient(url=QDRANT_URL)

    results = []

    # 搜尋 Qdrant 新聞語料
    if "news" in req.sources or "all" in req.sources:
        try:
            hits = await client.query_points(
                collection_name="news_articles",
                query=query_vec,
                limit=req.limit,
                score_threshold=req.min_score,
            )
            for h in hits.points:
                p = h.payload or {}
                results.append({
                    "source": "news",
                    "score": h.score,
                    "title": p.get("title", ""),
                    "summary": p.get("summary", "")[:200],
                    "url": p.get("url", ""),
                    "published_at": p.get("published_at", ""),
                    "category": p.get("category", ""),
                })
        except Exception as e:
            logger.warning(f"Qdrant news search failed: {e}")

    # 搜尋 OpenClaw Memory 的 Qdrant 鏡像（如果 Path D 已建立）
    if "memory" in req.sources or "all" in req.sources:
        try:
            hits = await client.query_points(
                collection_name="openclaw_memory",
                query=query_vec,
                limit=req.limit,
                score_threshold=req.min_score,
            )
            for h in hits.points:
                p = h.payload or {}
                results.append({
                    "source": "memory",
                    "score": h.score,
                    "path": p.get("path", ""),
                    "snippet": p.get("text", "")[:300],
                    "start_line": p.get("start_line", 0),
                    "end_line": p.get("end_line", 0),
                })
        except Exception as e:
            logger.warning(f"Qdrant memory search failed (Path D not set up?): {e}")

    await client.close()

    # 按 score 排序
    results.sort(key=lambda x: x["score"], reverse=True)
    return {
        "query": req.query,
        "total": len(results),
        "results": results[:req.limit],
    }


# ─────────────────────────────────────────────────────────────────
# 健康檢查 & 狀態
# ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    model = await get_model()
    r = await get_redis()
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "dim": model.get_sentence_embedding_dimension(),
        "cache": "redis" if r else "disabled",
        "endpoints": {
            "openai_compat": "POST /v1/embeddings",
            "batch": "POST /embed/batch",
            "cross_search": "POST /cross-search",
        },
    }


@app.get("/v1/models")
async def list_models():
    """OpenAI /v1/models 相容（讓 OpenClaw 識別模型）。"""
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_NAME,
                "object": "model",
                "owned_by": "local",
                "permission": [],
            }
        ],
    }
