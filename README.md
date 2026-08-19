# 📰 RSS to Notion 自动推送

> 完全免费、自动化的 RSS 订阅推送服务。把任意 RSS 源的内容自动推送到你的 Notion 数据库。

基于 **GitHub Actions** 定时运行，**无需服务器，零成本**。

---

## ✨ 特性

| 特性 | 说明 |
|------|------|
| ✅ 完全免费 | GitHub Actions 每月 2000 分钟免费额度 |
| ✅ 任意 RSS | 想订阅什么就订阅什么，支持无数个源 |
| ✅ 智能去重 | 基于链接 MD5 指纹，7 天内不重复推送 |
| ✅ 富文本页面 | 在 Notion 中显示摘要、书签、元信息 |
| ✅ 可选 AI 摘要 | 用免费 API 给每条内容生成一句话总结 |
| ✅ 状态持久 | 推送记录自动保存，跨次运行不丢失 |

---

## 🚀 5 分钟上手

### 前置要求

- GitHub 账号（免费）
- Notion 账号（免费）
- 一个你想订阅的 RSS 源（已内置福利吧示例）

---

### 第 1 步：创建 Notion Integration

1. 打开 https://www.notion.so/my-integrations
2. 点击 **"+ New integration"**
3. 填写名称：`RSS Bot`
4. 选择关联的工作区
5. 复制 **Internal Integration Token**（以 `secret_` 开头）

> ⚠️ **不要泄露这个 Token！**

---

### 第 2 步：创建 Notion 数据库（两种方式）

#### 方式 A：自动创建（推荐）⭐

克隆本仓库后运行初始化脚本：

```bash
git clone https://github.com/YOUR_NAME/rss-to-notion.git
cd rss-to-notion
pip install -r requirements.txt

export NOTION_API_KEY="secret_你的Token"
python setup_notion.py
```

脚本会自动创建数据库，并更新 `config.yaml`。

**注意**：运行前需要先在 Notion 中将 Integration 添加到你的工作区：
- 打开 Notion → 左下角 Settings → Connections → 添加你的 Integration

#### 方式 B：手动创建

1. 在 Notion 中新建一个 **Database - Full page**
2. 添加以下字段：

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `Title` | Title | 文章标题（必填） |
| `URL` | URL | 原文链接 |
| `Source` | Text | 来源名称 |
| `Published` | Date | 发布时间 |
| `AI Summary` | Text | AI 摘要（可选） |
| `Tags` | Multi-select | 标签（可选） |

3. 点击右上角 **"..." → "Connections"** → 添加你的 Integration
4. 复制浏览器地址栏中的数据库 ID：
   ```
   https://www.notion.so/xxx/DATABASE_ID?v=xxx
                                   ^^^^^^^^^^^^ 这就是
   ```
5. 编辑 `config.yaml`，填入 `database_id`

---

### 第 3 步：配置 RSS 源

编辑 `config.yaml`：

```yaml
rss_sources:
  fuliba:
    name: "福利吧"
    url: "https://fuliba2023.net/feed"
    enabled: true

  # 添加更多源：
  # hackernews:
  #   name: "Hacker News"
  #   url: "https://hnrss.org/frontpage"
  #   enabled: true

  # v2ex:
  #   name: "V2EX"
  #   url: "https://www.v2ex.com/index.xml"
  #   enabled: true

  # 少数派:
  #   name: "少数派"
  #   url: "https://sspai.com/feed"
  #   enabled: true

  # Readhub:
  #   name: "Readhub"
  #   url: "https://readhub.cn/topic/rss"
  #   enabled: true
```

> 💡 想订阅任何网站？先看看 https://rsshub-docs-mirror.github.io/ — 很多网站都能通过 RSSHub 生成 RSS！

---

### 第 4 步：推送到 GitHub

```bash
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/YOUR_NAME/rss-to-notion.git
git push -u origin main
```

---

### 第 5 步：配置 GitHub Secret

1. 进入 GitHub 仓库 → **Settings → Secrets → Actions**
2. 点击 **"New repository secret"**
3. Name: `NOTION_API_KEY`
4. Value: 你的 Notion Integration Token

---

### 🎉 完成！

GitHub Actions 会自动每 2 小时运行一次，抓取新内容推送到 Notion。

你也可以手动触发：**Actions → RSS to Notion → Run workflow**

---

## ⚙️ 配置选项

### 修改推送频率

编辑 `.github/workflows/rss-sync.yml`：

```yaml
# 每 30 分钟
- cron: "*/30 * * * *"

# 每 1 小时
- cron: "0 * * * *"

# 每天早 8 点
- cron: "0 8 * * *"
```

> [Crontab Guru](https://crontab.guru/) 帮你写 cron 表达式

### 启用 AI 摘要（可选）

编辑 `config.yaml`：

```yaml
ai:
  enabled: true
  api_key: "你的API Key"
  api_url: "https://api.deepseek.com/v1/chat/completions"
  model: "deepseek-chat"
```

**免费 API 推荐**：

| 提供商 | API URL | 模型 | 免费额度 |
|--------|---------|------|----------|
| DeepSeek | `https://api.deepseek.com/v1/chat/completions` | `deepseek-chat` | 免费 |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` | `qwen-turbo` | 免费 |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4/chat/completions` | `glm-4-flash` | 免费 |
| Google Gemini | 需特殊配置 | `gemini-1.5-flash` | 免费 |

> 在 GitHub Secrets 中添加 `AI_API_KEY` 即可

---

## 🆓 成本

| 服务 | 免费额度 | 实际消耗 |
|------|----------|----------|
| GitHub Actions | 2000 分钟/月 | ~20 分钟/月 |
| Notion API | 无限 | 可忽略 |
| RSS 抓取 | 零 | 零 |

> 即使每天推送 24 次，每月也只用 ~120 分钟，完全在免费额度内。

---

## 📂 项目结构

```
rss-to-notion/
├── .github/workflows/rss-sync.yml   ← GitHub Actions 定时任务
├── .gitignore
├── README.md                        ← 你正在看的文件
├── config.yaml                      ← RSS 源 + Notion 配置
├── requirements.txt                 ← 依赖
├── rss_to_notion.py                 ← 核心推送脚本
└── setup_notion.py                  ← Notion 数据库自动创建
```

---

## 🛠️ 本地测试

```bash
pip install -r requirements.txt

# 仅测试 RSS 抓取
NOTION_API_KEY=dummy python -c "
import feedparser
feed = feedparser.parse('https://fuliba2023.net/feed')
print(f'标题: {feed.feed.get(\"title\")}')
print(f'条目数: {len(feed.entries)}')
for e in feed.entries[:3]:
    print(f'  - {e.title}')
"

# 完整运行（需要有效的 NOTION_API_KEY）
NOTION_API_KEY=secret_xxx python rss_to_notion.py
```

---

## ❓ FAQ

**Q: 会重复推送吗？**
A: 不会。基于链接 MD5 去重，7 天内相同链接只推一次。

**Q: 可以推送到已有页面吗？**
A: 当前推送到数据库（Database）。如需推送到普通页面，需改代码。

**Q: 推送频率最高多少？**
A: GitHub Actions 最短间隔 5 分钟。

**Q: 某些网站没有 RSS 怎么办？**
A: 使用 RSSHub 生成：https://rsshub-docs-mirror.github.io/

**Q: 数据库字段名称可以自定义吗？**
A: 可以，但脚本中硬编码了 `Title`, `URL`, `Source`, `Published` 等字段名。修改 `create_notion_page()` 函数即可适配。

---

## 📄 License

MIT
