#!/usr/bin/env python3
"""
RSS to Notion - 通过 rss2json.com 代理抓取 RSS（绕过 GFW）
支持 IT之家、少数派、钛媒体等国内源
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

# ========== 配置 ==========
WORKSPACE = Path(__file__).parent
CONFIG_FILE = WORKSPACE / "config.yaml"
STATE_FILE = WORKSPACE / "state.json"

NOTION_TOKEN = os.environ.get("NOTION_API_KEY", "")
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
RSS2JSON_API = "https://api.rss2json.com/v1/api.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


# ========== RSS 抓取（通过 rss2json 代理） ==========

def fetch_rss_via_proxy(url: str, count: int = 5) -> list:
    """通过 rss2json.com 代理抓取 RSS，解决 GFW 问题"""
    params = {"rss_url": url, "count": count}
    try:
        r = requests.get(RSS2JSON_API, params=params, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        
        if data.get("status") != "ok":
            print(f"  ⚠️ rss2json 返回错误: {data.get('message', '未知')}")
            return []
        
        items = []
        for entry in data.get("items", []):
            # 提取图片（从 content HTML 中）
            content_html = entry.get("content", "") or ""
            images = []
            if content_html:
                soup = BeautifulSoup(content_html, "html.parser")
                for img in soup.find_all("img"):
                    src = img.get("src") or img.get("data-src") or ""
                    if src and src.startswith("http"):
                        images.append(src)
            
            # 提取纯文本
            text = ""
            if content_html:
                soup = BeautifulSoup(content_html, "html.parser")
                text = soup.get_text(separator="\n", strip=True)
            
            # 解析发布时间
            pub_date = entry.get("pubDate", "")
            
            item = {
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "description": entry.get("description", "") or "",
                "text": text,
                "images": images[:5],
                "pub_date": pub_date,
                "author": entry.get("author", ""),
            }
            
            if item["title"] and item["link"]:
                items.append(item)
        
        return items
        
    except requests.exceptions.Timeout:
        print(f"  ⏰ rss2json 超时: {url}")
        return []
    except Exception as e:
        print(f"  ❌ rss2json 错误: {e}")
        return []


def fetch_rss_direct(url: str, count: int = 5) -> list:
    """直接抓取 RSS（用于海外源）"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"  ❌ 直接抓取失败: {e}")
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    items = []
    for item in channel.findall("item")[:count]:
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        desc = item.findtext("description", "") or ""

        images = extract_images(desc)
        text = extract_text(desc)

        pub_date = item.findtext("pubDate", "")

        if title and link:
            items.append({
                "title": title,
                "link": link,
                "description": desc,
                "text": text,
                "images": images[:5],
                "pub_date": pub_date,
                "author": "",
            })

    return items


def fetch_rss(url: str, use_proxy: bool = True, count: int = 5) -> list:
    """智能抓取：默认通过 rss2json 代理，失败则直接抓取"""
    if use_proxy:
        items = fetch_rss_via_proxy(url, count=count)
        if items:
            return items
        print(f"  📡 代理失败，尝试直接抓取...")
    return fetch_rss_direct(url, count=count)


# ========== 内容提取 ==========

def extract_images(html: str) -> list:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if src and src.startswith("http") and not any(
            x in src for x in ["avatar", "icon", "logo", "emoji", "tracking", "pixel"]
        ):
            images.append(src)
    return list(dict.fromkeys(images))  # 去重


def extract_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # 过滤导航类文本
    lines = [l for l in lines if len(l) > 5 or re.search(r"[\u4e00-\u9fff]", l)]
    return "\n".join(lines)


# ========== AI 摘要 ==========

def generate_summary(title: str, content: str) -> str:
    if not content or len(content.strip()) < 20:
        return f"📌 {title}"
    # 提取前 200 字
    summary = content[:200].strip()
    if len(content) > 200:
        summary += "..."
    return summary


# ========== Notion API ==========

def get_notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def create_notion_page(database_id: str, item: dict, source_name: str) -> bool:
    summary = generate_summary(item["title"], item.get("text", ""))
    item["summary"] = summary

    # 清理标题中的非法字符
    title = re.sub(r'[\n\r\t]', ' ', item["title"])[:200]

    properties = {
        "Title": {"title": [{"text": {"content": title}}]},
        "Source": {"rich_text": [{"text": {"content": source_name}}]},
    }

    if item.get("pub_date"):
        try:
            dt = datetime.strptime(item["pub_date"], "%a, %d %b %Y %H:%M:%S %z")
            properties["Published"] = {"date": {"start": dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")}}
        except:
            try:
                dt = datetime.fromisoformat(item["pub_date"].replace("Z", "+00:00"))
                properties["Published"] = {"date": {"start": dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")}}
            except:
                pass

    if summary:
        properties["AI Summary"] = {"rich_text": [{"text": {"content": summary[:2000]}}]}

    # 构建页面块
    children = []

    # 1. 摘要
    if summary:
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"text": {"content": f"📝 AI 摘要: {summary}"}}],
                "icon": {"emoji": "🤖"},
                "color": "blue_background",
            },
        })

    # 2. 图片
    for img_url in item.get("images", [])[:3]:
        children.append({
            "object": "block",
            "type": "image",
            "image": {"type": "external", "external": {"url": img_url}},
        })

    # 3. 正文
    text = item.get("text", "")
    if text:
        paragraphs = text.split("\n")
        for para in paragraphs:
            if para.strip() and len(para.strip()) > 5:
                children.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"text": {"content": para.strip()[:2000]}}]
                    },
                })

    # 4. 分隔符 + 原文链接
    children.append({"object": "block", "type": "divider"})
    children.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {"text": {"content": "📖 "}},
                {"text": {"content": "阅读原文", "link": {"url": item["link"]}}},
            ]
        },
    })

    payload = {
        "parent": {"database_id": database_id},
        "properties": properties,
        "children": children,
    }

    try:
        r = requests.post(
            f"{NOTION_API}/pages",
            headers=get_notion_headers(),
            json=payload,
            timeout=30,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"  ❌ Notion 错误: {e}")
        if hasattr(e, 'response'):
            try:
                print(f"     {e.response.json()}")
            except:
                pass
        return False


# ========== 状态管理 ==========

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"items": {}}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def make_hash(link: str) -> str:
    return hashlib.md5(link.encode()).hexdigest()[:16]


def is_new(state: dict, link: str) -> bool:
    return make_hash(link) not in state.get("items", {})


def record_item(state: dict, link: str):
    h = make_hash(link)
    state.setdefault("items", {})[h] = {
        "link": link,
        "added_at": datetime.now().isoformat(),
    }


def cleanup_state(state: dict, days: int = 7):
    cutoff = datetime.now() - timedelta(days=days)
    items = state.get("items", {})
    to_remove = []
    for h, v in items.items():
        try:
            t = datetime.fromisoformat(v["added_at"])
            if t < cutoff:
                to_remove.append(h)
        except:
            pass
    for h in to_remove:
        del items[h]
    return len(to_remove)


# ========== 主流程 ==========

def main():
    if not NOTION_TOKEN:
        print("❌ 缺少 NOTION_API_KEY")
        sys.exit(1)

    database_id = os.environ.get("NOTION_DATABASE_ID", "3c15a375-9092-815a-aa2a-c03f5286890d")
    
    with open(CONFIG_FILE) as f:
        config = yaml.safe_load(f)

    # 读取配置
    max_items = config.get("settings", {}).get("max_items_per_source", 5)
    
    state = load_state()

    print("=" * 60)
    print(f"📡 RSS to Notion (每源最多 {max_items} 篇)")
    print("=" * 60)

    # 抓取
    all_items = []
    for name, source in config.get("rss_sources", {}).items():
        if not source.get("enabled", False):
            continue
        
        url = source["url"]
        display_name = source.get("name", name)
        use_proxy = source.get("use_proxy", True)
        
        print(f"\n📡 [{display_name}] via {'proxy' if use_proxy else 'direct'}")
        items = fetch_rss(url, use_proxy=use_proxy, count=max_items)
        print(f"  获取 {len(items)} 条")

        for item in items:
            if is_new(state, item["link"]):
                item["source_name"] = display_name
                all_items.append(item)

    print(f"\n📦 共 {len(all_items)} 条新内容")

    if not all_items:
        print("✅ 无新内容")
        cleanup_state(state)
        save_state(state)
        return

    # 推送
    success = 0
    for i, item in enumerate(all_items, 1):
        print(f"\n[{i}/{len(all_items)}] {item['title'][:50]}")
        print(f"  📷 图片: {len(item.get('images', []))} 张")
        print(f"  📝 内容: {len(item.get('text', ''))} 字")
        if create_notion_page(database_id, item, item["source_name"]):
            record_item(state, item["link"])
            success += 1
            print("  ✅ 成功")
        else:
            print("  ❌ 失败")

    print(f"\n{'=' * 60}")
    print(f"📊 完成: {success}/{len(all_items)} 成功")

    # 清理
    cleaned = cleanup_state(state, days=config.get("settings", {}).get("keep_days", 7))
    if cleaned:
        print(f"🧹 清理 {cleaned} 条旧记录")

    save_state(state)
    print("✅ 同步完成")


if __name__ == "__main__":
    main()
