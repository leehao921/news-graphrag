"""
報告生成器
Jinja2 HTML 模板 → WeasyPrint PDF

報告類型:
  daily_digest     ← 每日產業日報（n8n 07:30 觸發）
  earnings_brief   ← 財報快報（事件觸發）
  weekly_sector    ← 週度半導體總覽（週日）
  geopolitical     ← 地緣政治特別報告（事件觸發）
"""
from __future__ import annotations

import base64
import io
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(os.environ.get("TEMPLATE_DIR", "/app/templates"))


class ReportGenerator:
    def __init__(self):
        try:
            from jinja2 import Environment, FileSystemLoader
            self.jinja = Environment(
                loader=FileSystemLoader(str(TEMPLATE_DIR)),
                autoescape=True,
            )
        except ImportError:
            log.warning("Jinja2 未安裝，使用純文字模式")
            self.jinja = None

    async def generate(
        self,
        report_type: str,
        date: str,
        articles: list,
        hot_entities: list,
        sections: list[str],
        output_format: str = "pdf",
    ) -> dict:
        """生成報告，返回 HTML + PDF Base64 + 摘要"""

        # 1. 從 Qdrant + Neo4j 聚合數據
        data = await self._aggregate_data(date, articles, hot_entities, sections)

        # 2. 生成 executive summary（LLM）
        summary = await self._generate_summary(data)
        data["executive_summary"] = summary

        # 3. 渲染 HTML
        html = self._render_html(report_type, data)
        data["html"] = html

        # 4. 轉換 PDF（WeasyPrint）
        if output_format == "pdf":
            pdf_bytes = self._html_to_pdf(html)
            data["pdf_b64"] = base64.b64encode(pdf_bytes).decode()

        return data

    async def _aggregate_data(self, date: str, articles: list,
                              hot_entities: list, sections: list[str]) -> dict:
        """從多個來源聚合報告數據"""
        data = {
            "report_date": date,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "article_count": len(articles),
            "articles_by_domain": self._group_by_domain(articles),
            "hot_entities": hot_entities[:10],
            "sections": sections,
        }

        # 各版塊數據
        if "semiconductor_supply_chain" in sections:
            data["supply_chain"] = self._extract_supply_chain_news(articles)

        if "earnings_highlights" in sections:
            data["earnings"] = self._extract_earnings_news(articles)

        if "geopolitical_events" in sections:
            data["geopolitics"] = self._extract_geopolitical_news(articles)

        if "tmf_trading_implications" in sections:
            data["tmf_signals"] = self._derive_tmf_signals(data)

        return data

    def _group_by_domain(self, articles: list) -> dict:
        groups = {}
        for a in articles:
            for domain in (a.get("domains") or ["general"]):
                groups.setdefault(domain, []).append(a)
        return groups

    def _extract_supply_chain_news(self, articles: list) -> list:
        keywords = ["TSMC", "台積電", "CoWoS", "HBM", "封裝", "晶圓", "DRAM"]
        return [a for a in articles
                if any(kw in (a.get("title", "") + a.get("content", ""))
                       for kw in keywords)][:8]

    def _extract_earnings_news(self, articles: list) -> list:
        keywords = ["財報", "法說會", "EPS", "營收", "earnings", "revenue", "profit"]
        return [a for a in articles
                if any(kw in (a.get("title", "") + a.get("content", ""))
                       for kw in keywords)][:6]

    def _extract_geopolitical_news(self, articles: list) -> list:
        keywords = ["台海", "制裁", "出口管制", "關稅", "Taiwan Strait", "export control", "tariff"]
        return [a for a in articles
                if any(kw in (a.get("title", "") + a.get("content", ""))
                       for kw in keywords)][:5]

    def _derive_tmf_signals(self, data: dict) -> dict:
        """從新聞數據推導 TMF 交易影響"""
        supply_count = len(data.get("supply_chain", []))
        geo_count = len(data.get("geopolitics", []))
        earnings_count = len(data.get("earnings", []))

        # 簡化版信號評估
        bullish_factors = []
        bearish_factors = []

        if supply_count > 3:
            bullish_factors.append(f"供應鏈正面消息密集（{supply_count}則）")
        if geo_count > 2:
            bearish_factors.append(f"地緣政治風險升溫（{geo_count}則）")

        net_sentiment = len(bullish_factors) - len(bearish_factors)
        direction = "BULLISH" if net_sentiment > 0 else "BEARISH" if net_sentiment < 0 else "NEUTRAL"

        return {
            "direction": direction,
            "bullish_factors": bullish_factors,
            "bearish_factors": bearish_factors,
            "suggested_bias": "偏多" if direction == "BULLISH" else "偏空" if direction == "BEARISH" else "中性觀望",
            "confidence": min(abs(net_sentiment) * 25, 75),
        }

    async def _generate_summary(self, data: dict) -> str:
        """LLM 生成執行摘要（Ollama）"""
        try:
            import httpx
            prompt = self._build_summary_prompt(data)
            resp = httpx.post(
                f"{os.environ.get('OLLAMA_URL', 'http://ollama:11434')}/api/generate",
                json={"model": "qwen2.5:7b", "prompt": prompt, "stream": False},
                timeout=60.0
            )
            resp.raise_for_status()
            return resp.json().get("response", "（摘要生成失敗）")
        except Exception as e:
            log.warning(f"LLM 摘要失敗，使用靜態摘要: {e}")
            return self._static_summary(data)

    def _build_summary_prompt(self, data: dict) -> str:
        return f"""你是半導體產業分析師。請根據以下 {data['article_count']} 篇新聞，
生成一份不超過 300 字的繁體中文執行摘要，重點包含：
1. 最重要的半導體/供應鏈動態（1-2句）
2. 財報/法說會亮點（如有）
3. 地緣政治風險評估（1句）
4. 對台股/TMF期貨的短期影響（1句）

今日熱門實體: {', '.join([e.get('name','') for e in data.get('hot_entities',[])[:5]])}

新聞標題摘錄:
{chr(10).join(['- ' + a.get('title','') for a in (data.get('supply_chain',[]) + data.get('earnings',[]))[:10]])}

請直接輸出摘要，不要加標題或說明。"""

    def _static_summary(self, data: dict) -> str:
        articles = data.get("article_count", 0)
        sc = len(data.get("supply_chain", []))
        geo = len(data.get("geopolitics", []))
        tmf = data.get("tmf_signals", {})
        return (
            f"今日共收錄 {articles} 篇產業新聞。"
            f"供應鏈相關 {sc} 則，地緣政治 {geo} 則。"
            f"TMF交易方向：{tmf.get('suggested_bias', '中性觀望')}，"
            f"信心度 {tmf.get('confidence', 0)}%。"
        )

    def _render_html(self, report_type: str, data: dict) -> str:
        """Jinja2 渲染 HTML"""
        if self.jinja:
            try:
                template = self.jinja.get_template(f"{report_type}.html.j2")
                return template.render(**data)
            except Exception as e:
                log.warning(f"模板渲染失敗，使用預設: {e}")
        return self._default_html(data)

    def _default_html(self, data: dict) -> str:
        """極簡 HTML 後備模板"""
        articles_html = "\n".join([
            f'<li><a href="{a.get("url","#")}">{a.get("title","")}</a></li>'
            for a in (data.get("supply_chain", []) + data.get("earnings", []))[:15]
        ])
        return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <title>半導體產業日報 {data.get('report_date','')}</title>
  <style>
    body {{ font-family: "Noto Sans TC", sans-serif; margin: 2cm; line-height: 1.6; color: #333; }}
    h1 {{ color: #1a237e; border-bottom: 3px solid #1a237e; }}
    h2 {{ color: #283593; margin-top: 1.5em; }}
    .summary {{ background: #e8eaf6; padding: 1em; border-radius: 8px; margin: 1em 0; }}
    .signal {{ background: #e8f5e9; padding: 1em; border-radius: 8px; margin: 1em 0; }}
    .signal.bearish {{ background: #ffebee; }}
    .meta {{ color: #666; font-size: 0.9em; }}
    ul {{ padding-left: 1.5em; }}
    li {{ margin: 0.3em 0; }}
  </style>
</head>
<body>
  <h1>📊 半導體 + 台股 產業日報</h1>
  <p class="meta">報告日期：{data.get('report_date','')} ｜ 生成時間：{data.get('generated_at','')} ｜ 收錄新聞：{data.get('article_count',0)} 則</p>

  <h2>🔍 執行摘要</h2>
  <div class="summary"><p>{data.get('executive_summary','')}</p></div>

  <h2>🌊 TMF 期貨影響評估</h2>
  <div class="signal {'bearish' if data.get('tmf_signals',{}).get('direction')=='BEARISH' else ''}">
    <strong>方向：{data.get('tmf_signals',{}).get('suggested_bias','中性觀望')}</strong>
    ｜ 信心度：{data.get('tmf_signals',{}).get('confidence',0)}%
    <ul>
      {''.join([f'<li>✅ {f}</li>' for f in data.get('tmf_signals',{}).get('bullish_factors',[])])}
      {''.join([f'<li>❌ {f}</li>' for f in data.get('tmf_signals',{}).get('bearish_factors',[])])}
    </ul>
  </div>

  <h2>🔬 半導體供應鏈新聞</h2>
  <ul>{articles_html}</ul>

  <h2>🏢 今日熱門實體</h2>
  <ul>{''.join([f'<li>{e.get("name","")}{" (" + e.get("ticker","") + ")" if e.get("ticker") else ""} — {e.get("mentions",0)} 則</li>' for e in data.get("hot_entities",[])])}</ul>

  <hr>
  <p class="meta">由 GraphRAG News System 自動生成 ｜ 資料來源：{len(data.get('articles_by_domain',{}))} 個領域</p>
</body>
</html>"""

    def _html_to_pdf(self, html: str) -> bytes:
        """WeasyPrint 將 HTML 轉為 PDF"""
        try:
            from weasyprint import HTML as WHTML
            pdf_buf = io.BytesIO()
            WHTML(string=html).write_pdf(pdf_buf)
            return pdf_buf.getvalue()
        except ImportError:
            log.warning("WeasyPrint 未安裝，返回空 PDF")
            return b"%PDF-1.4 placeholder"
        except Exception as e:
            log.error(f"PDF 生成失敗: {e}")
            return b""
