"""
Apache DolphinScheduler — GraphRAG 完整數據管線 DAG
============================================================
DolphinScheduler 替代方案（比 n8n 更適合複雜 DAG 依賴）

架構:
  Task Group 1: 爬蟲（並行）
    ├── task_rss_taiwan       ← 台灣 RSS
    ├── task_rss_intl_semi    ← 國際半導體 RSS
    ├── task_rss_geopolitics  ← 地緣政治 RSS
    └── task_scrape_mops      ← MOPS 重大訊息（Playwright）

  Task Group 2: NLP 處理（依賴 Group1）
    └── task_nlp_pipeline     ← jieba + GLiNER2 + 情感分析

  Task Group 3: 向量化 & 圖建構（依賴 Group2）
    ├── task_embed_qdrant     ← BGE-M3 → Qdrant
    └── task_build_neo4j      ← 圖節點/邊更新

  Task Group 4: 報告生成（依賴 Group3）
    ├── task_daily_report     ← 每日 PDF 報告
    └── task_alert_check      ← 警報條件檢查 → WhatsApp

使用方法:
  pip install apache-dolphinscheduler
  python -m pydolphinscheduler yaml -f graphrag_pipeline_dag.py
"""

from __future__ import annotations

from pydolphinscheduler.core.process_definition import ProcessDefinition
from pydolphinscheduler.tasks.python import Python
from pydolphinscheduler.tasks.shell import Shell
from pydolphinscheduler.tasks.http import Http

# ─────────────────── 爬蟲任務 ───────────────────────────────────────────────

def crawl_rss_taiwan():
    """台灣 RSS 爬蟲"""
    import feedparser
    import redis
    import requests

    feeds = [
        ("cnyes_semi",  "https://news.cnyes.com/news/cat/SEMICONDUCTOR/rss"),
        ("technews",    "https://technews.tw/feed/"),
        ("ctee",        "https://ctee.com.tw/feed/"),
    ]
    r = redis.Redis()
    results = []

    for feed_id, url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                url_hash = hash(entry.link)
                if r.setnx(f"graphrag:dedup:{url_hash}", 1):
                    r.expire(f"graphrag:dedup:{url_hash}", 604800)
                    requests.post("http://localhost:8000/ingest/article", json={
                        "title": entry.title,
                        "content": entry.get("summary", ""),
                        "url": entry.link,
                        "source": feed_id,
                        "published_at": str(entry.get("published", "")),
                    }, timeout=10)
                    results.append(entry.link)
        except Exception as e:
            print(f"Error {feed_id}: {e}")

    print(f"台灣 RSS: 新增 {len(results)} 篇")
    return len(results)


def crawl_rss_international():
    """國際半導體 RSS 爬蟲"""
    import feedparser, redis, requests

    feeds = [
        ("reuters_tech", "https://feeds.reuters.com/reuters/technologyNews"),
        ("eetimes",      "https://www.eetimes.com/feed/"),
        ("trendforce",   "https://www.trendforce.com/rss/presscenter.xml"),
        ("chip_wars",    "https://amritaroy.substack.com/feed"),
        ("digitimes_en", "https://www.digitimes.com/rss/daily.xml"),
    ]
    r = redis.Redis()
    new_count = 0

    for feed_id, url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
                url_hash = hash(entry.link)
                if r.setnx(f"graphrag:dedup:{url_hash}", 1):
                    r.expire(f"graphrag:dedup:{url_hash}", 604800)
                    requests.post("http://localhost:8000/ingest/article", json={
                        "title": entry.title,
                        "content": entry.get("summary", ""),
                        "url": entry.link,
                        "source": feed_id,
                        "language": "en",
                    }, timeout=10)
                    new_count += 1
        except Exception as e:
            print(f"Error {feed_id}: {e}")

    print(f"國際半導體 RSS: 新增 {new_count} 篇")
    return new_count


def crawl_rss_geopolitics():
    """地緣政治 RSS + 關鍵字過濾"""
    import feedparser, redis, requests

    feeds = [
        ("isw",       "https://understandingwar.org/rss.xml"),
        ("aei",       "https://www.aei.org/feed/"),
        ("diplomat",  "https://thediplomat.com/feed/"),
        ("axios",     "https://api.axios.com/feed/technology"),
    ]
    keywords = ["Taiwan", "semiconductor", "chip", "export control",
                "TSMC", "supply chain", "tariff", "Strait"]
    r = redis.Redis()
    new_count = 0

    for feed_id, url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:20]:
                text = (entry.title + " " + entry.get("summary", "")).lower()
                if not any(kw.lower() in text for kw in keywords):
                    continue
                url_hash = hash(entry.link)
                if r.setnx(f"graphrag:dedup:{url_hash}", 1):
                    r.expire(f"graphrag:dedup:{url_hash}", 604800)
                    requests.post("http://localhost:8000/ingest/article", json={
                        "title": entry.title,
                        "content": entry.get("summary", ""),
                        "url": entry.link,
                        "source": feed_id,
                        "language": "en",
                    }, timeout=10)
                    new_count += 1
        except Exception as e:
            print(f"Error {feed_id}: {e}")

    print(f"地緣政治 RSS: 新增 {new_count} 篇（已過濾）")
    return new_count


def generate_daily_report():
    """每日報告生成"""
    import requests
    from datetime import datetime
    import pytz

    tz = pytz.timezone("Asia/Taipei")
    date = datetime.now(tz).strftime("%Y-%m-%d")

    resp = requests.post("http://localhost:8000/report/generate", json={
        "report_type": "daily_digest",
        "date": date,
        "format": "pdf",
        "include_sections": [
            "executive_summary",
            "semiconductor_supply_chain",
            "earnings_highlights",
            "geopolitical_events",
            "tmf_trading_implications",
        ]
    }, timeout=120)
    resp.raise_for_status()
    result = resp.json()
    print(f"報告生成完成: {result.get('minio_path')}")
    print(f"摘要: {result.get('executive_summary','')[:100]}...")
    return result


# ─────────────────── DolphinScheduler DAG 定義 ───────────────────────────────

with ProcessDefinition(
    name="GraphRAG 新聞管線",
    tenant="graphrag",
    schedule="0 */2 * * *",   # 每2小時執行（可在 UI 調整）
    timezone="Asia/Taipei",
    description="GraphRAG 完整新聞入庫 + 報告生成管線",
) as dag:

    # ── Group 1: 並行爬蟲 ────────────────────────────────────────────────────
    task_rss_tw = Python(
        name="爬蟲_台灣RSS",
        code=crawl_rss_taiwan,
        resource_limit={"cpu_quota": 1, "max_memory": "512M"},
    )

    task_rss_intl = Python(
        name="爬蟲_國際半導體RSS",
        code=crawl_rss_international,
        resource_limit={"cpu_quota": 1, "max_memory": "512M"},
    )

    task_rss_geo = Python(
        name="爬蟲_地緣政治RSS",
        code=crawl_rss_geopolitics,
        resource_limit={"cpu_quota": 1, "max_memory": "256M"},
    )

    task_mops = Http(
        name="爬蟲_MOPS重大訊息",
        url="http://localhost:8000/scrape/mops",
        http_method="POST",
        body='{"tickers": ["2330","2454","2317","2308","2382"],"lookback_hours": 2}',
        headers={"Content-Type": "application/json"},
    )

    # ── 等待所有爬蟲完成 ─────────────────────────────────────────────────────
    task_rss_tw >> task_rss_intl >> task_rss_geo >> task_mops

    # ── Group 4: 每日報告生成（只在早上7:30執行時觸發）────────────────────
    task_report = Python(
        name="生成每日報告",
        code=generate_daily_report,
        resource_limit={"cpu_quota": 2, "max_memory": "1G"},
    )

    # 依賴: 所有爬蟲完成後才生成報告
    task_mops >> task_report
