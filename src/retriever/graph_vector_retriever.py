"""
src/retriever/graph_vector_retriever.py

GraphVectorRetriever — 核心查詢引擎
向量搜尋 + Neo4j 圖遍歷 + 向量轉移（Vector Transfer）

算法:
  1. embed(query) → q_vec (1024-dim)
  2. Qdrant dense+sparse hybrid → initial top-k articles
  3. Neo4j 2-hop traversal → neighbor keyword/entity nodes
  4. Load neighbor vectors from Qdrant keywords collection
  5. q_transferred = normalize(q + α × mean(neighbor_vecs))
  6. Qdrant re-search with q_transferred → better results
  7. Graph-proximity re-rank → final results
"""
from __future__ import annotations

import time
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
from neo4j import GraphDatabase, Driver
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Prefetch, FusionQuery, Fusion, Filter,
    FieldCondition, MatchValue, DatetimeRange
)

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    article_id: str
    neo4j_id: str
    title: str
    summary: str
    url: str
    source: str
    published_at: str
    sentiment_score: float
    vector_score: float
    graph_proximity_score: float
    final_score: float
    matched_keywords: list[str]
    matched_entities: list[str]
    transfer_keywords: list[str]


class SparseEncoder:
    """BM25 稀疏向量編碼（簡化版，正式版用 qdrant-bm25）"""

    def encode(self, text: str) -> dict:
        """返回 {token_id: weight} 稀疏向量"""
        import hashlib
        tokens = text.lower().split()
        freq: dict[int, float] = {}
        for token in tokens:
            tid = int(hashlib.md5(token.encode()).hexdigest(), 16) % 50000
            freq[tid] = freq.get(tid, 0) + 1.0
        # TF normalization
        total = sum(freq.values())
        return {k: v / total for k, v in freq.items()}


class GraphVectorRetriever:
    """
    向量轉移混合查詢器

    Parameters
    ----------
    qdrant : QdrantClient
    neo4j_driver : neo4j.Driver
    embedder : callable(text: str) -> np.ndarray  # 1024-dim
    alpha : float  向量轉移強度 (0.0 = 純向量, 1.0 = 強轉移)
    vector_weight : float  最終分數中向量得分權重
    graph_weight : float   最終分數中圖鄰近度權重
    """

    def __init__(
        self,
        qdrant: QdrantClient,
        neo4j_driver: Driver,
        embedder,
        alpha: float = 0.3,
        vector_weight: float = 0.7,
        graph_weight: float = 0.3,
    ):
        self.qdrant = qdrant
        self.neo4j = neo4j_driver
        self.embedder = embedder
        self.alpha = alpha
        self.vector_weight = vector_weight
        self.graph_weight = graph_weight
        self._sparse_encoder = SparseEncoder()

    # ──────────────────────────────────────────────────────────────────────────
    # 主查詢入口
    # ──────────────────────────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        use_graph_expansion: bool = True,
        filters: Optional[dict] = None,
        alpha_override: Optional[float] = None,
    ) -> tuple[list[RetrievalResult], dict]:
        """
        Returns
        -------
        results : list[RetrievalResult]
        debug_info : dict  包含 latency、transfer_keywords 等診斷資訊
        """
        t0 = time.perf_counter()
        alpha = alpha_override if alpha_override is not None else self.alpha

        # Step 1: 查詢向量化
        q_vec = self.embedder(query)  # np.ndarray (1024,)
        logger.debug(f"Query embedded: {q_vec.shape}")

        # Step 2: 初次混合搜尋（dense + sparse hybrid RRF）
        qdrant_filter = self._build_qdrant_filter(filters)
        initial_hits = self._qdrant_hybrid_search(
            q_vec, query, limit=top_k * 3, qdrant_filter=qdrant_filter
        )
        logger.info(f"Initial hits: {len(initial_hits)}")

        transfer_keywords: list[str] = []
        final_q_vec = q_vec

        if use_graph_expansion and initial_hits and alpha > 0:
            # Step 3: Neo4j 圖遍歷 → 找鄰居節點
            neo4j_ids = [h.payload.get("neo4j_id") for h in initial_hits if h.payload.get("neo4j_id")]
            graph_neighbors = self._graph_expand(neo4j_ids, max_neighbors=30)
            logger.info(f"Graph neighbors found: {len(graph_neighbors)}")

            if graph_neighbors:
                # Step 4: 載入鄰居向量
                neighbor_vids = [n["vector_id"] for n in graph_neighbors if n.get("vector_id")]
                if neighbor_vids:
                    neighbor_vecs_data = self.qdrant.retrieve(
                        collection_name="keywords",
                        ids=neighbor_vids,
                        with_vectors=True,
                    )

                    # Step 5: 向量轉移
                    if neighbor_vecs_data:
                        final_q_vec = self._compute_vector_transfer(
                            q_vec, neighbor_vecs_data, alpha
                        )
                        transfer_keywords = [n["text"] for n in graph_neighbors[:10]]
                        logger.info(f"Vector transfer applied: α={alpha}, keywords={transfer_keywords[:5]}")

        # Step 6: 用轉移後向量二次搜尋
        if not np.array_equal(final_q_vec, q_vec):
            final_hits = self._qdrant_dense_search(final_q_vec, limit=top_k * 2, qdrant_filter=qdrant_filter)
        else:
            final_hits = initial_hits[:top_k * 2]

        # Step 7: 圖感知重排序
        initial_neo4j_ids = set(h.payload.get("neo4j_id") for h in initial_hits[:top_k])
        results = self._graph_rerank(final_hits, initial_neo4j_ids, top_k)

        latency_ms = (time.perf_counter() - t0) * 1000
        debug_info = {
            "latency_ms": round(latency_ms, 2),
            "initial_hits": len(initial_hits),
            "graph_expanded": use_graph_expansion and alpha > 0,
            "transfer_keywords": transfer_keywords,
            "alpha_used": alpha,
        }

        return results, debug_info

    # ──────────────────────────────────────────────────────────────────────────
    # 私有方法
    # ──────────────────────────────────────────────────────────────────────────

    def _qdrant_hybrid_search(self, q_vec: np.ndarray, query_text: str,
                              limit: int, qdrant_filter) -> list:
        """Dense + Sparse 混合搜尋（Reciprocal Rank Fusion）"""
        sparse_vec = self._sparse_encoder.encode(query_text)
        try:
            hits = self.qdrant.query_points(
                collection_name="news_articles",
                prefetch=[
                    Prefetch(query=q_vec.tolist(), using="dense", limit=limit),
                    # Prefetch(query=sparse_vec, using="sparse", limit=limit),
                    # 注意: sparse 需要 collection 支援，MVP 可先跳過
                ],
                query=FusionQuery(fusion=Fusion.RRF),
                limit=limit,
                query_filter=qdrant_filter,
                with_payload=True,
                with_vectors=False,
            ).points
        except Exception as e:
            # Fallback to dense only
            logger.warning(f"Hybrid search failed ({e}), falling back to dense")
            hits = self._qdrant_dense_search(q_vec, limit, qdrant_filter)
        return hits

    def _qdrant_dense_search(self, q_vec: np.ndarray, limit: int, qdrant_filter) -> list:
        return self.qdrant.query_points(
            collection_name="news_articles",
            query=q_vec.tolist(),
            using="dense",
            limit=limit,
            query_filter=qdrant_filter,
            with_payload=True,
        ).points

    def _build_qdrant_filter(self, filters: Optional[dict]) -> Optional[Filter]:
        if not filters:
            return None
        conditions = []
        if sources := filters.get("sources"):
            conditions.append(FieldCondition(key="source", match=MatchValue(any=sources)))
        if domains := filters.get("domains"):
            conditions.append(FieldCondition(key="domain", match=MatchValue(any=domains)))
        if lang := filters.get("language"):
            conditions.append(FieldCondition(key="language", match=MatchValue(value=lang)))
        if not conditions:
            return None
        from qdrant_client.models import Filter, Must
        return Filter(must=conditions)

    def _graph_expand(self, neo4j_ids: list[str], max_neighbors: int = 30) -> list[dict]:
        """
        Neo4j 2跳圖遍歷
        返回: [{"vector_id": str, "text": str, "edge_weight": float}, ...]
        """
        if not neo4j_ids:
            return []
        query = """
            UNWIND $ids AS article_id
            MATCH (a:Article {id: article_id})-[r:CONTAINS_KEYWORD|MENTIONS]->(n)
            WHERE n.vector_id IS NOT NULL
            WITH n, avg(r.tfidf) AS avg_weight
            ORDER BY avg_weight DESC
            LIMIT $limit
            RETURN n.vector_id AS vector_id,
                   coalesce(n.text, n.name) AS text,
                   avg_weight AS edge_weight
        """
        try:
            with self.neo4j.session() as session:
                result = session.run(query, ids=neo4j_ids, limit=max_neighbors)
                return [dict(row) for row in result]
        except Exception as e:
            logger.warning(f"Neo4j graph expand failed: {e}")
            return []

    def _compute_vector_transfer(
        self,
        q_vec: np.ndarray,
        neighbor_vecs_data: list,
        alpha: float,
    ) -> np.ndarray:
        """
        向量轉移計算核心

        q' = normalize(q + α × mean(neighbor_vectors))

        加權方式: 每個鄰居向量貢獻相等（未來可加 edge_weight 加權）
        """
        neighbor_matrix = np.vstack([
            np.array(pv.vector, dtype=np.float32)
            for pv in neighbor_vecs_data
            if pv.vector is not None
        ])
        if neighbor_matrix.shape[0] == 0:
            return q_vec

        # 鄰居向量均值
        transfer_component = neighbor_matrix.mean(axis=0)

        # 線性組合
        q_prime = q_vec + alpha * transfer_component

        # L2 正規化（Qdrant cosine 距離需要）
        norm = np.linalg.norm(q_prime)
        if norm < 1e-10:
            return q_vec
        return (q_prime / norm).astype(np.float32)

    def _graph_rerank(
        self,
        hits: list,
        initial_neo4j_ids: set[str],
        top_k: int,
    ) -> list[RetrievalResult]:
        """
        融合重排序：
        final_score = vector_weight × vector_score
                    + graph_weight × graph_proximity_score

        graph_proximity_score:
          1.0 = 在初次搜尋結果中（確定相關）
          0.5 = 一跳鄰居（圖相鄰）
          0.0 = 全新文件
        """
        results = []
        for hit in hits[:top_k * 2]:
            payload = hit.payload or {}
            neo4j_id = payload.get("neo4j_id", "")

            # 向量得分（Qdrant 分數，越高越好）
            vector_score = float(hit.score)

            # 圖鄰近度得分
            if neo4j_id in initial_neo4j_ids:
                graph_score = 1.0
            else:
                graph_score = self._get_graph_proximity(neo4j_id, initial_neo4j_ids)

            final_score = (
                self.vector_weight * vector_score
                + self.graph_weight * graph_score
            )

            results.append(RetrievalResult(
                article_id=payload.get("article_id", str(hit.id)),
                neo4j_id=neo4j_id,
                title=payload.get("title", ""),
                summary=payload.get("summary", ""),
                url=payload.get("url", ""),
                source=payload.get("source", ""),
                published_at=payload.get("published_at", ""),
                sentiment_score=float(payload.get("sentiment_score", 0.0)),
                vector_score=vector_score,
                graph_proximity_score=graph_score,
                final_score=final_score,
                matched_keywords=payload.get("keywords", []),
                matched_entities=payload.get("entities", []),
                transfer_keywords=[],  # 由 retrieve() 填入
            ))

        results.sort(key=lambda r: r.final_score, reverse=True)
        return results[:top_k]

    def _get_graph_proximity(self, neo4j_id: str, initial_ids: set[str]) -> float:
        """查詢 neo4j_id 與初始結果集的最短圖距離（簡化版：0.5 或 0.0）"""
        if not neo4j_id or not initial_ids:
            return 0.0
        try:
            query = """
                MATCH (a:Article {id: $target_id})-[:CONTAINS_KEYWORD|MENTIONS]-(shared)-
                      [:CONTAINS_KEYWORD|MENTIONS]-(b:Article)
                WHERE b.id IN $initial_ids
                RETURN count(b) > 0 AS is_neighbor
                LIMIT 1
            """
            with self.neo4j.session() as session:
                result = session.run(query, target_id=neo4j_id,
                                     initial_ids=list(initial_ids))
                row = result.single()
                return 0.5 if row and row["is_neighbor"] else 0.0
        except Exception:
            return 0.0


# ─────────────────────── Factory ─────────────────────────────────────────────

def create_retriever(
    qdrant_url: str = "http://localhost:6333",
    neo4j_uri: str = "bolt://localhost:7687",
    neo4j_user: str = "neo4j",
    neo4j_password: str = "changeme",
    ollama_url: str = "http://localhost:11434",
    embedding_model: str = "bge-m3",
    alpha: float = 0.3,
) -> GraphVectorRetriever:
    """便捷工廠函數"""
    import httpx

    qdrant = QdrantClient(url=qdrant_url)
    neo4j_driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    def embed(text: str) -> np.ndarray:
        resp = httpx.post(
            f"{ollama_url}/api/embeddings",
            json={"model": embedding_model, "prompt": text},
            timeout=30.0
        )
        resp.raise_for_status()
        return np.array(resp.json()["embedding"], dtype=np.float32)

    return GraphVectorRetriever(
        qdrant=qdrant,
        neo4j_driver=neo4j_driver,
        embedder=embed,
        alpha=alpha,
    )
