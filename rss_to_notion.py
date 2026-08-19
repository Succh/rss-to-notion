#!/usr/bin/env python3
"""
RSS to Notion - 自动抓取 RSS 并推送到 Notion
修复了日期格式、依赖问题
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

# ========== 配置 ==========
WORKSPACE = Path(__file__).parent
CONFIG_FILE = WORKSPACE / "config.yaml"
STATE_FILE = WORKSPACE / "state.json"

# Notion API
NOTION_TOKEN = os.environ.get("NOTION_API_KEY", "")
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


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
    return hashlib.md5(url.encode()).hexdigest()


def strip_html(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", clean).strip()[:800]


def parse_date(date_str: str) -> str:
    """解析 RSS 日期格式"""
    if not date_str:
        return datetime.utcnow().isoformat()[:10]
    try:
        # RFC 822: Wed, 19 Aug 2026 10:00:00 +0000
        dt = datetime.strptime(date_str.strip()[:25], "%a, %d %b %Y %H:%M:%S")
        return dt.isoformat()[:10]
    except:
        pass
    try:
        # ISO 格式
        return date_str[:10]
    except:
        return datetime.utcnow().isoformat()[:10]


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
            title = item.find("title")
            link = item.find("link")
            desc = item.find("description") or item.find("{http://www.w3.org/2005/Atom}summary")
            pub = item.find("pubDate") or item.find("{http://www.w3.org/2005/Atom}published") or item.find("{http://www.w3.org/2005/Atom}updated")
            link_url = ""
            if link is not None:
                link_url = link.text if link.text else link.get("href", "")
            results.append({
                "title": title.text if title is not None else "(无标题)",
                "link": link_url,
                "summary": strip_html(desc.text) if desc is not None else "",
                "published": parse_date(pub.text if pub is not None else ""),
            })
        return results
    except ET.ParseError as e:
        print(f"  ⚠️ XML解析错误: {e}")
        return []
    except Exception as e:
        print(f"  ⚠️ 抓取错误: {e}")
        return []


def is_duplicate(state: dict, link: str, dedup_days: int) -> bool:
    """检查是否重复"""
    fp = make_fingerprint(link)
    if fp in state["items"]:
        last_seen = datetime.fromisoformat(state["items"][fp])
        if (datetime.utcnow() - last_seen).days < dedup_days:
            return True
    return False


def record_item(state: dict, link: str):
    """记录已推送"""
    fp = make_fingerprint(link)
    state["items"][fp] = datetime.utcnow().isoformat()


def get_notion_database(database_id: str) -> dict:
    """验证数据库"""
    resp = requests.get(
        f"{NOTION_API}/databases/{database_id}",
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VERSION,
        },
    )
    if resp.status_code != 200:
        raise Exception(f"数据库不存在: {resp.status_code}")
    return resp.json()


def create_notion_page(database_id: str, item: dict, source_name: str) -> bool:
    """创建 Notion 页面"""
    payload = {
        "parent": {"database_id": database_id},
        "properties": {
            "Title": {"title": [{"text": {"content": item["title"][:2000]}}]},
            "URL": {"url": item["link"]},
            "Source": {"rich_text": [{"text": {"content": source_name}}]},
            "Published": {"date": {"start": item["published"]}},
        },
        "children": [
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": item["summary"]}}]}},
            {"object": "block", "type": "divider", "divider": {}},
            {"object": "block", "type": "bookmark", "bookmark": {"url": item["link"]}},
        ],
    }

    resp = requests.post(
        f"{NOTION_API}/pages",
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        json=payload,
    )

    if resp.status_code == 200:
        return True
    else:
        print(f"  ❌ Notion 写入失败: {resp.status_code}")
        return False


def beautify_notion_database(database_id: str, parent_page_id: str = ""):
    """美化 Notion 页面"""
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    # 设置数据库图标和封面
    db_payload = {
        "icon": {"emoji": "📰"},
        "cover": {
            "type": "external",
            "external": {
                "url": "https://images.unsplash.com/photo-1504711434969-e33886168f5c?w=1200&h=600&fit=crop"
            },
        },
    }
    resp = requests.patch(f"{NOTION_API}/databases/{database_id}", headers=headers, json=db_payload)
    if resp.status_code == 200:
        print("🎨 数据库美化成功")

    if parent_page_id:
        page_payload = {
            "icon": {"emoji": "🗞️"},
            "cover": {
                "type": "external",
                "external": {
                    "url": "https://images.unsplash.com/photo-1586339949916-3e9457bef6d3?w=1200&h=600&fit=crop"
                },
            },
        }
        resp = requests.patch(f"{NOTION_API}/pages/{parent_page_id}", headers=headers, json=page_payload)
        if resp.status_code == 200:
            print("🎨 父页面美化成功")

        welcome_blocks = [
            {"object": "block", "type": "callout", "callout": {
                "rich_text": [{"text": {"content": "🤖 这里是 RSS 自动订阅中心\n\n每 5 小时自动抓取最新的科技资讯"}}],
                "icon": {"emoji": "📡"}, "color": "blue_background"}},
            {"object": "block", "type": "divider", "divider": {}},
        ]
        resp = requests.patch(f"{NOTION_API}/blocks/{parent_page_id}/children", headers=headers, json={"children": welcome_blocks})
        if resp.status_code == 200:
            print("🎨 欢迎内容添加成功")


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

    # 美化页面
    parent_page_id = config["notion"].get("parent_page_id", "")
    beautify_notion_database(database_id, parent_page_id)

    # 抓取所有源
    all_items = []
    for src_id, src_conf in config["rss_sources"].items():
        if not src_conf.get("enabled", True):
            continue
        print(f"📡 抓取: {src_conf['name']}")
        items = fetch_rss(src_conf["url"])
        print(f"   获取 {len(items)} 条")
        for item in items:
            item["source_id"] = src_id
            item["source_name"] = src_conf["name"]
        all_items.extend(items)

    # 去重
    dedup_days = config["settings"].get("dedup_days", 7)
    new_items = []
    for item in all_items:
        if not is_duplicate(state, item["link"], dedup_days):
            new_items.append(item)

    print(f"\n📊 总计: {len(all_items)} 条, 新增: {len(new_items)} 条")

    if not new_items:
        print("ℹ️ 没有新内容")
        return

    # 限制数量
    max_items = config["settings"].get("max_items_per_run", 20)
    if len(new_items) > max_items:
        print(f"⚠️ 超出限制，只推送前 {max_items} 条")
        new_items = new_items[:max_items]

    # 推送
    success = 0
    for i, item in enumerate(new_items, 1):
        print(f"\n[{i}/{len(new_items)}] {item['title'][:50]}")
        if create_notion_page(database_id, item, item["source_name"]):
            record_item(state, item["link"])
            success += 1
            print("  ✅ 成功")

    state["last_run"] = datetime.utcnow().isoformat()
    save_state(state)

    print(f"\n{'='*40}")
    print(f"🎉 完成! 成功推送 {success}/{len(new_items)} 条")


if __name__ == "__main__":
    main()
