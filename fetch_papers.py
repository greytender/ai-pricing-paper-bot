import os
import requests
from datetime import datetime

# 1. 从 GitHub 安全锁中读取你的四把钥匙
ZOTERO_KEY = os.getenv("ZOTERO_API_KEY")
ZOTERO_ID = os.getenv("ZOTERO_USER_ID")
COLLECTION_ID = os.getenv("ZOTERO_COLLECTION_ID")
SS_KEY = os.getenv("SEMANTIC_SCHOLAR_KEY")

# 2. 设定你的三维组合关键词
QUERY = '("AI product" OR "LLM" OR "SaaS" OR "generative AI") AND ("pricing" OR "mechanism design") AND ("game theory" OR "equilibrium")'

def get_latest_papers():
    # 调用 Semantic Scholar 搜索接口
    current_year = datetime.now().year
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={QUERY}&year=2025-{current_year}&fields=title,abstract,authors,doi,url,year"
    
    # 带上官方学术钥匙，从此享受免限速的高级通道待遇
    headers = {}
    if SS_KEY:
        headers["x-api-key"] = SS_KEY  # 官方身份验证字段
        
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get("data", [])
    return []

def upload_to_zotero(paper):
    # 将抓到的文献数据转换为 Zotero 能够识别的 JSON 格式
    zotero_url = f"https://api.zotero.org/users/{ZOTERO_ID}/items"
    headers = {
        "Authorization": f"Bearer {ZOTERO_KEY}",
        "Content-Type": "application/json"
    }
    
    # 提取前三位作者的姓氏
    creators = []
    if paper.get("authors"):
        for auth in paper["authors"][:3]:
            creators.append({"creatorType": "author", "lastName": auth.get("name", "Unknown")})

    # 封装符合 Zotero 规范的条目
    payload = [{
        "itemType": "journalArticle",
        "title": paper.get("title", "Untitled"),
        "abstractNote": paper.get("abstract", "No abstract available"),
        "creators": creators,
        "date": str(paper.get("year", "")),
        "url": paper.get("url", ""),
        "DOI": paper.get("doi", "") if paper.get("doi") else "",
        "collections": [COLLECTION_ID],
        "tags": [{"tag": "🤖AI自动爬取"}, {"tag": "博弈论定价"}]
    }]
    
    res = requests.post(zotero_url, headers=headers, json=payload)
    if res.status_code == 201:
        print(f"成功入库: {paper.get('title')}")
    else:
        print(f"入库失败的原因: {res.text}")

if __name__ == "__main__":
    print("开始使用官方学术通道扫描文献...")
    papers = get_latest_papers()
    print(f"共发现 {len(papers)} 篇潜在相关论文，开始筛选入库...")
    for paper in papers:
        # 简单清洗：必须包含摘要才入库，确保文献质量
        if paper.get("abstract"):
            upload_to_zotero(paper)
    print("今日文献流同步完成！")