# Contributing Guide — News GraphRAG

## Git Flow

```
main          ← 生產就緒，protected（CI 必須綠）
  └── develop ← 整合分支，所有 feature 的目標
        ├── feat/rss-crawler-cnyes
        ├── feat/neo4j-graph-builder
        ├── fix/embedding-cache-ttl
        └── chore/update-dependencies
```

### 分支命名規則

| 前綴 | 用途 | 範例 |
|------|------|------|
| `feat/` | 新功能 | `feat/mops-playwright-scraper` |
| `fix/` | Bug 修復 | `fix/siyuan-auth-header` |
| `chore/` | 維護、依賴更新 | `chore/bump-qdrant-client` |
| `docs/` | 文件 | `docs/setup-guide` |
| `test/` | 測試補充 | `test/embedding-bridge-integration` |
| `refactor/` | 重構（不改功能） | `refactor/nlp-pipeline-async` |

### 標準工作流程

```bash
# 1. 從 develop 開新分支
git checkout develop && git pull origin develop
git checkout -b feat/your-feature

# 2. 開發 + 提交（使用 Conventional Commits）
git add .
git commit -m "feat(scraper): 新增 MOPS 月營收 Playwright 爬蟲"

# 3. 推送並開 PR
git push origin feat/your-feature
gh pr create --base develop --title "feat: MOPS scraper" --body "..."

# 4. CI 綠後，squash merge 到 develop
# 5. develop → main：PR + tag release
```

## Commit Message 格式（Conventional Commits）

```
<type>(<scope>): <簡短描述>

[可選正文]

[可選 footer]
```

**Types：** `feat` `fix` `chore` `docs` `test` `refactor` `perf` `ci`

**Scopes：** `api` `scraper` `nlp` `embed` `graph` `report` `n8n` `siyuan` `docker`

**範例：**
```
feat(embed): 新增 Embedding Bridge OpenAI 相容端點

- POST /v1/embeddings 支援 BGE-M3
- Redis 快取 TTL 24h
- cross-search 跨庫搜尋端點

Closes #12
```

## 測試規範

```bash
# 執行所有測試
make test

# 執行特定模組
make test-embed
make test-api
make test-scraper

# 產生覆蓋率報告
make coverage
```

**規則：**
- PR 合併前 coverage ≥ 80%
- 新功能必須附測試
- Integration tests 標記 `@pytest.mark.integration`（本地執行，CI 跳過）

## Code Review 標準

- [ ] 有對應的 unit test
- [ ] 通過 CI（ruff lint + mypy + pytest）
- [ ] 環境變數未硬編碼
- [ ] 敏感資料不進 commit（.env 在 .gitignore）
- [ ] Pydantic 模型有 type hints
- [ ] 非同步函數有 await / async def
