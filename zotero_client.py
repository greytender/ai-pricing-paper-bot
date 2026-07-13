"""
Zotero API 交互模块
负责：
  - 获取/创建 Collection（支持父子层级）
  - 将论文条目导入 Zotero（含 PDF URL 关联）
  - 按研究领域自动分类到子 Collection
  - 查询已存在条目以避免重复导入
"""

import re
import time
import logging
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)

# ── 研究领域分类规则 ─────────────────────────────────────────────
# 按论文的 fieldsOfStudy、venue、title 中的关键词自动归类
CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("Reinforcement Learning", [
        "reinforcement learning", "multi-agent", "q-learning", "rl-based",
        "deep rl", "policy gradient", "dynamic pricing rl",
    ]),
    ("Algorithmic Pricing", [
        "algorithmic pricing", "algorithmic collusion", "pricing algorithm",
        "automated pricing", "algorithmic price",
    ]),
    ("Game Theory", [
        "game theory", "nash equilibrium", "stackelberg", "bertrand",
        "oligopoly", "mechanism design", "auction", "strategic interaction",
    ]),
    ("Data-Driven Pricing", [
        "data-driven", "machine learning pricing", "demand forecasting",
        "price prediction", "computational pricing",
    ]),
    ("AI & LLM Economics", [
        "llm pricing", "large language model", "ai pricing", "ai product",
        "foundation model pricing", "mlops pricing", "ai service pricing",
    ]),
]

# 默认分类（无法匹配任何规则时使用）
DEFAULT_CATEGORY: str = "Other Pricing Research"


def _build_headers() -> dict[str, str]:
    """构建 Zotero API 请求头。"""
    if not config.ZOTERO_API_KEY:
        raise ValueError("ZOTERO_API_KEY 未配置，请在 .env 中设置。")
    return {
        "Zotero-API-Key": config.ZOTERO_API_KEY,
        "Zotero-API-Version": "3",
        "Content-Type": "application/json",
    }


def _make_request(
    method: str,
    url: str,
    headers: dict[str, str],
    json_data: Any = None,
    timeout: int = 15,
) -> requests.Response:
    """
    封装 Zotero API HTTP 请求，统一错误处理。
    Zotero 写操作返回 multi-status JSON: {"successful": {}, "unchanged": {}, "failed": {}}
    """
    try:
        resp = requests.request(method, url, headers=headers, json=json_data, timeout=timeout)
        resp.raise_for_status()
        return resp
    except requests.exceptions.HTTPError as e:
        logger.error("HTTP 错误 (%s): %s", e.response.status_code, e.response.text[:500])
        raise
    except requests.exceptions.ConnectionError:
        logger.error("连接 Zotero API 失败，请检查网络。")
        raise
    except requests.exceptions.Timeout:
        logger.error("Zotero API 请求超时。")
        raise


def get_all_collections() -> list[dict[str, Any]]:
    """
    获取用户 Zotero 库中所有 Collection。

    Returns:
        Collection 字典列表，每个包含 key 和 data.name
    """
    if not config.ZOTERO_USER_ID:
        raise ValueError("ZOTERO_USER_ID 未配置，请在 .env 中设置。")

    headers = _build_headers()
    url = f"{config.ZOTERO_BASE_URL}/users/{config.ZOTERO_USER_ID}/collections"

    resp = _make_request("GET", url, headers)
    collections: list[dict[str, Any]] = resp.json()
    logger.info("获取到 %d 个 Zotero Collection。", len(collections))
    return collections


def find_or_create_collection(
    collection_name: str,
    parent_key: str | None = None,
) -> str:
    """
    查找指定名称的 Collection，如果不存在则自动创建。
    支持创建子 Collection（指定 parent_key）。

    Args:
        collection_name: Collection 名称
        parent_key: 父 Collection 的 key（None 表示顶级）

    Returns:
        Collection 的 key
    """
    # 先查找：如果指定了父级，在父级的子 Collection 中查找
    collections = get_all_collections()
    for col in collections:
        data: dict[str, Any] = col.get("data", {})
        if data.get("name") == collection_name:
            col_parent: str | None = data.get("parentCollection")
            if parent_key is None and col_parent is None:
                logger.info("找到已有 Collection: %s (key=%s)", collection_name, col["key"])
                return col["key"]
            if parent_key and col_parent == parent_key:
                logger.info("找到已有子 Collection: %s (key=%s)", collection_name, col["key"])
                return col["key"]

    # 未找到，创建新的
    logger.info("Collection '%s' 不存在，正在创建...", collection_name)
    headers = _build_headers()
    url = f"{config.ZOTERO_BASE_URL}/users/{config.ZOTERO_USER_ID}/collections"

    payload: dict[str, str | None] = {"name": collection_name}
    if parent_key:
        payload["parentCollection"] = parent_key

    try:
        resp = _make_request("POST", url, headers, json_data=[payload])
        result: dict[str, Any] = resp.json()
    except Exception as e:
        raise RuntimeError(f"创建 Collection 请求失败: {e}")

    if not result.get("successful"):
        failed_info: dict[str, Any] = result.get("failed", {})
        unchanged_info: dict[str, Any] = result.get("unchanged", {})
        raise RuntimeError(
            f"创建 Collection 失败，响应: successful={result.get('successful')}, "
            f"failed={failed_info}, unchanged={unchanged_info}"
        )

    # 从 successful 中安全提取 key
    success_values: list[dict[str, Any]] = list(result["successful"].values())
    if not success_values:
        raise RuntimeError(f"创建 Collection 返回的 successful 列表为空: {result}")
    new_key: str = success_values[0].get("key", "")
    if not new_key:
        raise RuntimeError(f"创建 Collection 返回的 key 为空: {success_values[0]}")

    logger.info("成功创建 Collection: %s (key=%s)", collection_name, new_key)
    return new_key


def get_existing_dois_in_collection(collection_key: str) -> set[str]:
    """
    获取指定 Collection 中已有的所有 DOI，用于避免重复导入。

    Args:
        collection_key: Collection 的 key

    Returns:
        已有 DOI 的集合（小写）
    """
    headers = _build_headers()
    url = (
        f"{config.ZOTERO_BASE_URL}/users/{config.ZOTERO_USER_ID}"
        f"/collections/{collection_key}/items"
    )
    params: dict[str, str | int] = {"limit": 100, "start": 0}
    existing_dois: set[str] = set()

    while True:
        try:
            resp = _make_request("GET", url, headers)
            items: list[dict[str, Any]] = resp.json()

            for item in items:
                doi: str | None = (item.get("data") or {}).get("DOI")
                if doi:
                    existing_dois.add(doi.lower())

            # 判断是否有下一页
            link_header: str | None = resp.headers.get("Link", "")
            if 'rel="next"' not in link_header:
                break

            start: int = params["start"] + params["limit"]
            params["start"] = start
            time.sleep(config.REQUEST_DELAY_SECONDS)

        except Exception as e:
            logger.error("获取已有 DOI 失败: %s", e)
            break

    logger.info("Collection 中已有 %d 个 DOI。", len(existing_dois))
    return existing_dois


def classify_paper(paper: dict[str, Any]) -> str:
    """
    根据论文的标题、摘要、venue、fieldsOfStudy 自动分类到研究领域。

    Args:
        paper: Semantic Scholar 论文字典

    Returns:
        分类名称
    """
    # 拼接所有文本信息用于匹配
    title: str = (paper.get("title") or "").lower()
    abstract: str = (paper.get("abstract") or "").lower()
    venue: str = (paper.get("venue") or "").lower()
    fields: list[str] = paper.get("fieldsOfStudy") or []

    # 组合搜索文本
    search_text: str = f"{title} {abstract} {venue}"
    for f in fields:
        search_text += f" {f.lower()}"

    # 按规则顺序匹配（第一个匹配的即分类结果）
    for category_name, keywords in CATEGORY_RULES:
        for keyword in keywords:
            if keyword.lower() in search_text:
                return category_name

    return DEFAULT_CATEGORY


def _parse_authors(authors: list[dict[str, Any]]) -> list[dict[str, str]]:
    """
    将 Semantic Scholar 的作者格式转换为 Zotero 的 creators 格式。
    """
    creators: list[dict[str, str]] = []
    for author in authors:
        name: str = author.get("name", "").strip()
        if not name:
            continue

        parts: list[str] = name.split()
        if len(parts) >= 2:
            creators.append({
                "creatorType": "author",
                "firstName": parts[0],
                "lastName": " ".join(parts[1:]),
            })
        elif len(parts) == 1:
            creators.append({
                "creatorType": "author",
                "name": parts[0],
            })
    return creators


def paper_to_zotero_item(
    paper: dict[str, Any],
    collection_key: str,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """
    将 Semantic Scholar 论文数据转换为 Zotero item 格式。
    自动关联 Open Access PDF URL。

    Args:
        paper: Semantic Scholar 论文字典
        collection_key: 目标 Collection 的 key
        tags: 额外的标签列表

    Returns:
        Zotero item 字典
    """
    external_ids: dict[str, str] = paper.get("externalIds") or {}
    journal_info: dict[str, Any] = paper.get("journal") or {}
    publication_date: str = paper.get("publicationDate", "")

    date_str: str = publication_date if publication_date else str(paper.get("year", ""))

    # 处理标签
    item_tags: list[dict[str, str]] = [{"tag": "AI-Auto-Fetch"}]
    if tags:
        item_tags.extend([{"tag": t} for t in tags])

    # 将 fieldsOfStudy 也作为标签
    for field in (paper.get("fieldsOfStudy") or []):
        item_tags.append({"tag": field})

    # 自动分类标签
    category: str = classify_paper(paper)
    item_tags.append({"tag": category})

    item: dict[str, Any] = {
        "itemType": "journalArticle",
        "title": paper.get("title", "Untitled"),
        "creators": _parse_authors(paper.get("authors", [])),
        "abstractNote": paper.get("abstract", ""),
        "date": date_str,
        "DOI": external_ids.get("DOI", ""),
        "url": paper.get("url", ""),
        "collections": [collection_key],
        "tags": item_tags,
        "relations": {},
    }

    # 填充期刊信息
    if journal_info.get("name"):
        item["publicationTitle"] = journal_info["name"]
    if journal_info.get("volume"):
        item["volume"] = journal_info["volume"]
    if journal_info.get("pages"):
        item["pages"] = journal_info["pages"]

    if not item.get("publicationTitle") and paper.get("venue"):
        item["publicationTitle"] = paper["venue"]

    # Open Access PDF 链接 — 作为 url 字段，Zotero 可通过此链接下载
    oa_pdf: dict[str, str] = paper.get("openAccessPdf") or {}
    if oa_pdf.get("url"):
        item["url"] = oa_pdf["url"]

    return item


def upload_paper_to_zotero(
    paper: dict[str, Any],
    collection_key: str,
) -> bool:
    """
    将单篇论文上传到 Zotero 指定 Collection。

    Args:
        paper: Semantic Scholar 论文字典
        collection_key: 目标 Collection 的 key

    Returns:
        是否上传成功
    """
    headers = _build_headers()
    url = f"{config.ZOTERO_BASE_URL}/users/{config.ZOTERO_USER_ID}/items"

    item = paper_to_zotero_item(paper, collection_key)
    category: str = classify_paper(paper)
    title: str = paper.get("title", "Untitled")[:60]

    try:
        resp = _make_request("POST", url, headers, json_data=[item])
        result: dict[str, Any] = resp.json()

        if "successful" in result and result["successful"]:
            logger.info("✅ [%s] 成功入库: %s", category, title)
            return True
        elif "unchanged" in result and result["unchanged"]:
            logger.info("⏭️ [%s] 已存在，跳过: %s", category, title)
            return True
        else:
            failed: dict[str, Any] = result.get("failed", {})
            logger.error("❌ [%s] 入库失败 '%s': %s", category, title, failed)
            return False

    except Exception as e:
        logger.error("❌ [%s] 入库异常 '%s': %s", category, title, e)
        return False


def batch_upload_to_zotero(
    papers: list[dict[str, Any]],
    collection_name: str | None = None,
) -> dict[str, int]:
    """
    批量上传论文到 Zotero，支持自动分类到子 Collection。

    流程：
    1. 确定父 Collection（ZOTERO_COLLECTION_KEY 或按名称查找/创建）
    2. 获取父 Collection 已有 DOI（全局去重）
    3. 对每篇论文自动分类，查找/创建对应子 Collection
    4. 逐篇上传到对应子 Collection

    Args:
        papers: 论文列表
        collection_name: 父 Collection 名称（默认使用配置值）

    Returns:
        统计信息 {"success": 成功数, "skipped": 跳过数, "failed": 失败数}
    """
    if not config.ZOTERO_USER_ID or not config.ZOTERO_API_KEY:
        logger.error("Zotero 配置缺失，跳过上传。请设置 ZOTERO_API_KEY 和 ZOTERO_USER_ID。")
        return {"success": 0, "skipped": len(papers), "failed": 0}

    stats: dict[str, int] = {"success": 0, "skipped": 0, "failed": 0}

    # 1. 获取父 Collection key
    parent_key: str | None = config.ZOTERO_COLLECTION_KEY
    if not parent_key:
        collection_name = collection_name or config.ZOTERO_COLLECTION_NAME
        try:
            parent_key = find_or_create_collection(collection_name)
        except Exception as e:
            logger.error("获取/创建父 Collection 失败: %s", e)
            return {"success": 0, "skipped": 0, "failed": len(papers)}
    else:
        logger.info("使用指定的父 Collection key: %s", parent_key)

    # 2. 获取已有 DOI（在父 Collection 全局去重）
    existing_dois = get_existing_dois_in_collection(parent_key)

    # 3. 预建子 Collection 缓存（避免重复查询）
    sub_collection_cache: dict[str, str] = {}

    # 4. 逐篇上传
    for paper in papers:
        doi: str = (paper.get("externalIds") or {}).get("DOI", "")
        if doi and doi.lower() in existing_dois:
            logger.info("⏭️ DOI 已存在，跳过: %s", paper.get("title", "")[:60])
            stats["skipped"] += 1
            continue

        # 自动分类
        category = classify_paper(paper)

        # 查找或创建子 Collection
        if category not in sub_collection_cache:
            try:
                sub_key = find_or_create_collection(category, parent_key=parent_key)
                sub_collection_cache[category] = sub_key
            except Exception as e:
                logger.error("创建子 Collection '%s' 失败: %s，使用父 Collection", category, e)
                sub_collection_cache[category] = parent_key

        sub_key = sub_collection_cache[category]

        # 上传到子 Collection
        success = upload_paper_to_zotero(paper, sub_key)
        if success:
            stats["success"] += 1
            if doi:
                existing_dois.add(doi.lower())
        else:
            stats["failed"] += 1

        time.sleep(config.REQUEST_DELAY_SECONDS)

    # 统计分类结果
    category_counts: dict[str, int] = {}
    for paper in papers:
        cat = classify_paper(paper)
        category_counts[cat] = category_counts.get(cat, 0) + 1

    logger.info("分类统计: %s", category_counts)
    logger.info(
        "批量上传完成: 成功=%d, 跳过=%d, 失败=%d",
        stats["success"], stats["skipped"], stats["failed"],
    )
    return stats
