#!/usr/bin/env python3
"""
RSS to Notion - 通过 rss2json.com 代理抓取 RSS（绕过 GFW）
每源只抓最新 5 篇，只推新文章
"""

import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

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


# ========== RSS 抓取 ==========

def fetch_rss_via_proxy(url: str, count: int = 5) -> list:
    """通过 rss2json.com 代理抓取 RSS"""
    params = {"rss_url": url}
    try:
        r = requests.get(RSS2JSON_API, params=params, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  ❌ rss2json 错误: {e}")
        return []

    if data.get("status") != "ok":
        print(f"  ⚠️ rss2json 返回错误")
        return []

    items = []
    for entry in data.get("items", [])[:count]:
        content_html = entry.get("content", "") or ""
        images = []
        text = ""
        if content_html:
            soup = BeautifulSoup(content_html, "html.parser")
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src") or ""
                if src and src.startswith("http"):
                    images.append(src)
            text = soup.get_text(separator="\n", strip=True)

        item = {
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "text": text,
            "images": images[:5],
            "pub_date": entry.get("pubDate", ""),
        }
        if item["title"] and item["link"]:
            items.append(item)

    return items


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

        soup = BeautifulSoup(desc, "html.parser")
        images = []
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if src and src.startswith("http"):
                images.append(src)
        text = soup.get_text(separator="\n", strip=True)

        if title and link:
            items.append({
                "title": title,
                "link": link,
                "text": text,
                "images": images[:5],
                "pub_date": item.findtext("pubDate", ""),
            })

    return items


def fetch_rss(url: str, use_proxy: bool = True, count: int = 5) -> list:
    """智能抓取"""
    if use_proxy:
        items = fetch_rss_via_proxy(url, count=count)
        if items:
            return items
        print(f"  📡 代理失败，尝试直接抓取...")
    return fetch_rss_direct(url, count=count)


# ========== 摘要 ==========

def generate_summary(title: str, content: str) -> str:
    if not content or len(content.strip()) < 20:
        return f"📌 {title}"
    return content[:200].strip() + ("..." if len(content) > 200 else "")


# ========== Notion ==========

def get_notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def create_notion_page(database_id: str, item: dict, source_name: str) -> bool:
    summary = generate_summary(item["title"], item.get("text", ""))
    item["summary"] = summary

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

    children = []

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

    for img_url in item.get("images", [])[:3]:
        children.append({
            "object": "block",
            "type": "image",
            "image": {"type": "external", "external": {"url": img_url}},
        })

    text = item.get("text", "")
    if text:
        for para in text.split("\n"):
            if para.strip() and len(para.strip()) > 5:
                children.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"text": {"content": para.strip()[:2000]}}]
                    },
                })

    children.append({"object": "block", "type": "divider", "divider": {}})
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
        if hasattr(e, 'response') and e.response is not None:
            try:
                err_body = e.response.json()
                print(f"     详情: {err_body.get('message', '')[:200]}")
            except:
                pass
        return False


# ========== 状态 ==========

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


def cleanup_state(state: dict, days: int = 7) -> int:
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

    max_items = config.get("settings", {}).get("max_items_per_source", 5)
    state = load_state()

    print("=" * 60)
    print(f"📡 RSS to Notion (每源 {max_items} 篇, 仅新文章)")
    print("=" * 60)

    all_items = []
    for name, source in config.get("rss_sources", {}).items():
        if not source.get("enabled", False):
            continue

        url = source["url"]
        display_name = source.get("name", name)
        use_proxy = source.get("use_proxy", True)

        print(f"\n📡 [{display_name}]")
        items = fetch_rss(url, use_proxy=use_proxy, count=max_items)
        print(f"  获取 {len(items)} 条")

        new_count = 0
        for item in items:
            if is_new(state, item["link"]):
                item["source_name"] = display_name
                all_items.append(item)
                new_count += 1
        print(f"  新增 {new_count} 条")

    print(f"\n📦 共 {len(all_items)} 条新内容待推送")

    if not all_items:
        print("✅ 无新内容")
        cleanup_state(state)
        save_state(state)
        return

    success = 0
    for i, item in enumerate(all_items, 1):
        print(f"\n[{i}/{len(all_items)}] {item['title'][:50]}")
        print(f"  📷 {len(item.get('images', []))} 张 | 📝 {len(item.get('text', ''))} 字")
        if create_notion_page(database_id, item, item["source_name"]):
            record_item(state, item["link"])
            success += 1
            print("  ✅ 成功")
        else:
            print("  ❌ 失败")

    print(f"\n{'=' * 60}")
    print(f"📊 完成: {success}/{len(all_items)} 成功")

    cleaned = cleanup_state(state, days=config.get("settings", {}).get("keep_days", 7))
    if cleaned:
        print(f"🧹 清理 {cleaned} 条旧记录")

    save_state(state)
    print("✅ 同步完成")


if __name__ == "__main__":
    main()
