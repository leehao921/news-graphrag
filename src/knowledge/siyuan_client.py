"""
SiYuan 思源筆記 REST API Client
================================
整合 SiYuan 知識庫 — 自動建立報告文件、研究筆記、信號記錄。

API 文件: http://localhost:6806/api/  (啟動後可查)
Auth: Authorization: Token {SIYUAN_TOKEN}

筆記本架構:
  📰 Daily Reports / 每日日報
  🔬 Semiconductor Analysis / 半導體分析
  💹 TMF Trading Signals / 交易信號
  🌏 Geopolitical Monitor / 地緣政治
  📊 FinTel-Graph / 財務圖分析
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Any
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Taipei")

# ─────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────

class SiYuanConfig(BaseModel):
    base_url: str = "http://localhost:6806"
    token: str = "graphrag2026"
    timeout: float = 30.0


class NotebookInfo(BaseModel):
    id: str
    name: str
    icon: str = ""
    sort: int = 0
    closed: bool = False


class DocCreated(BaseModel):
    id: str
    doc_path: str


# ─────────────────────────────────────────────────────────────────
# SiYuan REST Client
# ─────────────────────────────────────────────────────────────────

class SiYuanClient:
    """Async HTTP client 封裝 SiYuan REST API。"""

    def __init__(self, config: SiYuanConfig | None = None):
        self.config = config or SiYuanConfig()
        self._client: httpx.AsyncClient | None = None

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Token {self.config.token}",
            "Content-Type": "application/json",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                headers=self.headers,
                timeout=self.config.timeout,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _post(self, endpoint: str, payload: dict) -> dict:
        client = await self._get_client()
        try:
            resp = await client.post(f"/api/{endpoint}", json=payload)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code", 0) != 0:
                raise RuntimeError(f"SiYuan API error [{endpoint}]: {data.get('msg')}")
            return data.get("data", {})
        except httpx.HTTPStatusError as e:
            logger.error(f"SiYuan HTTP error {e.response.status_code}: {endpoint}")
            raise

    # ──────────────────────────────────────
    # System
    # ──────────────────────────────────────

    async def get_version(self) -> str:
        """檢查連線與版本。"""
        data = await self._post("system/version", {})
        return data.get("ver", "unknown")

    async def health_check(self) -> bool:
        """快速健康檢查。"""
        try:
            ver = await self.get_version()
            logger.info(f"SiYuan connected, version: {ver}")
            return True
        except Exception as e:
            logger.warning(f"SiYuan health check failed: {e}")
            return False

    # ──────────────────────────────────────
    # Notebook 管理
    # ──────────────────────────────────────

    async def list_notebooks(self) -> list[NotebookInfo]:
        data = await self._post("notebook/lsNotebooks", {})
        notebooks = data.get("notebooks", [])
        return [NotebookInfo(**nb) for nb in notebooks]

    async def create_notebook(self, name: str) -> str:
        """建立筆記本，回傳 notebook_id。"""
        data = await self._post("notebook/createNotebook", {"name": name})
        notebook_id = data.get("notebook", {}).get("id", "")
        logger.info(f"Created notebook: {name} ({notebook_id})")
        return notebook_id

    async def get_or_create_notebook(self, name: str) -> str:
        """取得或建立筆記本，回傳 notebook_id。"""
        notebooks = await self.list_notebooks()
        for nb in notebooks:
            if nb.name == name:
                return nb.id
        return await self.create_notebook(name)

    # ──────────────────────────────────────
    # Document 管理
    # ──────────────────────────────────────

    async def create_doc_from_markdown(
        self,
        notebook_id: str,
        path: str,
        markdown: str,
    ) -> str:
        """
        用 Markdown 建立文件，回傳 doc_id。

        path 格式: "/Daily Reports/2026-03-01_report"
                   (不含副檔名，SiYuan 自動加)
        """
        data = await self._post(
            "filetree/createDocWithMd",
            {
                "notebook": notebook_id,
                "path": path,
                "markdown": markdown,
            },
        )
        doc_id = data if isinstance(data, str) else data.get("id", "")
        logger.info(f"Created doc: {path} ({doc_id})")
        return doc_id

    async def update_doc_markdown(self, doc_id: str, markdown: str) -> bool:
        """更新現有文件內容（先清空再重建）。"""
        # SiYuan 透過 insertBlock + clearBlock 更新
        # 簡化: 刪除舊 children，插入新 block
        await self._post(
            "block/updateBlock",
            {
                "id": doc_id,
                "data": markdown,
                "dataType": "markdown",
            },
        )
        return True

    async def list_docs(self, notebook_id: str, path: str = "/") -> list[dict]:
        """列出目錄下的文件。"""
        data = await self._post(
            "filetree/listDocsByPath",
            {"notebook": notebook_id, "path": path, "sort": 4},  # sort=4: 按時間倒序
        )
        return data.get("files", [])

    # ──────────────────────────────────────
    # Block 操作
    # ──────────────────────────────────────

    async def insert_block(
        self,
        parent_id: str,
        markdown: str,
        previous_id: str = "",
    ) -> str:
        """在 parent block 內插入新 block，回傳 block_id。"""
        data = await self._post(
            "block/insertBlock",
            {
                "dataType": "markdown",
                "data": markdown,
                "nextID": "",
                "previousID": previous_id,
                "parentID": parent_id,
            },
        )
        blocks = data if isinstance(data, list) else []
        return blocks[0].get("doOperations", [{}])[0].get("id", "") if blocks else ""

    # ──────────────────────────────────────
    # SQL Query（搜尋）
    # ──────────────────────────────────────

    async def sql_query(self, stmt: str) -> list[dict]:
        """執行 SQL 查詢 SiYuan 的塊資料庫。"""
        data = await self._post("query/sql", {"stmt": stmt})
        return data if isinstance(data, list) else []

    async def search_docs(self, keyword: str, limit: int = 20) -> list[dict]:
        """全文搜尋文件。"""
        return await self.sql_query(
            f"SELECT id, content, hpath FROM blocks "
            f"WHERE type='d' AND content LIKE '%{keyword}%' "
            f"LIMIT {limit}"
        )

    # ──────────────────────────────────────
    # Asset 上傳
    # ──────────────────────────────────────

    async def upload_asset(self, file_path: Path, doc_id: str = "") -> str:
        """上傳檔案（PDF、圖片等）到 SiYuan assets，回傳 asset URL。"""
        client = await self._get_client()
        with open(file_path, "rb") as f:
            files = {"file[]": (file_path.name, f, "application/octet-stream")}
            resp = await client.post(
                "/api/asset/upload",
                files=files,
                headers={"Authorization": f"Token {self.config.token}"},
            )
        data = resp.json()
        successes = data.get("data", {}).get("succMap", {})
        return successes.get(file_path.name, "")


# ─────────────────────────────────────────────────────────────────
# Knowledge Base Manager（高層業務邏輯）
# ─────────────────────────────────────────────────────────────────

class GraphRAGKnowledgeBase:
    """
    整合 GraphRAG → SiYuan 的知識庫管理器。

    筆記本架構:
      📰 Daily Reports       — 每日新聞日報
      🔬 Semiconductor       — 半導體產業分析
      💹 TMF Signals         — 交易信號記錄
      🌏 Geopolitical        — 地緣政治監控
      📊 FinTel Graph        — 財務圖分析
    """

    NOTEBOOKS = {
        "daily_reports":   "📰 Daily Reports",
        "semiconductor":   "🔬 Semiconductor Analysis",
        "tmf_signals":     "💹 TMF Trading Signals",
        "geopolitical":    "🌏 Geopolitical Monitor",
        "fintel_graph":    "📊 FinTel-Graph",
    }

    def __init__(self, client: SiYuanClient):
        self.client = client
        self._notebook_ids: dict[str, str] = {}

    async def initialize(self):
        """首次初始化：建立所有筆記本。"""
        logger.info("Initializing GraphRAG Knowledge Base in SiYuan...")
        for key, name in self.NOTEBOOKS.items():
            nb_id = await self.client.get_or_create_notebook(name)
            self._notebook_ids[key] = nb_id
            logger.info(f"  ✅ {name}: {nb_id}")
        return self._notebook_ids

    async def _get_nb_id(self, key: str) -> str:
        if key not in self._notebook_ids:
            await self.initialize()
        return self._notebook_ids[key]

    # ──────────────────────────────────────
    # 每日日報 → SiYuan
    # ──────────────────────────────────────

    async def push_daily_report(
        self,
        report_date: date,
        markdown_content: str,
        pdf_path: Path | None = None,
        tmf_signal: str = "neutral",
        key_entities: list[str] | None = None,
    ) -> str:
        """將每日日報推送至 SiYuan 📰 Daily Reports 筆記本。"""
        nb_id = await self._get_nb_id("daily_reports")
        date_str = report_date.strftime("%Y-%m-%d")
        month_str = report_date.strftime("%Y-%m")
        doc_path = f"/{month_str}/{date_str}_daily_digest"

        # 建立完整 markdown
        full_md = self._build_report_md(
            report_date, markdown_content, tmf_signal, key_entities or [], pdf_path
        )

        doc_id = await self.client.create_doc_from_markdown(nb_id, doc_path, full_md)

        # 上傳 PDF 附件
        if pdf_path and pdf_path.exists():
            asset_url = await self.client.upload_asset(pdf_path, doc_id)
            if asset_url:
                await self.client.insert_block(
                    doc_id,
                    f"[📄 下載 PDF 報告]({asset_url})",
                )

        logger.info(f"Daily report {date_str} pushed to SiYuan: {doc_id}")
        return doc_id

    def _build_report_md(
        self,
        report_date: date,
        content: str,
        tmf_signal: str,
        entities: list[str],
        pdf_path: Path | None,
    ) -> str:
        signal_icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(
            tmf_signal, "⚪"
        )
        entity_tags = " ".join(f"##{e}##" for e in entities[:10])
        date_str = report_date.strftime("%Y年%m月%d日")

        return f"""# {date_str} 市場日報

{{{{.custom-attr}}}}
date: {report_date.isoformat()}
signal: {tmf_signal}
tags: daily-report, semiconductor, taiwan-stocks

## TMF 信號 {signal_icon}

> **今日方向**: {tmf_signal.upper()}

{content}

---

## 關鍵實體

{entity_tags}

---

*自動產生 by News-GraphRAG | {datetime.now(TZ).strftime("%Y-%m-%d %H:%M")} (Asia/Taipei)*
"""

    # ──────────────────────────────────────
    # 半導體分析 → SiYuan
    # ──────────────────────────────────────

    async def push_semiconductor_note(
        self,
        title: str,
        content: str,
        category: str = "General",  # Companies | Technologies | Markets | Policies
        ticker: str | None = None,
    ) -> str:
        """推送半導體分析筆記。"""
        nb_id = await self._get_nb_id("semiconductor")
        today = datetime.now(TZ).date()
        slug = title.replace(" ", "_").replace("/", "-")[:40]
        doc_path = f"/{category}/{today.isoformat()}_{slug}"

        ticker_tag = f"**股票代碼**: {ticker}  \n" if ticker else ""
        md = f"""# {title}

{ticker_tag}
分類: {category}
更新: {datetime.now(TZ).strftime("%Y-%m-%d %H:%M")}

{content}

---
*GraphRAG 自動摘要*
"""
        return await self.client.create_doc_from_markdown(nb_id, doc_path, md)

    # ──────────────────────────────────────
    # TMF 信號記錄 → SiYuan
    # ──────────────────────────────────────

    async def log_tmf_signal(
        self,
        signal_type: str,
        price: float,
        ofi_value: float,
        iv_percentile: float,
        bb_lower: float,
        bb_upper: float,
        reasoning: str,
        action: str = "WATCH",  # WATCH | BUY | SELL | EXIT
    ) -> str:
        """記錄 TMF 交易信號到 SiYuan 💹 TMF Signals。"""
        nb_id = await self._get_nb_id("tmf_signals")
        now = datetime.now(TZ)
        date_str = now.date().isoformat()
        time_str = now.strftime("%H:%M:%S")

        action_icon = {
            "BUY": "🟢", "SELL": "🔴", "WATCH": "🟡", "EXIT": "⚫"
        }.get(action, "⚪")

        # 月份分組
        doc_path = f"/{now.strftime('%Y-%m')}/signal_log"
        signal_block = f"""
## {time_str} {action_icon} {action} — {signal_type}

| 指標 | 數值 |
|------|------|
| 價格 | {price:,.0f} |
| OFI | {ofi_value:+.1f} |
| IV 百分位 | {iv_percentile:.1f}% |
| BB 下緣 | {bb_lower:,.0f} |
| BB 上緣 | {bb_upper:,.0f} |

**理由**: {reasoning}
"""
        # 嘗試找既有的日誌文件，若無則建立
        try:
            docs = await self.client.list_docs(nb_id, f"/{now.strftime('%Y-%m')}")
            existing = [d for d in docs if "signal_log" in d.get("name", "")]
            if existing:
                doc_id = existing[0].get("id", "")
                await self.client.insert_block(doc_id, signal_block)
                return doc_id
        except Exception:
            pass

        md = f"# {date_str[:7]} TMF 信號日誌\n\n" + signal_block
        return await self.client.create_doc_from_markdown(nb_id, doc_path, md)

    # ──────────────────────────────────────
    # 地緣政治 → SiYuan
    # ──────────────────────────────────────

    async def push_geopolitical_event(
        self,
        title: str,
        content: str,
        region: str = "Taiwan",  # Taiwan | US-China | Middle East | Global
        impact_level: str = "medium",  # low | medium | high | critical
        taiex_impact: str | None = None,
    ) -> str:
        """推送地緣政治事件分析。"""
        nb_id = await self._get_nb_id("geopolitical")
        now = datetime.now(TZ)
        slug = title.replace(" ", "_")[:40]
        doc_path = f"/{region}/{now.date().isoformat()}_{slug}"

        impact_icon = {
            "low": "🔵", "medium": "🟡", "high": "🟠", "critical": "🔴"
        }.get(impact_level, "⚪")

        taiex_section = f"\n**台股影響**: {taiex_impact}\n" if taiex_impact else ""

        md = f"""# {impact_icon} {title}

**地區**: {region}  
**影響等級**: {impact_level.upper()}  
**時間**: {now.strftime("%Y-%m-%d %H:%M")} (Asia/Taipei)
{taiex_section}

{content}

---
*GraphRAG 地緣政治監控*
"""
        return await self.client.create_doc_from_markdown(nb_id, doc_path, md)

    # ──────────────────────────────────────
    # GraphRAG 搜尋結果 → SiYuan 研究筆記
    # ──────────────────────────────────────

    async def save_search_research(
        self,
        query: str,
        results: list[dict],
        graph_context: list[dict] | None = None,
    ) -> str:
        """將 GraphRAG 搜尋結果儲存為 SiYuan 研究筆記。"""
        nb_id = await self._get_nb_id("fintel_graph")
        now = datetime.now(TZ)
        slug = query.replace(" ", "_")[:30]
        doc_path = f"/Research/{now.strftime('%Y-%m')}/{now.strftime('%Y%m%d_%H%M')}_{slug}"

        # 結果 Markdown 表格
        result_rows = "\n".join(
            f"| {i+1} | {r.get('title', '')[:40]} | {r.get('score', 0):.3f} | "
            f"{r.get('source', '')} |"
            for i, r in enumerate(results[:10])
        )

        graph_section = ""
        if graph_context:
            nodes = [g.get("entity", "") for g in graph_context[:5]]
            graph_section = f"\n## 知識圖譜上下文\n相關實體: {', '.join(nodes)}\n"

        md = f"""# 研究查詢: {query}

**時間**: {now.strftime("%Y-%m-%d %H:%M")}  
**返回結果數**: {len(results)}

## 搜尋結果

| # | 標題 | 相關度 | 來源 |
|---|------|--------|------|
{result_rows}
{graph_section}

---
*GraphRAG Vector Transfer 增強搜尋*
"""
        return await self.client.create_doc_from_markdown(nb_id, doc_path, md)


# ─────────────────────────────────────────────────────────────────
# CLI 初始化工具
# ─────────────────────────────────────────────────────────────────

async def init_knowledge_base(base_url: str = "http://localhost:6806", token: str = "graphrag2026"):
    """CLI 工具: 初始化 SiYuan 知識庫結構。"""
    config = SiYuanConfig(base_url=base_url, token=token)
    client = SiYuanClient(config)

    print("🔌 Connecting to SiYuan...")
    if not await client.health_check():
        print("❌ Cannot connect to SiYuan. Check docker-compose and token.")
        return

    kb = GraphRAGKnowledgeBase(client)
    ids = await kb.initialize()

    print("\n✅ Knowledge Base initialized:")
    for key, nb_id in ids.items():
        name = GraphRAGKnowledgeBase.NOTEBOOKS[key]
        print(f"   {name}: {nb_id}")

    print("\n📋 Add to .env:")
    for key, nb_id in ids.items():
        env_key = f"SIYUAN_NB_{key.upper()}"
        print(f"   {env_key}={nb_id}")

    await client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SiYuan Knowledge Base CLI")
    parser.add_argument("--init", action="store_true", help="初始化筆記本結構")
    parser.add_argument("--url", default="http://localhost:6806", help="SiYuan URL")
    parser.add_argument("--token", default="graphrag2026", help="Access Token")
    args = parser.parse_args()

    if args.init:
        asyncio.run(init_knowledge_base(args.url, args.token))
    else:
        parser.print_help()
