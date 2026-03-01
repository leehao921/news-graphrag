"""
SiYuan Client Unit Tests
測試 REST API 格式、文件路徑生成、筆記本管理邏輯。
"""

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.knowledge.siyuan_client import (
    GraphRAGKnowledgeBase,
    SiYuanClient,
    SiYuanConfig,
)


# ─── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def config():
    return SiYuanConfig(base_url="http://localhost:6806", token="test-token")


@pytest.fixture
def mock_client(config):
    client = SiYuanClient(config)
    return client


@pytest.fixture
def mock_kb(mock_client):
    kb = GraphRAGKnowledgeBase(mock_client)
    kb._notebook_ids = {
        "daily_reports": "nb-daily-001",
        "semiconductor": "nb-semi-002",
        "tmf_signals": "nb-tmf-003",
        "geopolitical": "nb-geo-004",
        "fintel_graph": "nb-graph-005",
    }
    return kb


# ─── SiYuanClient 測試 ────────────────────────────────────────────

class TestSiYuanClient:
    def test_headers_format(self, config):
        """Auth header 格式必須是 'Token {token}'。"""
        client = SiYuanClient(config)
        assert client.headers["Authorization"] == "Token test-token"
        assert client.headers["Content-Type"] == "application/json"

    @pytest.mark.asyncio
    async def test_health_check_success(self, mock_client):
        with patch.object(mock_client, "_post", AsyncMock(return_value={"ver": "3.1.0"})):
            result = await mock_client.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, mock_client):
        with patch.object(mock_client, "_post", AsyncMock(side_effect=Exception("timeout"))):
            result = await mock_client.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_get_or_create_notebook_existing(self, mock_client):
        """筆記本已存在時不應重複建立。"""
        from src.knowledge.siyuan_client import NotebookInfo
        mock_nb = NotebookInfo(id="existing-id", name="📰 Daily Reports")
        with patch.object(mock_client, "list_notebooks", AsyncMock(return_value=[mock_nb])):
            with patch.object(mock_client, "create_notebook", AsyncMock()) as mock_create:
                nb_id = await mock_client.get_or_create_notebook("📰 Daily Reports")
        assert nb_id == "existing-id"
        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_or_create_notebook_new(self, mock_client):
        """筆記本不存在時應建立新的。"""
        with patch.object(mock_client, "list_notebooks", AsyncMock(return_value=[])):
            with patch.object(mock_client, "create_notebook", AsyncMock(return_value="new-id")):
                nb_id = await mock_client.get_or_create_notebook("📰 Daily Reports")
        assert nb_id == "new-id"


# ─── GraphRAGKnowledgeBase 測試 ─────────────────────────────────

class TestGraphRAGKnowledgeBase:
    def test_notebook_structure(self):
        """確認所有必要筆記本都定義了。"""
        expected = {"daily_reports", "semiconductor", "tmf_signals", "geopolitical", "fintel_graph"}
        assert set(GraphRAGKnowledgeBase.NOTEBOOKS.keys()) == expected

    @pytest.mark.asyncio
    async def test_push_daily_report_doc_path(self, mock_kb):
        """日報文件路徑格式：/{YYYY-MM}/{YYYY-MM-DD}_daily_digest。"""
        test_date = date(2026, 3, 1)
        with patch.object(mock_kb.client, "create_doc_from_markdown", AsyncMock(return_value="doc-id-001")):
            with patch.object(mock_kb.client, "upload_asset", AsyncMock(return_value="")):
                doc_id = await mock_kb.push_daily_report(
                    report_date=test_date,
                    markdown_content="## Test\nContent",
                    tmf_signal="bullish",
                )
        assert doc_id == "doc-id-001"

        # 驗證 create_doc_from_markdown 的 path 參數
        call_args = mock_kb.client.create_doc_from_markdown.call_args
        path_arg = call_args[0][1]  # 第 2 個位置參數
        assert "2026-03" in path_arg
        assert "2026-03-01" in path_arg
        assert "daily_digest" in path_arg

    @pytest.mark.asyncio
    async def test_tmf_signal_icon_mapping(self, mock_kb):
        """TMF 信號圖示映射正確。"""
        kb = mock_kb
        # 測試 Markdown 生成中的圖示
        md = kb._build_report_md(
            date(2026, 3, 1), "content", "bullish", ["TSMC", "CXMT"], None
        )
        assert "🟢" in md  # bullish = green

        md = kb._build_report_md(
            date(2026, 3, 1), "content", "bearish", [], None
        )
        assert "🔴" in md  # bearish = red

        md = kb._build_report_md(
            date(2026, 3, 1), "content", "neutral", [], None
        )
        assert "🟡" in md  # neutral = yellow

    @pytest.mark.asyncio
    async def test_push_semiconductor_note(self, mock_kb):
        """半導體筆記推送到正確筆記本。"""
        with patch.object(mock_kb.client, "create_doc_from_markdown", AsyncMock(return_value="doc-semi-001")):
            doc_id = await mock_kb.push_semiconductor_note(
                title="TrendForce DRAM 漲價分析",
                content="Q1 2026 DRAM +90%",
                category="Markets",
                ticker="2303",
            )
        assert doc_id == "doc-semi-001"
        # 確認使用 semiconductor 筆記本
        call_args = mock_kb.client.create_doc_from_markdown.call_args
        assert call_args[0][0] == "nb-semi-002"

    @pytest.mark.asyncio
    async def test_push_geopolitical_event_with_impact(self, mock_kb):
        """地緣政治事件包含影響等級圖示。"""
        with patch.object(mock_kb.client, "create_doc_from_markdown", AsyncMock(return_value="doc-geo-001")):
            await mock_kb.push_geopolitical_event(
                title="美伊戰爭衝擊台股",
                content="台指期夜盤跌 525 點",
                region="Taiwan",
                impact_level="critical",
                taiex_impact="預估跌 500-900 點",
            )
        call_args = mock_kb.client.create_doc_from_markdown.call_args
        markdown = call_args[0][2]  # 第 3 個位置參數（markdown content）
        assert "🔴" in markdown  # critical = red
        assert "critical" in markdown.upper() or "CRITICAL" in markdown
        assert "預估跌 500-900 點" in markdown


# ─── 邊界條件測試 ────────────────────────────────────────────────

class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_daily_report_with_pdf(self, mock_kb, tmp_path):
        """PDF 附件應觸發 upload_asset 呼叫。"""
        pdf_file = tmp_path / "report.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake content")  # fake PDF

        with patch.object(mock_kb.client, "create_doc_from_markdown", AsyncMock(return_value="doc-001")):
            with patch.object(mock_kb.client, "upload_asset", AsyncMock(return_value="assets://report.pdf")) as mock_upload:
                with patch.object(mock_kb.client, "insert_block", AsyncMock(return_value="block-001")):
                    await mock_kb.push_daily_report(
                        report_date=date(2026, 3, 1),
                        markdown_content="content",
                        pdf_path=pdf_file,
                    )
        mock_upload.assert_called_once()

    @pytest.mark.asyncio
    async def test_entity_tags_truncated(self, mock_kb):
        """實體標籤最多顯示 10 個。"""
        entities = [f"entity_{i}" for i in range(20)]  # 20 個實體
        md = mock_kb._build_report_md(
            date(2026, 3, 1), "content", "neutral", entities, None
        )
        # 數 ## 標記的個數（entity 格式是 ##name##）
        tag_count = md.count("##") // 2
        assert tag_count <= 10
