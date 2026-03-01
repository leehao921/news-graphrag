#!/usr/bin/env python3
"""
Embedding Integration 測試腳本
==============================
驗證各個路線（A/B/C/D）的設定是否正確。

用法:
  python3 scripts/test_embedding_integration.py --path a   # 測試 Ollama 直連
  python3 scripts/test_embedding_integration.py --path c   # 測試 Bridge
  python3 scripts/test_embedding_integration.py --path d   # 測試 QMD + Qdrant
  python3 scripts/test_embedding_integration.py --all      # 全部測試
"""

import argparse
import asyncio
import json
import subprocess
import sys
import time

import httpx


# ─────────────────────────────────────────────────────────────────
# 共用工具
# ─────────────────────────────────────────────────────────────────

async def check_openai_compat(base_url: str, api_key: str, model: str, label: str) -> bool:
    """
    測試任何 OpenAI 相容的 embedding API。
    這是 OpenClaw 實際發送的請求格式。
    """
    print(f"\n🔬 測試 {label}")
    print(f"   URL: {base_url}/embeddings")
    print(f"   Model: {model}")

    test_texts = [
        "TMF 微型台指期貨 OFI 訂單流不平衡",
        "TSMC HBM capacity expansion 2026",
        "半導體供應鏈地緣政治風險分析",
    ]

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            t0 = time.perf_counter()
            resp = await client.post(
                f"{base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": model, "input": test_texts},
            )
            elapsed = time.perf_counter() - t0

            if resp.status_code != 200:
                print(f"   ❌ HTTP {resp.status_code}: {resp.text[:200]}")
                return False

            data = resp.json()
            embeddings = [entry["embedding"] for entry in data.get("data", [])]

            if len(embeddings) != len(test_texts):
                print(f"   ❌ 期望 {len(test_texts)} vectors，得到 {len(embeddings)}")
                return False

            dim = len(embeddings[0])

            # 測試 cosine similarity（中英文查詢是否語義相近）
            v1 = embeddings[0]  # 台文 TMF
            v2 = embeddings[1]  # 英文 TSMC
            v3 = embeddings[2]  # 中文半導體

            def cosine(a, b):
                dot = sum(x * y for x, y in zip(a, b))
                na = sum(x * x for x in a) ** 0.5
                nb = sum(x * x for x in b) ** 0.5
                return dot / (na * nb) if na * nb > 0 else 0

            sim_12 = cosine(v1, v2)
            sim_13 = cosine(v1, v3)
            sim_23 = cosine(v2, v3)

            print(f"   ✅ {len(embeddings)} vectors, dim={dim}, latency={elapsed:.2f}s")
            print(f"   📐 Cosine similarities:")
            print(f"      TMF ↔ TSMC:  {sim_12:.4f}  (跨語言業務相關)")
            print(f"      TMF ↔ 半導體: {sim_13:.4f}  (同語言業務相關)")
            print(f"      TSMC ↔ 半導體: {sim_23:.4f}  (跨語言同域)")

            # BGE-M3 多語言對齊判斷
            if dim == 1024:
                print(f"   ✅ BGE-M3 1024-dim（最佳：與 GraphRAG 向量空間一致）")
            elif dim == 768:
                print(f"   ✅ 768-dim（良好：但與 GraphRAG BGE-M3 向量空間不同）")
            else:
                print(f"   ⚠️  {dim}-dim（請確認是否與 GraphRAG 使用同一模型）")

            return True

    except httpx.ConnectError:
        print(f"   ❌ 連線失敗 — 服務是否已啟動？")
        return False
    except Exception as e:
        print(f"   ❌ 錯誤：{e}")
        return False


async def test_path_a():
    """Path A：Ollama 直連測試。"""
    print("\n" + "="*60)
    print("PATH A：Ollama 直連")
    print("="*60)

    # 先確認 Ollama 是否在線
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get("http://localhost:11434/api/tags")
            models = [m["name"] for m in resp.json().get("models", [])]
            print(f"   Ollama models: {models}")
            if not any("bge-m3" in m or "nomic" in m for m in models):
                print("   ⚠️  建議安裝：ollama pull bge-m3")
                print("   ⚠️  備選：ollama pull nomic-embed-text（768-dim）")
    except Exception:
        print("   ❌ Ollama 未啟動（localhost:11434）")
        print("   💡 啟動指令：ollama serve")
        return False

    return await check_openai_compat(
        base_url="http://localhost:11434/v1",
        api_key="ollama",
        model="bge-m3",
        label="Ollama BGE-M3",
    )


async def test_path_c():
    """Path C：Embedding Bridge 測試。"""
    print("\n" + "="*60)
    print("PATH C：Embedding Bridge (localhost:11235)")
    print("="*60)

    # 健康檢查
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            resp = await c.get("http://localhost:11235/health")
            info = resp.json()
            print(f"   Bridge info: model={info['model']}, dim={info.get('dim')}, cache={info.get('cache')}")
    except Exception:
        print("   ❌ Bridge 未啟動（localhost:11235）")
        print("   💡 啟動指令：docker compose up embed-bridge")
        print("      或：uvicorn src.embeddings.bridge:app --port 11235")
        return False

    ok = await check_openai_compat(
        base_url="http://localhost:11235/v1",
        api_key="local-bridge",
        model="BAAI/bge-m3",
        label="Embedding Bridge",
    )

    if ok:
        # 測試 cross-corpus 搜尋
        print("\n   📡 測試 Cross-Corpus 搜尋...")
        try:
            async with httpx.AsyncClient(timeout=15.0) as c:
                resp = await c.post(
                    "http://localhost:11235/cross-search",
                    json={
                        "query": "TMF 台指期貨 OFI 策略",
                        "min_score": 0.4,
                        "limit": 5,
                        "sources": ["news", "memory"],
                    },
                )
                results = resp.json()
                print(f"   找到 {results['total']} 筆跨庫結果")
                for r in results["results"][:3]:
                    print(f"   [{r['source']}] score={r['score']:.3f} {r.get('title', r.get('path', ''))[:50]}")
        except Exception as e:
            print(f"   ⚠️  Cross-corpus 搜尋失敗（Qdrant 可能未索引）：{e}")

    return ok


async def test_path_d():
    """Path D：QMD + Qdrant 測試。"""
    print("\n" + "="*60)
    print("PATH D：QMD + Qdrant CLI")
    print("="*60)

    import os
    script = os.path.join(os.path.dirname(__file__), "qmd_qdrant.py")

    # 測試 QMD CLI 是否可執行
    try:
        result = subprocess.run(
            [sys.executable, script, "search", "TMF OFI 策略"],
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, "QDRANT_URL": "http://localhost:6333", "EMBED_URL": "http://localhost:11235/v1"},
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if "No results found" in stdout or stdout == "[]":
            print("   ⚠️  搜尋無結果（索引可能為空）")
            print("   💡 執行索引：python3 scripts/qmd_qdrant.py update")
            return False
        elif stdout.startswith("["):
            results = json.loads(stdout)
            print(f"   ✅ QMD CLI 正常，找到 {len(results)} 筆結果")
            for r in results[:2]:
                print(f"      [{r['score']:.3f}] {r['path']} L{r['startLine']}-{r['endLine']}")
            return True
        else:
            print(f"   ❌ 非預期輸出：{stdout[:200]}")
            if stderr:
                print(f"   stderr: {stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print("   ❌ 超時（Bridge/Qdrant 是否在線？）")
        return False
    except Exception as e:
        print(f"   ❌ 執行失敗：{e}")
        return False


async def main():
    parser = argparse.ArgumentParser(description="Embedding Integration Test")
    parser.add_argument("--path", choices=["a", "b", "c", "d"], help="測試特定路線")
    parser.add_argument("--all", action="store_true", help="測試所有路線")
    args = parser.parse_args()

    results = {}

    if args.all or args.path == "a":
        results["A (Ollama)"] = await test_path_a()

    if args.all or args.path == "c":
        results["C (Bridge)"] = await test_path_c()

    if args.all or args.path == "d":
        results["D (QMD+Qdrant)"] = await test_path_d()

    if not results:
        parser.print_help()
        return

    print("\n" + "="*60)
    print("測試結果摘要")
    print("="*60)
    for name, ok in results.items():
        status = "✅" if ok else "❌"
        print(f"  {status} Path {name}")

    print("\n📋 下一步：")
    print("  1. 選擇可用的路線")
    print("  2. 複製對應設定至 ~/.openclaw/openclaw.json")
    print("     config/openclaw_memory_configs.jsonc 裡有完整範例")
    print("  3. 重啟 OpenClaw: openclaw gateway restart")
    print("  4. 測試：/memory search TMF OFI 策略")


if __name__ == "__main__":
    asyncio.run(main())
