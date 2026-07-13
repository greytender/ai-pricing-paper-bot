# AI Pricing Paper Bot

数据驱动的 AI 产品定价博弈论文自动爬取系统。通过 Semantic Scholar API 多关键词检索论文，自动去重后导入 Zotero 文献管理库。

## 架构

```
├── main.py            # 主入口，编排完整爬取流程
├── config.py          # 全局配置（环境变量、关键词、参数）
├── s2_fetcher.py      # Semantic Scholar API 检索模块
├── zotero_client.py   # Zotero API 导入模块
├── cache.py           # 本地 JSON 缓存，支持增量更新
├── requirements.txt   # Python 依赖
├── .env.example       # 环境变量模板
├── .github/workflows/auto_run.yml  # GitHub Actions 定时任务
└── data/              # 运行时数据（缓存、日志）
```

## 工作流程

1. **多关键词检索** — 10 组关键词覆盖 AI 定价博弈的研究维度
2. **推荐扩展** — 对高引 Top 5 论文获取 Semantic Scholar 推荐论文
3. **三级去重** — DOI > S2 PaperId > 标题，全量去重
4. **增量缓存** — 本地 JSON 缓存已处理论文，避免重复入库
5. **Zotero 导入** — 自动查找/创建 Collection，DOI 去重后逐篇写入

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入以下信息：

| 变量 | 必填 | 说明 |
|------|------|------|
| `SEMANTIC_SCHOLAR_KEY` | 否 | [申请地址](https://www.semanticscholar.org/product/api#api-key-form)，有 Key 提升速率限制 |
| `ZOTERO_API_KEY` | 是 | [申请地址](https://www.zotero.org/settings/keys/new) |
| `ZOTERO_USER_ID` | 是 | 在 Zotero API Key 页面查看 |
| `ZOTERO_COLLECTION_NAME` | 否 | 默认 `AI Pricing - Game Theory`，不存在会自动创建 |

### 3. 运行

```bash
python main.py
```

## GitHub Actions 自动运行

项目已配置每日自动运行的 GitHub Actions workflow：

1. 在 GitHub 仓库的 **Settings > Secrets and variables > Actions** 中添加：
   - `ZOTERO_API_KEY`
   - `ZOTERO_USER_ID`
   - `ZOTERO_COLLECTION_NAME`（可选）
   - `SEMANTIC_SCHOLAR_KEY`（可选）

2. Workflow 每天北京时间 0:00 自动执行，也可在 Actions 页面手动触发。

## 自定义关键词

编辑 `config.py` 中的 `SEARCH_QUERIES` 列表即可自定义搜索关键词：

```python
SEARCH_QUERIES: list[str] = [
    "your custom keyword 1",
    "your custom keyword 2",
]
```

## License

MIT
