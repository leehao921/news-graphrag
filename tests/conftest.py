"""
共用 pytest fixtures。
"""

import os

import pytest

# CI 環境下設定假的環境變數（避免連線外部服務）
os.environ.setdefault("EMBED_MODEL", "mock-bge-m3")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("SIYUAN_URL", "http://localhost:6806")
os.environ.setdefault("SIYUAN_TOKEN", "test-token")
os.environ.setdefault("MEMORY_COLLECTION", "openclaw_memory_test")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: 需要 docker compose up 才能執行"
    )
    config.addinivalue_line(
        "markers", "slow: 執行時間 > 5 秒"
    )
    config.addinivalue_line(
        "markers", "embed: 需要 Embedding Bridge (localhost:11235)"
    )
