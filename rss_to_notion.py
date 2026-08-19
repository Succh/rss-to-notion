#!/usr/bin/env python3
"""
RSS to Notion - 自动抓取 RSS 并推送到 Notion
新增: AI 摘要 + 自动清理 + 图片提取 + 全文内容
"""

import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml
from bs4 import BeautifulSoup
from readability import Document

# ========== 配置 ==========
WORKSPACE = Path(__file__).parent
CONFIG_FILE = WORKSPACE / "config.yaml"
STATE_FILE = WORKSPACE / "state.json"

# Notion API
NOTION_TOKEN = os.environ.get("NOTION_API_KEY", "")
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# AI API (DeepSeek)
AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_API_URL = "https://api.deepseek.com/v1/chat/completions"
AI_MODEL = "deepseek-chat"


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"items": {}, "last_run": None}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def make_fingerprint(url: str) -> str:
    return hashlib.md5(url.encode()).hexstrip()


def strip_html(text: str) -> str:
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator=" ", strip=True)[:1000]


def extract_images(html: str, base_url: str = "") -> list:
    """从 HTML 中提取所有图片 URL"""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    imgs = []
    for img in soup.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "") or img.get("data-original", "")
        if src:
            # 处理相对 URL
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/") and base_url:
                parsed = urlparse(base_url)
                src = f"{parsed.scheme}://{parsed.netloc}{src}"
            if src.startswith("http"):
                imgs.append(src)
    # 去重
    return list(dict.fromkeys(imgs))[:5]  # 最多5张


def extract_text(html: str) -> str:
    """从 HTML 中提取纯文本"""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    # 移除 script 和 style
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    # 清理空行
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    return "\n".join(lines)[:2000]


def fetch_full_content(url: str) -> tuple:
    """从原文链接提取全文内容和图片"""
    if not url:
        return "", []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, timeout=15, headers=headers)
        if r.status_code != 200:
            return "", []
        
        doc = Document(r.text)
        title = doc.short_title()
        summary = doc.summary()
        
        # 提取图片
        soup = BeautifulSoup(r.text, "html.parser")
        imgs = []
        # 优先取 og:image
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            imgs.append(og["content"])
        # 再取 article 内的图片
        article = soup.find("article") or soup.find("main") or soup.find("body")
        if article:
            for img in article.find_all("img")[:5]:
                src = img.get("src", "") or img.get("data-src", "")
                if src and src.startswith("http") and src not in imgs:
                    imgs.append(src)
        
        # 提取正文文本
        text = extract_text(summary)
        
        return text[:2000], imgs[:5]
    except Exception as e:
        return "", []


def parse_date(date_str: str) -> str:
    """解析 RSS 日期格式"""
    if not date_str:
        return datetime.utcnow().isoformat()[:10]
    try:
        dt = datetime.strptime(date_str.strip()[:25], "%a, %d %b %Y %H:%M:%S")
        return dt.isoformat()[:10]
    except:
        pass
    try:
        return date_str[:10]
    except:
        return datetime.utcnow().isoformat()[:10]


# ========== AI 摘要 ==========
def generate_summary(title: str, content: str) -> str:
    """使用 DeepSeek API 生成中文摘要，失败时降级到提取式摘要"""
    if not AI_API_KEY:
        return extractive_summary(content)
    
    clean_content = strip_html(content)
    if len(clean_content) > 3000:
        clean_content = clean_content[:3000]
    
    prompt = f"""请为以下文章生成一段简洁的中文摘要（80-120字），概括核心要点。
只输出摘要内容，不要任何前缀或解释。

标题: {title}
内容: {clean_content}"""

    try:
        resp = requests.post(
            AI_API_KEY and AI_API_URL or "https://api.deepseek.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {AI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": AI_MODEL,
                "messages": [
                    {"role": "system", "content": "你是一个专业的文章摘要助手。请用简洁的中文概括文章核心内容，80-120字。"},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 200,
                "temperature": 0.7
            },
            timeout=30
        )
        if resp.status_code == 200:
            result = resp.json()
            summary = result["choices"][0]["message"]["content"].strip()
            if len(summary) > 120:
                summary = summary[:120] + "..."
            return summary
        else:
            return extractive_summary(content)
    except Exception as e:
        return extractive_summary(content)


def extractive_summary(content: str) -> str:
    """提取式摘要（备用方案）"""
    clean = strip_html(content)
    if not clean:
        return "暂无摘要"
    
    sentences = re.split(r'[。！？.!?]', clean)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
    
    summary = "。".join(sentences[:2])
    if len(summary) > 120:
        summary = summary[:120] + "..."
    return summary if summary else "暂无摘要"


# ========== RSS 抓取 ==========
def fetch_rss(url: str) -> list:
    """抓取 RSS 源"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        r = requests.get(url, timeout=15, headers=headers)
        if r.status_code != 200:
            print(f"  ⚠️ HTTP {r.status_code}")
            return []
        root = ET.fromstring(r.content)
        items = root.findall(".//item")
        if not items:
            items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
        results = []
        for item in items:
            title = item.findtext("title", "") or item.findtext(".//{http://www.w3.org/2005/Atom}title", "")
            link = item.findtext("link", "") or item.find(".//{http://www.w3.org/2005/Atom}link")
            if link is not None:
                link = link.get("href", "") or link.text or ""
            desc = item.findtext("description", "") or item.findtext(".//{http://www.w3.org/2005/Atom}summary", "") or ""
            content_encoded = item.findtext(".//{http://purl.org/rss/1.0/modules/content/}encoded", "") or ""
            pub_date = item.findtext("pubDate", "") or item.findtext(".//{http://www.w3.org/2005/Atom}published", "") or ""
            
            # 提取图片
            html_content = desc + content_encoded
            images = extract_images(html_content, url)
            # 提取文本
            text = extract_text(content_encoded) or extract_text(desc)
            
            results.append({
                "title": (title or "").strip(),
                "link": (link or "").strip(),
                "description": desc,
                "text": text,
                "images": images,
                "date": parse_date(pub_date)
            })
        return results
    except Exception as e:
        print(f"  ⚠️ 抓取失败: {e}")
        return []


# ========== Notion 操作 ==========
def get_notion_database(database_id: str):
    """验证 Notion 数据库"""
    resp = requests.get(
        f"{NOTION_API}/databases/{database_id}",
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VERSION
        }
    )
    resp.raise_for_status()
    return resp.json()


def create_notion_page(database_id: str, item: dict, source_name: str) -> bool:
    """创建 Notion 页面（含图片和全文）"""
    properties = {
        "Title": {"title": [{"text": {"content": item["title"]}}]},
        "URL": {"url": item["link"]},
        "Source": {"rich_text": [{"text": {"content": source_name}}]},
        "Published": {"date": {"start": item["date"]}}
    }
    
    # 如果有摘要，添加属性
    summary = item.get("summary", "")
    if summary:
        properties["AI Summary"] = {"rich_text": [{"text": {"content": summary}}]}
    
    # 构建页面内容块
    children = []
    
    # 1. 摘要 Callout
    if summary:
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"text": {"content": f"📝 AI 摘要: {summary}"}}],
                "icon": {"emoji": "🤖"},
                "color": "blue_background"
            }
        })
    
    # 2. 图片（如果有）
    images = item.get("images", [])
    for img_url in images[:3]:  # 最多3张
        children.append({
            "object": "block",
            "type": "image",
            "image": {"type": "external", "external": {"url": img_url}}
        })
    
    # 3. 正文内容（如果有）
    text = item.get("text", "")
    if text:
        # 分段，每段不超过2000字符
        paragraphs = text.split("\n")
        for para in paragraphs:
            if para.strip():
                children.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"text": {"content": para.strip()[:2000]}}]
                    }
                })
    
    # 4. 阅读原文按钮
    children.append({
        "object": "block",
        "type": "divider"
    })
    children.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {"text": {"content": "📖 "}},
                {"text": {"content": "阅读原文", "link": {"url": item["link"]}}}
            ]
        }
    })
    
    payload = {
        "parent": {"database_id": database_id},
        "properties": properties,
        "children": children
    }
    
    try:
        resp = requests.post(
            f"{NOTION_API}/pages",
            headers={
                "Authorization": f"Bearer {NOTION_TOKEN}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json"
            },
            json=payload
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"  ❌ 创建页面失败: {e}")
        return False


def cleanup_old_pages(database_id: str, days: int = 30) -> int:
    """清理超过指定天数的旧文章"""
    cutoff_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    print(f"\n🧹 清理 {days} 天前的旧文章 (截止日期: {cutoff_date})")
    
    deleted_count = 0
    has_more = True
    next_cursor = None
    
    while has_more:
        payload = {
            "filter": {
                "property": "Published",
                "date": {"on_or_before": cutoff_date}
            },
            "page_size": 100
        }
        if next_cursor:
            payload["start_cursor"] = next_cursor
        
        try:
            resp = requests.post(
                f"{NOTION_API}/databases/{database_id}/query",
                headers={
                    "Authorization": f"Bearer {NOTION_TOKEN}",
                    "Notion-Version": NOTION_VERSION,
                    "Content-Type": "application/json"
                },
                json=payload
            )
            
            if resp.status_code != 200:
                print(f"  ❌ 查询失败: {resp.status_code}")
                break
            
            data = resp.json()
            pages = data.get("results", [])
            
            for page in pages:
                page_id = page["id"]
                try:
                    archive_resp = requests.patch(
                        f"{NOTION_API}/pages/{page_id}",
                        headers={
                            "Authorization": f"Bearer {NOTION_TOKEN}",
                            "Notion-Version": NOTION_VERSION,
                            "Content-Type": "application/json"
                        },
                        json={"archived": True}
                    )
                    if archive_resp.status_code == 200:
                        deleted_count += 1
                except Exception as e:
                    print(f"  ❌ 归档失败: {e}")
            
            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor")
            
        except Exception as e:
            print(f"  ❌ 清理过程出错: {e}")
            break
    
    print(f"  ✅ 已归档 {deleted_count} 篇旧文章")
    return deleted_count


def beautify_notion_database(database_id: str, parent_page_id: str = ""):
    """美化 Notion 数据库"""
    try:
        resp = requests.patch(
            f"{NOTION_API}/databases/{database_id}",
            headers={
                "Authorization": f"Bearer {NOTION_TOKEN}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json"
            },
            json={
                "icon": {"emoji": "📰"},
                "cover": {
                    "type": "external",
                    "external": {"url": "https://images.unsplash.com/photo-1586339949916-3e9457bef6d3?w=1200&h=600&fit=crop"}
                }
            }
        )
        if resp.status_code == 200:
            print("🎨 数据库美化成功")
    except Exception as e:
        print(f"⚠️ 美化失败: {e}")


def record_item(state: dict, link: str):
    """记录已处理的条目"""
    fp = make_fingerprint(link)
    state["items"][fp] = {
        "link": link,
        "processed_at": datetime.utcnow().isoformat()
    }


def is_processed(state: dict, link: str) -> bool:
    """检查是否已处理"""
    fp = make_fingerprint(link)
    return fp in state["items"]


def main():
    if not NOTION_TOKEN:
        print("❌ 未设置 NOTION_API_KEY 环境变量")
        sys.exit(1)

    config = load_config()
    state = load_state()

    database_id = config["notion"]["database_id"]
    if database_id == "YOUR_DATABASE_ID_HERE":
        print("❌ 请先配置 Notion 数据库 ID")
        sys.exit(1)

    # 验证数据库
    try:
        get_notion_database(database_id)
        print("✅ Notion 数据库连接成功")
    except Exception as e:
        print(f"❌ 数据库验证失败: {e}")
        sys.exit(1)

    # 美化数据库
    parent_page_id = config["notion"].get("parent_page_id", "")
    beautify_notion_database(database_id, parent_page_id)

    # 抓取所有源
    all_items = []
    for src_id, src_conf in config["rss_sources"].items():
        if not src_conf.get("enabled", True):
            continue
        print(f"\n📡 抓取: {src_conf['name']}")
        items = fetch_rss(src_conf["url"])
        print(f"   获取 {len(items)} 条")
        for item in items:
            item["source_id"] = src_id
            item["source_name"] = src_conf["name"]
        all_items.extend(items)

    # 去重
    new_items = [item for item in all_items if not is_processed(state, item["link"])]
    print(f"\n📊 总计: {len(all_items)} 条, 新增: {len(new_items)} 条")

    if not new_items:
        print("ℹ️ 没有新内容")
        # 仍然执行清理
        cleanup_days = config.get("settings", {}).get("cleanup_days", 30)
        if cleanup_days > 0:
            cleanup_old_pages(database_id, cleanup_days)
        state["last_run"] = datetime.utcnow().isoformat()
        save_state(state)
        return

    # 限制数量
    max_items = config["settings"].get("max_items_per_run", 20)
    if len(new_items) > max_items:
        print(f"⚠️ 超出限制，只推送前 {max_items} 条")
        new_items = new_items[:max_items]

    # 生成 AI 摘要
    ai_enabled = config.get("ai", {}).get("enabled", False) or bool(AI_API_KEY)
    if ai_enabled:
        print(f"\n🤖 正在生成 AI 摘要...")
        for i, item in enumerate(new_items, 1):
            summary = generate_summary(item["title"], item.get("text", "") + item.get("description", ""))
            item["summary"] = summary
            print(f"  [{i}/{len(new_items)}] {item['title'][:40]}... -> {summary[:30]}...")

    # 推送
    success = 0
    for i, item in enumerate(new_items, 1):
        print(f"\n[{i}/{len(new_items)}] {item['title'][:50]}")
        print(f"  📷 图片: {len(item.get('images', []))} 张")
        print(f"  📝 内容: {len(item.get('text', ''))} 字")
        if create_notion_page(database_id, item, item["source_name"]):
            record_item(state, item["link"])
            success += 1
            print("  ✅ 成功")

    # 自动清理旧文章
    cleanup_days = config.get("settings", {}).get("cleanup_days", 30)
    if cleanup_days > 0:
        cleanup_old_pages(database_id, cleanup_days)

    state["last_run"] = datetime.utcnow().isoformat()
    save_state(state)

    print(f"\n{'='*40}")
    print(f"🎉 完成! 成功推送 {success}/{len(new_items)} 条")


if __name__ == "__main__":
    main()
