"""
Embedding Bridge Unit Tests
測試 OpenAI 相容端點、快取邏輯、cross-search 格式。
不需要實際的 sentence-transformers（使用 mock）。
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient


# ─── Fixtures ────────────────────────────────────────────────────

@pytest.fixture
def mock_model():
    """Mock SentenceTransformer 避免實際載入模型（1.1GB）。"""
    model = MagicMock()
    model.get_sentence_embedding_dimension.return_value = 1024
    # encode 回傳 numpy-like float array
    import numpy as np
    model.encode = MagicMock(
        return_value=np.array([[0.1] * 1024, [0.2] * 1024, [0.3] * 1024])
    )
    return model


@pytest.fixture
def mock_redis():
    """Mock Redis，預設快取 miss。"""
    r = AsyncMock()
    r.ping = AsyncMock(return_value=True)
    r.mget = AsyncMock(return_value=[None, None, None])  # 全部 cache miss
    r.pipeline = MagicMock(return_value=AsyncMock())
    r.pipeline.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    r.pipeline.return_value.__aexit__ = AsyncMock(return_value=None)
    return r


@pytest.fixture
def bridge_app(mock_model, mock_redis):
    """建立測試用的 bridge app（注入 mock）。"""
    with patch("src.embeddings.bridge._model", mock_model), \
         patch("src.embeddings.bridge._redis", mock_redis), \
         patch("src.embeddings.bridge.get_model", AsyncMock(return_value=mock_model)), \
         patch("src.embeddings.bridge.get_redis", AsyncMock(return_value=mock_redis)):
        from src.embeddings.bridge import app
        yield TestClient(app)


# ─── OpenAI 相容格式測試 ──────────────────────────────────────────

class TestOpenAICompatEndpoint:
    """驗證 OpenClaw 期望的 /v1/embeddings 格式。"""

    def test_single_string_input(self, bridge_app):
        """OpenClaw 有時傳單一字串（非陣列）。"""
        resp = bridge_app.post(
            "/v1/embeddings",
            json={"model": "BAAI/bge-m3", "input": "TMF 台指期貨"},
            headers={"Authorization": "Bearer local-bridge"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert len(data["data"]) == 1
        assert data["data"][0]["object"] == "embedding"
        assert data["data"][0]["index"] == 0
        assert isinstance(data["data"][0]["embedding"], list)
        assert len(data["data"][0]["embedding"]) == 1024

    def test_batch_string_array(self, bridge_app):
        """批次 embed（OpenClaw 建立 chunks 時使用）。"""
        texts = [
            "TMF 微型台指 OFI 訂單流",
            "TSMC HBM 產能擴張 2026",
            "半導體供應鏈地緣政治風險",
        ]
        resp = bridge_app.post(
            "/v1/embeddings",
            json={"model": "BAAI/bge-m3", "input": texts},
            headers={"Authorization": "Bearer test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) == 3
        for i, entry in enumerate(data["data"]):
            assert entry["index"] == i
            assert len(entry["embedding"]) == 1024
        assert data["model"] == "BAAI/bge-m3"
        assert "usage" in data

    def test_empty_input_rejected(self, bridge_app):
        """空輸入應回傳 400。"""
        resp = bridge_app.post(
            "/v1/embeddings",
            json={"model": "BAAI/bge-m3", "input": []},
        )
        assert resp.status_code == 400

    def test_models_endpoint(self, bridge_app):
        """OpenClaw 可能呼叫 /v1/models 識別模型。"""
        resp = bridge_app.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert len(data["data"]) >= 1
        assert data["data"][0]["id"] is not None

    def test_health_endpoint(self, bridge_app):
        """健康檢查端點。"""
        resp = bridge_app.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "model" in data
        assert "dim" in data


# ─── 快取邏輯測試 ─────────────────────────────────────────────────

class TestEmbeddingCache:
    """驗證 Redis 快取的 hit/miss 行為。"""

    @pytest.mark.asyncio
    async def test_cache_miss_calls_model(self, mock_model, mock_redis):
        """Cache miss 時應呼叫 sentence-transformers encode。"""
        import numpy as np
        mock_redis.mget = AsyncMock(return_value=[None])  # miss

        with patch("src.embeddings.bridge._model", mock_model), \
             patch("src.embeddings.bridge._redis", mock_redis), \
             patch("src.embeddings.bridge.get_model", AsyncMock(return_value=mock_model)), \
             patch("src.embeddings.bridge.get_redis", AsyncMock(return_value=mock_redis)):
            from src.embeddings.bridge import embed_texts
            result = await embed_texts(["test query"])

        assert len(result) == 1
        assert len(result[0]) == 1024
        mock_model.encode.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_hit_skips_model(self, mock_model, mock_redis):
        """Cache hit 時不應呼叫 encode。"""
        cached_vec = [0.5] * 1024
        mock_redis.mget = AsyncMock(return_value=[json.dumps(cached_vec)])

        with patch("src.embeddings.bridge._model", mock_model), \
             patch("src.embeddings.bridge._redis", mock_redis), \
             patch("src.embeddings.bridge.get_model", AsyncMock(return_value=mock_model)), \
             patch("src.embeddings.bridge.get_redis", AsyncMock(return_value=mock_redis)):
            from src.embeddings.bridge import embed_texts
            result = await embed_texts(["cached text"])

        assert result[0] == cached_vec
        mock_model.encode.assert_not_called()

    @pytest.mark.asyncio
    async def test_partial_cache_hit(self, mock_model, mock_redis):
        """部分 cache hit：只對 miss 的文字呼叫 encode。"""
        import numpy as np
        cached_vec = [0.9] * 1024
        # 第 1 個 hit，第 2 個 miss
        mock_redis.mget = AsyncMock(return_value=[json.dumps(cached_vec), None])
        mock_model.encode = MagicMock(return_value=np.array([[0.1] * 1024]))

        with patch("src.embeddings.bridge._model", mock_model), \
             patch("src.embeddings.bridge._redis", mock_redis), \
             patch("src.embeddings.bridge.get_model", AsyncMock(return_value=mock_model)), \
             patch("src.embeddings.bridge.get_redis", AsyncMock(return_value=mock_redis)):
            from src.embeddings.bridge import embed_texts
            result = await embed_texts(["hit text", "miss text"])

        assert len(result) == 2
        assert result[0] == cached_vec  # 來自 cache
        # encode 只被呼叫一次（只有 miss 的那個）
        mock_model.encode.assert_called_once()
        call_args = mock_model.encode.call_args[0][0]
        assert len(call_args) == 1  # 只有 1 個 miss


# ─── Cross-Corpus 搜尋格式測試 ───────────────────────────────────

class TestCrossSearch:
    """驗證 cross-search 端點的輸入/輸出格式。"""

    @pytest.mark.asyncio
    async def test_cross_search_response_format(self, bridge_app, mock_model, mock_redis):
        """Cross-search 應回傳統一的 source/score/title 格式。"""
        mock_qdrant_results = MagicMock()
        mock_qdrant_results.points = [
            MagicMock(
                score=0.82,
                payload={
                    "title": "TrendForce DRAM 價格上漲",
                    "summary": "DRAM 合約價 Q1 +90%",
                    "url": "https://example.com",
                    "category": "semiconductor",
                    "published_at": "2026-03-01",
                },
            )
        ]

        with patch("src.embeddings.bridge.embed_texts", AsyncMock(return_value=[[0.1] * 1024])):
            with patch("qdrant_client.AsyncQdrantClient") as mock_qdrant_cls:
                mock_client = AsyncMock()
                mock_client.query_points = AsyncMock(return_value=mock_qdrant_results)
                mock_client.close = AsyncMock()
                mock_qdrant_cls.return_value = mock_client

                resp = bridge_app.post(
                    "/cross-search",
                    json={
                        "query": "DRAM 價格趨勢",
                        "min_score": 0.5,
                        "limit": 5,
                        "sources": ["news"],
                    },
                )

        assert resp.status_code == 200
        data = resp.json()
        assert "query" in data
        assert "total" in data
        assert "results" in data
        # 每個結果有 source + score 欄位
        for r in data["results"]:
            assert "source" in r
            assert "score" in r


# ─── Batch Embed 端點測試 ─────────────────────────────────────────

class TestBatchEmbed:
    def test_batch_embed_basic(self, bridge_app):
        """批次 embed 端點（GraphRAG 文章入庫用）。"""
        resp = bridge_app.post(
            "/embed/batch",
            json={"texts": ["text1", "text2", "text3"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "embeddings" in data
        assert len(data["embeddings"]) == 3
        assert data["dim"] == 1024

    def test_batch_limit_enforced(self, bridge_app):
        """超過 512 個文字應回傳 400。"""
        resp = bridge_app.post(
            "/embed/batch",
            json={"texts": ["x"] * 513},
        )
        assert resp.status_code == 400
