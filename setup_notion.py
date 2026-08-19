#!/usr/bin/env python3
"""
Notion 数据库初始化脚本
运行此脚本会自动在你的 Notion 工作区创建一个 RSS 订阅数据库

使用方法:
1. 先设置 NOTION_API_KEY 环境变量
2. 确保 Integration 已添加到工作区（在 Notion 中手动操作）
3. 运行: python setup_notion.py

数据库字段:
- Title (title): 文章标题
- URL (url): 原文链接
- Source (rich_text): 来源名称
- Published (date): 发布时间
- AI Summary (rich_text): AI 生成的一句话摘要
- Tags (multi_select): 标签
"""

import json
import os
import sys

import requests

NOTION_TOKEN = os.environ.get("NOTION_API_KEY", "")
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# 数据库字段定义
DATABASE_SCHEMA = {
    "title": [{"text": {"content": "📰 RSS 订阅"}}],
    "properties": {
        "Title": {"title": {}},
        "URL": {"url": {}},
        "Source": {"rich_text": {}},
        "Published": {"date": {}},
        "AI Summary": {"rich_text": {}},
        "Tags": {
            "multi_select": {
                "options": [
                    {"name": "福利吧", "color": "blue"},
                    {"name": "Hacker News", "color": "red"},
                    {"name": "V2EX", "color": "green"},
                    {"name": "少数派", "color": "yellow"},
                    {"name": "Readhub", "color": "purple"},
                ]
            }
        },
    },
}


def create_database(parent_page_id: str = None) -> str:
    """
    创建数据库
    parent_page_id: 可选，将数据库创建在某个页面下
    """
    payload = {
        "parent": {"page_id": parent_page_id} if parent_page_id else {"workspace": True},
        **DATABASE_SCHEMA,
    }

    resp = requests.post(
        f"{NOTION_API}/databases",
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        json=payload,
    )

    if resp.status_code == 200:
        data = resp.json()
        db_id = data["id"]
        db_url = data.get("url", "")
        print(f"✅ 数据库创建成功!")
        print(f"   ID:  {db_id}")
        print(f"   URL: {db_url}")
        return db_id
    else:
        print(f"❌ 数据库创建失败: {resp.status_code}")
        print(resp.text)
        return None


def find_parent_page() -> str:
    """
    尝试获取工作区中的第一个页面作为父级
    """
    resp = requests.post(
        f"{NOTION_API}/search",
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        json={
            "query": "",
            "filter": {"value": "page", "property": "object"},
            "page_size": 5,
        },
    )
    if resp.status_code == 200:
        data = resp.json()
        pages = data.get("results", [])
        if pages:
            return pages[0]["id"]
    return None


def update_config_yaml(database_id: str):
    """自动更新 config.yaml 中的 database_id"""
    import yaml

    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        
        config["notion"]["database_id"] = database_id
        
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        
        print(f"\n✅ config.yaml 已更新 database_id")
    else:
        print(f"\n⚠️ 未找到 config.yaml，请手动更新 database_id 为: {database_id}")


if __name__ == "__main__":
    if NOTION_TOKEN:
        print("🔑 使用 NOTION_API_KEY 环境变量")
    else:
        print("❌ 未设置 NOTION_API_KEY 环境变量")
        print("   运行: export NOTION_API_KEY=你的Token")
        sys.exit(1)

    print("🚀 开始创建 Notion 数据库...")
    print(f"   字段: Title, URL, Source, Published, AI Summary, Tags")
    print()

    # 可选：查找父页面
    parent = find_parent_page()
    if parent:
        print(f"📁 将数据库创建在页面 {parent[:8]}... 下")
    else:
        print("📁 将数据库创建在根目录")

    db_id = create_database(parent)
    if db_id:
        update_config_yaml(db_id)
        print(f"\n🎉 全部完成!")
        print(f"\n下一步:")
        print(f"1. 在 Notion 中找到这个数据库")
        print(f"2. 点击右上角 '...' → 'Connections' → 添加你的 Integration")
        print(f"3. 推送代码到 GitHub，配置 NOTION_API_KEY secret")
