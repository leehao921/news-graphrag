#!/usr/bin/env python3
"""
qmd-qdrant — OpenClaw QMD 後端的 Qdrant 實作
==============================================
用 Qdrant 取代 SQLite 作為 OpenClaw memory 的向量搜尋後端。

OpenClaw 以 qmd backend 模式 spawn 這個 script 作為子進程，
透過 stdin/stdout 與之溝通。

QMD 命令介面（OpenClaw 會呼叫的）：
  qmd_qdrant.py search  <query>   → 搜尋記憶
  qmd_qdrant.py vsearch <query>   → 向量搜尋（語義）
  qmd_qdrant.py query   <query>   → 查詢模式
  qmd_qdrant.py update            → 重新索引記憶檔案
  qmd_qdrant.py embed             → 生成 embeddings

輸出格式（stdout JSON array）：
  [
    {
      "path": "/path/to/MEMORY.md",
      "startLine": 10,
      "endLine": 25,
      "score": 0.82,
      "snippet": "## TMF 信號\n..."
    }
  ]

設定（環境變數）：
  QDRANT_URL=http://localhost:6333
  EMBED_URL=http://localhost:11235/v1   (Bridge API)
  MEMORY_COLLECTION=openclaw_memory
  OPENCLAW_WORKSPACE=~/.openclaw/workspace
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import httpx

# ─────────────────────────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────────────────────────

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
EMBED_URL = os.getenv("EMBED_URL", "http://localhost:11235/v1")
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
COLLECTION = os.getenv("MEMORY_COLLECTION", "openclaw_memory")
WORKSPACE = Path(os.getenv("OPENCLAW_WORKSPACE", "~/.openclaw/workspace")).expanduser()
MAX_RESULTS = int(os.getenv("QMD_MAX_RESULTS", "8"))
MIN_SCORE = float(os.getenv("QMD_MIN_SCORE", "0.35"))
CHUNK_SIZE = int(os.getenv("QMD_CHUNK_SIZE", "400"))    # tokens
CHUNK_OVERLAP = int(os.getenv("QMD_CHUNK_OVERLAP", "80"))

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(message)s",
    stream=sys.stderr,  # 所有 log 到 stderr，stdout 只輸出結果
)
logger = logging.getLogger("qmd-qdrant")


# ─────────────────────────────────────────────────────────────────
# Embedding 客戶端（呼叫 Bridge API）
# ─────────────────────────────────────────────────────────────────

async def embed_texts(texts: list[str]) -> list[list[float]]:
    """透過 Embedding Bridge 取得向量。"""
    if not texts:
        return []
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{EMBED_URL}/embeddings",
            headers={"Authorization": "Bearer local-bridge", "Content-Type": "application/json"},
            json={"model": EMBED_MODEL, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        return [entry["embedding"] for entry in data["data"]]


async def embed_query(query: str) -> list[float]:
    vectors = await embed_texts([query])
    return vectors[0] if vectors else []


# ─────────────────────────────────────────────────────────────────
# Qdrant 客戶端
# ─────────────────────────────────────────────────────────────────

async def ensure_collection(dim: int = 1024):
    """確保 openclaw_memory collection 存在。"""
    async with httpx.AsyncClient(timeout=15.0) as client:
        # 檢查是否存在
        try:
            resp = await client.get(f"{QDRANT_URL}/collections/{COLLECTION}")
            if resp.status_code == 200:
                return  # 已存在
        except Exception:
            pass

        # 建立 collection（dense 1024-dim）
        payload = {
            "vectors": {
                "size": dim,
                "distance": "Cosine",
            },
            "sparse_vectors": {
                "bm25": {
                    "index": {"type": "plain"}
                }
            },
            "optimizers_config": {"default_segment_number": 2},
        }
        resp = await client.put(
            f"{QDRANT_URL}/collections/{COLLECTION}",
            json=payload,
        )
        resp.raise_for_status()
        logger.info(f"Created Qdrant collection: {COLLECTION}")


async def qdrant_search_vector(query_vec: list[float], limit: int = MAX_RESULTS) -> list[dict]:
    """Qdrant 向量搜尋，回傳 scored points。"""
    payload = {
        "vector": query_vec,
        "limit": limit,
        "with_payload": True,
        "score_threshold": MIN_SCORE,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/search",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json().get("result", [])


async def qdrant_search_hybrid(query: str, query_vec: list[float], limit: int = MAX_RESULTS) -> list[dict]:
    """
    Hybrid search: dense cosine + sparse BM25 RRF fusion。
    比 OpenClaw builtin 的 SQLite FTS 更準確。
    """
    # 建立 sparse vector（keyword 頻率，簡化版）
    keywords = [w.lower() for w in query.split() if len(w) > 1]
    sparse_indices = [abs(hash(kw)) % 65535 for kw in keywords]
    sparse_values = [1.0 / (i + 1) for i in range(len(keywords))]

    payload = {
        "prefetch": [
            {
                "query": query_vec,
                "using": "dense",  # dense vector field
                "limit": limit * 2,
            },
            {
                "query": {"indices": sparse_indices, "values": sparse_values},
                "using": "bm25",
                "limit": limit * 2,
            },
        ],
        "query": {"fusion": "rrf"},  # Reciprocal Rank Fusion
        "limit": limit,
        "with_payload": True,
        "score_threshold": 0.0,  # RRF scores are different scale
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{QDRANT_URL}/collections/{COLLECTION}/points/query",
                json=payload,
            )
            if resp.status_code == 200:
                return resp.json().get("result", {}).get("points", [])
    except Exception:
        pass

    # Fallback: pure vector search
    return await qdrant_search_vector(query_vec, limit)


async def qdrant_upsert(points: list[dict]):
    """批次插入/更新 Qdrant 記憶 chunks。"""
    if not points:
        return
    payload = {"points": points, "wait": True}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.put(
            f"{QDRANT_URL}/collections/{COLLECTION}/points",
            json=payload,
        )
        resp.raise_for_status()


async def qdrant_delete_by_path(path: str):
    """刪除特定檔案的所有 chunks。"""
    payload = {
        "filter": {
            "must": [{"key": "path", "match": {"value": path}}]
        }
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/delete",
            json=payload,
        )


# ─────────────────────────────────────────────────────────────────
# Markdown Chunking
# ─────────────────────────────────────────────────────────────────

def chunk_markdown(text: str, path: str) -> list[dict]:
    """
    Markdown-aware chunking：
    - 按 ## 標題邊界分割
    - 超長段落再按行數切割
    - 保留 start_line, end_line metadata
    """
    lines = text.split("\n")
    chunks = []
    current_lines: list[str] = []
    current_start = 1
    token_estimate = 0  # 粗估 token 數（字元/4）

    def flush_chunk():
        nonlocal current_start, token_estimate
        if not current_lines:
            return
        content = "\n".join(current_lines).strip()
        if not content:
            return
        end_line = current_start + len(current_lines) - 1
        h = hashlib.sha256(f"{path}:{current_start}:{content}".encode()).hexdigest()[:12]
        chunks.append({
            "id": h,
            "path": path,
            "start_line": current_start,
            "end_line": end_line,
            "text": content,
        })
        current_start = end_line + 1
        current_lines.clear()
        token_estimate = 0

    for i, line in enumerate(lines, 1):
        # 在 ## 標題處強制分割
        if line.startswith("## ") and current_lines and token_estimate > 50:
            flush_chunk()
            current_start = i

        current_lines.append(line)
        token_estimate += len(line) // 4 + 1

        # 超過 chunk size 時分割
        if token_estimate >= CHUNK_SIZE:
            flush_chunk()
            current_start = i + 1

    flush_chunk()
    return chunks


# ─────────────────────────────────────────────────────────────────
# 索引更新
# ─────────────────────────────────────────────────────────────────

def collect_memory_files() -> list[Path]:
    """收集所有記憶 Markdown 檔案。"""
    patterns = [
        WORKSPACE / "MEMORY.md",
        WORKSPACE / "memory.md",
        WORKSPACE / "memory" / "**" / "*.md",
        WORKSPACE / "knowledge" / "semiconductor" / "**" / "*.md",
        WORKSPACE / "knowledge" / "vendor" / "**" / "*.md",
        WORKSPACE / "knowledge" / "trading" / "**" / "*.md",
    ]
    files: list[Path] = []
    for pattern in patterns:
        if "*" in str(pattern):
            files.extend(Path(p) for p in glob.glob(str(pattern), recursive=True))
        elif pattern.exists():
            files.append(pattern)
    return list(set(files))


def load_file_hashes() -> dict[str, str]:
    """從本地 cache 載入檔案 hash（避免重複 embed）。"""
    cache_path = Path.home() / ".openclaw" / "memory" / "qmd_qdrant_hashes.json"
    try:
        return json.loads(cache_path.read_text())
    except Exception:
        return {}


def save_file_hashes(hashes: dict[str, str]):
    cache_path = Path.home() / ".openclaw" / "memory" / "qmd_qdrant_hashes.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(hashes, indent=2))


async def cmd_update():
    """
    重新掃描記憶檔案，更新 Qdrant 索引。
    只處理有變更的檔案（hash-based）。
    """
    logger.info("Starting memory index update...")
    files = collect_memory_files()
    hashes = load_file_hashes()
    updated = 0
    skipped = 0

    # 確保 collection 存在（先 embed 一個空文字取維度）
    test_vec = await embed_texts(["test"])
    dim = len(test_vec[0]) if test_vec else 1024
    await ensure_collection(dim)

    for fpath in files:
        try:
            content = fpath.read_text(encoding="utf-8", errors="ignore")
            file_hash = hashlib.md5(content.encode()).hexdigest()
            path_str = str(fpath)

            if hashes.get(path_str) == file_hash:
                skipped += 1
                continue

            # 分割 + embed
            raw_chunks = chunk_markdown(content, path_str)
            if not raw_chunks:
                continue

            texts = [c["text"] for c in raw_chunks]
            vectors = await embed_texts(texts)

            # 刪除舊 chunks
            await qdrant_delete_by_path(path_str)

            # 插入新 chunks
            points = []
            for chunk, vec in zip(raw_chunks, vectors):
                points.append({
                    "id": abs(int(chunk["id"], 16)) % (2**63),  # Qdrant 需要整數 ID
                    "vector": vec,
                    "payload": {
                        "path": chunk["path"],
                        "start_line": chunk["start_line"],
                        "end_line": chunk["end_line"],
                        "text": chunk["text"],
                        "source": "memory",
                        "updated_at": int(time.time()),
                    },
                })
            await qdrant_upsert(points)

            hashes[path_str] = file_hash
            updated += 1
            logger.info(f"  Indexed: {fpath.name} ({len(raw_chunks)} chunks)")

        except Exception as e:
            logger.error(f"Failed to index {fpath}: {e}")

    save_file_hashes(hashes)
    logger.info(f"Update done: {updated} files updated, {skipped} unchanged")
    print(json.dumps({"updated": updated, "skipped": skipped}))


# ─────────────────────────────────────────────────────────────────
# 搜尋命令
# ─────────────────────────────────────────────────────────────────

def hits_to_qmd_format(hits: list[dict]) -> list[dict]:
    """
    將 Qdrant 結果轉換為 OpenClaw QMD 期望的格式。
    OpenClaw 解析：parseQmdQueryResultArray(stdout)
    """
    results = []
    for hit in hits:
        p = hit.get("payload", {})
        score = hit.get("score", 0.0)
        text = p.get("text", "")
        path = p.get("path", "")
        start = p.get("start_line", 1)
        end = p.get("end_line", start + text.count("\n"))

        # 格式：符合 OpenClaw QMD 解析器期望的欄位
        results.append({
            "path": path,
            "startLine": start,
            "endLine": end,
            "score": round(score, 4),
            "snippet": text[:700],  # maxSnippetChars
        })
    return results


async def cmd_search(query: str, mode: str = "hybrid"):
    """執行搜尋，輸出 JSON 到 stdout。"""
    if not query.strip():
        print("[]")
        return

    try:
        query_vec = await embed_query(query)

        if mode == "vsearch":
            hits = await qdrant_search_vector(query_vec, limit=MAX_RESULTS)
        else:
            hits = await qdrant_search_hybrid(query, query_vec, limit=MAX_RESULTS)

        results = hits_to_qmd_format(hits)

        if not results:
            print("No results found.")
            return

        print(json.dumps(results, ensure_ascii=False))

    except Exception as e:
        logger.error(f"Search failed: {e}")
        # QMD fallback：輸出 no results（讓 OpenClaw fallback 到 builtin）
        print("No results found.")


# ─────────────────────────────────────────────────────────────────
# Embed 命令（批次預計算，減少 on-demand 延遲）
# ─────────────────────────────────────────────────────────────────

async def cmd_embed():
    """預計算所有記憶檔案的 embeddings（定期執行）。"""
    await cmd_update()


# ─────────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="QMD-Qdrant: OpenClaw memory backend with Qdrant"
    )
    subparsers = parser.add_subparsers(dest="command")

    # search 命令
    sp = subparsers.add_parser("search", help="BM25 + 向量混合搜尋")
    sp.add_argument("query", nargs="+")

    # vsearch 命令
    sp = subparsers.add_parser("vsearch", help="純向量語義搜尋")
    sp.add_argument("query", nargs="+")

    # query 命令（alias for search）
    sp = subparsers.add_parser("query", help="查詢模式（同 search）")
    sp.add_argument("query", nargs="+")

    # update 命令
    subparsers.add_parser("update", help="重新索引所有記憶檔案")

    # embed 命令
    subparsers.add_parser("embed", help="預計算 embeddings")

    args = parser.parse_args()

    if args.command in ("search", "query"):
        query = " ".join(args.query)
        asyncio.run(cmd_search(query, mode="hybrid"))

    elif args.command == "vsearch":
        query = " ".join(args.query)
        asyncio.run(cmd_search(query, mode="vsearch"))

    elif args.command == "update":
        asyncio.run(cmd_update())

    elif args.command == "embed":
        asyncio.run(cmd_embed())

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
