.PHONY: help test test-unit test-integration coverage lint fmt check install up down clean

PYTHON := python3
PYTEST := pytest
SRC := src
TESTS := tests

help:  ## 顯示所有指令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ─── 測試 ────────────────────────────────────────────────────────

test: test-unit  ## 執行所有 unit tests

test-unit:  ## Unit tests（不需要外部服務）
	$(PYTEST) $(TESTS)/unit/ -v -m "not integration" \
		--cov=$(SRC) --cov-report=term-missing

test-integration:  ## Integration tests（需要 docker compose up）
	$(PYTEST) $(TESTS)/integration/ -v -m "integration" \
		--cov=$(SRC) --cov-report=term-missing

test-embed:  ## Embedding Bridge 測試
	$(PYTEST) $(TESTS)/unit/test_embedding_bridge.py -v

test-api:  ## FastAPI 端點測試
	$(PYTEST) $(TESTS)/unit/test_api.py -v

test-scraper:  ## Scraper 測試
	$(PYTEST) $(TESTS)/unit/test_scrapers.py -v

coverage:  ## 產生 HTML 覆蓋率報告
	$(PYTEST) $(TESTS)/unit/ \
		--cov=$(SRC) \
		--cov-report=html:htmlcov \
		--cov-report=term-missing
	@echo "Coverage report: htmlcov/index.html"

# ─── 程式碼品質 ───────────────────────────────────────────────────

lint:  ## Ruff lint 檢查
	ruff check $(SRC)/ $(TESTS)/ scripts/

fmt:  ## Ruff 自動格式化
	ruff format $(SRC)/ $(TESTS)/ scripts/
	ruff check --fix $(SRC)/ $(TESTS)/ scripts/

check: lint  ## lint + mypy type check
	mypy $(SRC)/ --ignore-missing-imports || true

# ─── 安裝 ────────────────────────────────────────────────────────

install:  ## 安裝開發依賴
	pip install -e ".[dev]"

install-lite:  ## 安裝最小依賴（測試用）
	pip install pytest pytest-asyncio pytest-cov pytest-mock \
		fastapi httpx pydantic redis ruff mypy

# ─── Docker ───────────────────────────────────────────────────────

up:  ## 啟動所有服務
	docker compose up -d

up-core:  ## 只啟動核心服務（Qdrant + Neo4j + Postgres + Redis）
	docker compose up -d qdrant neo4j postgres redis

up-embed:  ## 啟動 Embedding Bridge
	docker compose up -d embed-bridge

down:  ## 停止所有服務
	docker compose down

logs:  ## 查看所有服務 logs
	docker compose logs -f --tail=50

# ─── 工具 ────────────────────────────────────────────────────────

test-embed-integration:  ## 測試 embedding 整合（所有路線）
	$(PYTHON) scripts/test_embedding_integration.py --all

index-memory:  ## 更新 QMD Qdrant 記憶索引
	$(PYTHON) scripts/qmd_qdrant.py update

test-rss:  ## 測試所有 RSS feed 連線
	$(PYTHON) scripts/test_rss_feeds.py

siyuan-init:  ## 初始化 SiYuan 知識庫
	curl -s -X POST http://localhost:8000/knowledge/siyuan/init | python3 -m json.tool

clean:  ## 清理暫存檔
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache htmlcov .coverage coverage.xml
