"""
RSS Feed 連通性測試
驗證所有 Layer 1 RSS 端點是否可用

用法:
  pip install feedparser httpx pyyaml
  python scripts/test_rss_feeds.py
  python scripts/test_rss_feeds.py --quick   # 只測前10個
"""

import sys
import asyncio
import time
import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

try:
    import httpx
    import feedparser
except ImportError:
    print("pip install feedparser httpx pyyaml")
    sys.exit(1)

# RSS 端點
RSS_FEEDS = {
    # ── 台灣即時 ──
    "cnyes_semi":     "https://news.cnyes.com/news/cat/SEMICONDUCTOR/rss",
    "cnyes_tw":       "https://news.cnyes.com/news/cat/TWSTOCK/rss",
    "technews":       "https://technews.tw/feed/",
    "technews_ai":    "https://technews.tw/category/ai/feed/",
    "ctee":           "https://ctee.com.tw/feed/",
    "moneydj":        "https://www.moneydj.com/rss/news.xml",
    "digitimes_tw":   "https://www.digitimes.com.tw/rss/news.xml",

    # ── 國際半導體 ──
    "eetimes":        "https://www.eetimes.com/feed/",
    "tomshardware":   "https://www.tomshardware.com/feeds/all",
    "digitimes_en":   "https://www.digitimes.com/rss/daily.xml",
    "trendforce":     "https://www.trendforce.com/rss/presscenter.xml",
    "semi_org":       "https://www.semi.org/en/rss/blog-newsletter-rss-feeds.xml",
    "semianalysis":   "https://www.semianalysis.com/feed",
    "chip_wars":      "https://amritaroy.substack.com/feed",
    "fab_knowledge":  "https://www.fabricatedknowledge.com/feed",
    "semi_digest":    "https://www.semiconductor-digest.com/feed/",

    # ── 國際財經 ──
    "reuters_tech":   "https://feeds.reuters.com/reuters/technologyNews",
    "reuters_mkt":    "https://feeds.reuters.com/reuters/businessNews",
    "axios_tech":     "https://api.axios.com/feed/technology",
    "ft_tech":        "https://www.ft.com/technology?format=rss",

    # ── 地緣政治 ──
    "isw":            "https://understandingwar.org/rss.xml",
    "aei":            "https://www.aei.org/feed/",
    "csis":           "https://www.csis.org/rss.xml",
    "diplomat":       "https://thediplomat.com/feed/",
    "cfr":            "https://www.cfr.org/rss/tech.xml",
    "chip_wars_sub":  "https://amritaroy.substack.com/feed",
}

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


@dataclass
class FeedResult:
    name: str
    url: str
    ok: bool
    entry_count: int = 0
    latest_title: str = ""
    latest_date: str = ""
    error: str = ""
    latency_ms: float = 0.0


def test_feed(name: str, url: str, timeout: int = 10) -> FeedResult:
    t0 = time.time()
    try:
        # 使用 feedparser (支援各種 RSS/Atom 格式)
        feed = feedparser.parse(url, request_headers={
            'User-Agent': 'GraphRAG-NewsBot/1.0 (test)',
            'Accept': 'application/rss+xml, application/atom+xml, */*',
        })

        latency = (time.time() - t0) * 1000

        if feed.bozo and not feed.entries:
            return FeedResult(name=name, url=url, ok=False,
                            error=str(feed.bozo_exception)[:80],
                            latency_ms=latency)

        entries = feed.entries
        if not entries:
            return FeedResult(name=name, url=url, ok=True,
                            entry_count=0,
                            error="⚠️ 0 篇文章（空 feed）",
                            latency_ms=latency)

        latest = entries[0]
        title = getattr(latest, 'title', '(no title)')[:60]
        published = getattr(latest, 'published', getattr(latest, 'updated', ''))[:16]

        return FeedResult(
            name=name, url=url, ok=True,
            entry_count=len(entries),
            latest_title=title,
            latest_date=published,
            latency_ms=latency
        )

    except Exception as e:
        return FeedResult(name=name, url=url, ok=False,
                        error=str(e)[:80],
                        latency_ms=(time.time() - t0) * 1000)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--quick', action='store_true', help='只測試前10個')
    parser.add_argument('--filter', type=str, help='只測試包含此關鍵字的 feed')
    args = parser.parse_args()

    feeds = dict(RSS_FEEDS)
    if args.filter:
        feeds = {k: v for k, v in feeds.items() if args.filter.lower() in k.lower()}
    if args.quick:
        feeds = dict(list(feeds.items())[:10])

    print(f"\n{BOLD}RSS Feed 連通性測試{RESET}")
    print(f"測試 {len(feeds)} 個 RSS 端點...\n")
    print(f"{'名稱':<20} {'狀態':<8} {'文章數':<6} {'延遲':<8} {'最新文章標題'}")
    print("─" * 90)

    results = []
    ok_count = 0
    fail_count = 0

    for name, url in feeds.items():
        result = test_feed(name, url)
        results.append(result)

        if result.ok and result.entry_count > 0:
            ok_count += 1
            status = f"{GREEN}✓ OK{RESET}"
            print(f"{name:<20} {status:<17} {result.entry_count:<6} "
                  f"{result.latency_ms:.0f}ms{'':<4} {result.latest_title}")
        elif result.ok:
            status = f"{YELLOW}⚠ EMPTY{RESET}"
            print(f"{name:<20} {status:<17} {result.entry_count:<6} "
                  f"{result.latency_ms:.0f}ms{'':<4} {result.error}")
        else:
            fail_count += 1
            status = f"{RED}✗ FAIL{RESET}"
            print(f"{name:<20} {status:<17} {'—':<6} "
                  f"{result.latency_ms:.0f}ms{'':<4} {RED}{result.error}{RESET}")

    print("─" * 90)
    print(f"\n結果: {GREEN}{ok_count} 成功{RESET}  {RED}{fail_count} 失敗{RESET}  "
          f"(共 {len(feeds)} 個)\n")

    # 失敗清單
    failed = [r for r in results if not r.ok or r.entry_count == 0]
    if failed:
        print(f"{YELLOW}需要確認的 Feed:{RESET}")
        for r in failed:
            print(f"  {r.name}: {r.url}")
            print(f"    原因: {r.error}")
        print()

    # 按延遲排序
    valid = [r for r in results if r.ok and r.entry_count > 0]
    valid.sort(key=lambda r: r.latency_ms)
    if valid:
        print(f"{BOLD}最快的 5 個 Feed:{RESET}")
        for r in valid[:5]:
            print(f"  {r.name:<20} {r.latency_ms:.0f}ms  ({r.entry_count} articles)")
        print()


if __name__ == '__main__':
    main()
