"""
Zotero API 交互模块
负责：获取/创建 Collection、将论文条目导入 Zotero、查询已存在条目以避免重复导入。
"""

import time
import logging
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)


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
    timeout: int = 30,
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


def find_or_create_collection(collection_name: str) -> str:
    """
    查找指定名称的 Collection，如果不存在则自动创建。

    Args:
        collection_name: Collection 名称

    Returns:
        Collection 的 key
    """
    # 先查找
    collections = get_all_collections()
    for col in collections:
        if col.get("data", {}).get("name") == collection_name:
            key: str = col["key"]
            logger.info("找到已有 Collection: %s (key=%s)", collection_name, key)
            return key

    # 未找到，创建新的
    logger.info("Collection '%s' 不存在，正在创建...", collection_name)
    headers = _build_headers()
    url = f"{config.ZOTERO_BASE_URL}/users/{config.ZOTERO_USER_ID}/collections"

    resp = _make_request("POST", url, headers, json_data=[{"name": collection_name}])
    result: dict[str, Any] = resp.json()

    if "successful" in result:
        new_key: str = list(result["successful"].values())[0]["key"]
        logger.info("成功创建 Collection: %s (key=%s)", collection_name, new_key)
        return new_key
    else:
        raise RuntimeError(f"创建 Collection 失败: {result}")


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
            # 分页信息在 Header 中
            total_results: str | None = resp.headers.get("Total-Results", "0")
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


def _parse_authors(authors: list[dict[str, Any]]) -> list[dict[str, str]]:
    """
    将 Semantic Scholar 的作者格式转换为 Zotero 的 creators 格式。
    处理姓名拆分逻辑：尝试按空格分割为 firstName + lastName。

    Args:
        authors: Semantic Scholar 返回的作者列表

    Returns:
        Zotero creators 列表
    """
    creators: list[dict[str, str]] = []
    for author in authors:
        name: str = author.get("name", "").strip()
        if not name:
            continue

        # 尝试分割为 firstName 和 lastName
        parts: list[str] = name.split()
        if len(parts) >= 2:
            creators.append({
                "creatorType": "author",
                "firstName": parts[0],
                "lastName": " ".join(parts[1:]),
            })
        elif len(parts) == 1:
            # 单个词的名字，使用 name 字段（Zotero 对中文姓名友好）
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

    # 处理日期：优先使用 publicationDate，否则使用 year
    date_str: str = publication_date if publication_date else str(paper.get("year", ""))

    # 处理标签
    item_tags: list[dict[str, str]] = [{"tag": "AI-Auto-Fetch"}]
    if tags:
        item_tags.extend([{"tag": t} for t in tags])

    # 将 fieldsOfStudy 也作为标签
    for field in paper.get("fieldsOfStudy", []):
        item_tags.append({"tag": field})

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

    # 如果没有期刊信息但有 venue，使用 venue
    if not item.get("publicationTitle") and paper.get("venue"):
        item["publicationTitle"] = paper["venue"]

    # Open Access PDF 链接
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
    title: str = paper.get("title", "Untitled")[:60]

    try:
        resp = _make_request("POST", url, headers, json_data=[item])
        result: dict[str, Any] = resp.json()

        if "successful" in result and result["successful"]:
            logger.info("✅ 成功入库: %s", title)
            return True
        elif "unchanged" in result and result["unchanged"]:
            logger.info("⏭️ 已存在，跳过: %s", title)
            return True
        else:
            failed: dict[str, Any] = result.get("failed", {})
            logger.error("❌ 入库失败 '%s': %s", title, failed)
            return False

    except Exception as e:
        logger.error("❌ 入库异常 '%s': %s", title, e)
        return False


def batch_upload_to_zotero(
    papers: list[dict[str, Any]],
    collection_name: str | None = None,
) -> dict[str, int]:
    """
    批量上传论文到 Zotero，自动处理 Collection 查找/创建、DOI 去重。
    优先使用直接指定的 ZOTERO_COLLECTION_KEY，否则按名称查找/创建。

    Args:
        papers: 论文列表
        collection_name: 目标 Collection 名称（默认使用配置值）

    Returns:
        统计信息 {"success": 成功数, "skipped": 跳过数, "failed": 失败数}
    """
    if not config.ZOTERO_USER_ID or not config.ZOTERO_API_KEY:
        logger.error("Zotero 配置缺失，跳过上传。请设置 ZOTERO_API_KEY 和 ZOTERO_USER_ID。")
        return {"success": 0, "skipped": len(papers), "failed": 0}

    stats: dict[str, int] = {"success": 0, "skipped": 0, "failed": 0}

    # 1. 获取 Collection key：优先使用直接指定的 key，否则按名称查找/创建
    collection_key: str | None = config.ZOTERO_COLLECTION_KEY
    if not collection_key:
        collection_name = collection_name or config.ZOTERO_COLLECTION_NAME
        try:
            collection_key = find_or_create_collection(collection_name)
        except Exception as e:
            logger.error("获取/创建 Collection 失败: %s", e)
            return {"success": 0, "skipped": 0, "failed": len(papers)}
    else:
        logger.info("使用指定的 Collection key: %s", collection_key)

    # 2. 获取已有 DOI，避免重复
    existing_dois = get_existing_dois_in_collection(collection_key)

    # 3. 逐篇上传（Zotero API 单次写入限制约 50 条，逐篇更可靠）
    for paper in papers:
        doi: str = (paper.get("externalIds") or {}).get("DOI", "")
        if doi and doi.lower() in existing_dois:
            logger.info("⏭️ DOI 已存在，跳过: %s", paper.get("title", "")[:60])
            stats["skipped"] += 1
            continue

        success = upload_paper_to_zotero(paper, collection_key)
        if success:
            stats["success"] += 1
            if doi:
                existing_dois.add(doi.lower())
        else:
            stats["failed"] += 1

        # 遵守 Zotero 速率限制（无 Key 用户尤其需要注意）
        time.sleep(config.REQUEST_DELAY_SECONDS)

    logger.info(
        "批量上传完成: 成功=%d, 跳过=%d, 失败=%d",
        stats["success"], stats["skipped"], stats["failed"],
    )
    return stats
