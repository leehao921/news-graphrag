"""
QMD Qdrant CLI Unit Tests
測試 chunk_markdown、hits_to_qmd_format、QMD 輸出格式相容性。
不需要實際的 Qdrant 或 Embedding Bridge。
"""

import json
import sys
from pathlib import Path

import pytest

# 直接 import qmd_qdrant.py（scripts 目錄）
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from qmd_qdrant import chunk_markdown, hits_to_qmd_format


# ─── Markdown Chunking ────────────────────────────────────────────

class TestChunkMarkdown:
    def test_empty_document(self):
        result = chunk_markdown("", "/path/MEMORY.md")
        assert result == []

    def test_single_chunk_small_doc(self):
        text = "# Daily Report\n\nTMF 今日信號：看多\nOFI > 150\n"
        chunks = chunk_markdown(text, "/path/MEMORY.md")
        assert len(chunks) == 1
        assert chunks[0]["path"] == "/path/MEMORY.md"
        assert chunks[0]["start_line"] == 1
        assert "TMF" in chunks[0]["text"]

    def test_heading_boundary_split(self):
        """## 標題應作為分割邊界。"""
        text = "\n".join([
            "# Report",
            "intro content " * 10,
            "",
            "## Section A",
            "section a content " * 30,  # 夠長，觸發分割
            "",
            "## Section B",
            "section b content " * 30,
        ])
        chunks = chunk_markdown(text, "/path/test.md")
        # 至少 2 個 chunks（Section A 和 B 分開）
        assert len(chunks) >= 2

    def test_chunk_preserves_line_numbers(self):
        """每個 chunk 的 start/end line 必須正確。"""
        lines = ["line " + str(i) for i in range(1, 11)]
        text = "\n".join(lines)
        chunks = chunk_markdown(text, "/test.md")
        # 所有 chunk 的 start_line >= 1
        for chunk in chunks:
            assert chunk["start_line"] >= 1
            assert chunk["end_line"] >= chunk["start_line"]

    def test_chunk_id_is_unique(self):
        """每個 chunk 必須有唯一的 id（hash）。"""
        text = "\n".join(["content " * 50] * 10)  # 長文件
        chunks = chunk_markdown(text, "/path/MEMORY.md")
        ids = [c["id"] for c in chunks]
        assert len(ids) == len(set(ids)), "Chunk IDs 不唯一"

    def test_chinese_content(self):
        """中文內容的 chunking 正確性。"""
        text = "# 台積電分析\n\n" + "TSMC 2026 Q1 收入預估 358 億美元，" * 20
        chunks = chunk_markdown(text, "/path/semi.md")
        assert len(chunks) >= 1
        assert "TSMC" in chunks[0]["text"] or "台積電" in chunks[0]["text"]

    def test_different_paths_different_ids(self):
        """相同內容不同路徑，chunk ID 應不同。"""
        text = "# Same Content\n\nSame text here."
        chunks_a = chunk_markdown(text, "/path/a.md")
        chunks_b = chunk_markdown(text, "/path/b.md")
        assert chunks_a[0]["id"] != chunks_b[0]["id"]


# ─── QMD 輸出格式相容性 ────────────────────────────────────────────

class TestHitsToQmdFormat:
    """驗證 Qdrant hits → OpenClaw QMD JSON 格式轉換。"""

    def test_basic_conversion(self):
        """基本轉換：Qdrant hit → QMD snippet。"""
        hits = [
            {
                "score": 0.82,
                "payload": {
                    "path": "/workspace/MEMORY.md",
                    "start_line": 10,
                    "end_line": 25,
                    "text": "## TMF 信號\nOFI > 150，看多訊號",
                },
            }
        ]
        results = hits_to_qmd_format(hits)
        assert len(results) == 1
        r = results[0]
        # OpenClaw parseQmdQueryResultArray 期望的欄位
        assert r["path"] == "/workspace/MEMORY.md"
        assert r["startLine"] == 10
        assert r["endLine"] == 25
        assert r["score"] == pytest.approx(0.82, abs=0.001)
        assert "TMF" in r["snippet"]

    def test_snippet_truncation(self):
        """超長 snippet 應截斷至 700 字元（maxSnippetChars）。"""
        long_text = "A" * 1000
        hits = [{"score": 0.7, "payload": {
            "path": "/test.md", "start_line": 1, "end_line": 5, "text": long_text
        }}]
        results = hits_to_qmd_format(hits)
        assert len(results[0]["snippet"]) <= 700

    def test_empty_hits(self):
        """空結果列表應回傳空列表。"""
        assert hits_to_qmd_format([]) == []

    def test_output_is_json_serializable(self):
        """輸出必須可序列化為 JSON（OpenClaw 讀 stdout）。"""
        hits = [
            {
                "score": 0.65,
                "payload": {
                    "path": "/memory/2026-03-01.md",
                    "start_line": 5,
                    "end_line": 20,
                    "text": "TMF 微型台指，今日開盤做空",
                },
            }
        ]
        results = hits_to_qmd_format(hits)
        # 必須可以 JSON 序列化
        serialized = json.dumps(results, ensure_ascii=False)
        # 必須可以反序列化
        parsed = json.loads(serialized)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    def test_multiple_hits_ordering(self):
        """多筆結果的順序應維持（由 Qdrant 已排序）。"""
        hits = [
            {"score": 0.9, "payload": {"path": "/a.md", "start_line": 1, "end_line": 5, "text": "first"}},
            {"score": 0.7, "payload": {"path": "/b.md", "start_line": 1, "end_line": 5, "text": "second"}},
            {"score": 0.5, "payload": {"path": "/c.md", "start_line": 1, "end_line": 5, "text": "third"}},
        ]
        results = hits_to_qmd_format(hits)
        assert results[0]["score"] == pytest.approx(0.9, abs=0.001)
        assert results[1]["score"] == pytest.approx(0.7, abs=0.001)
        assert results[2]["score"] == pytest.approx(0.5, abs=0.001)


# ─── QMD CLI 整合相容性模擬 ──────────────────────────────────────────

class TestQmdOutputCompatibility:
    """
    模擬 OpenClaw 的 parseQmdQueryResultArray 邏輯：
    確認我們的輸出格式符合 OpenClaw 的解析期望。
    """

    def _parse_qmd_output(self, stdout: str) -> list | None:
        """模擬 OpenClaw 的 parseQmdQueryResultArray。"""
        stripped = stdout.strip()
        if not stripped:
            return None
        if "No results found" in stripped:
            return []
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
        # 嘗試從噪音中提取 JSON array
        start = stripped.find("[")
        if start >= 0:
            try:
                return json.loads(stripped[start:])
            except Exception:
                pass
        return None

    def test_valid_results_parsed(self):
        hits = [
            {"score": 0.75, "payload": {
                "path": "/workspace/MEMORY.md", "start_line": 1, "end_line": 10,
                "text": "TMF 策略分析"
            }}
        ]
        stdout = json.dumps(hits_to_qmd_format(hits), ensure_ascii=False)
        result = self._parse_qmd_output(stdout)
        assert result is not None
        assert len(result) == 1
        assert result[0]["path"] == "/workspace/MEMORY.md"

    def test_no_results_marker(self):
        """無結果時回傳空列表（OpenClaw 識別 'No results found'）。"""
        result = self._parse_qmd_output("No results found.")
        assert result == []

    def test_empty_stdout_returns_none(self):
        result = self._parse_qmd_output("")
        assert result is None
