#!/usr/bin/env python3
"""
GitHub Trending Daily Collector
每天抓取 GitHub Trending，生成 md 文件，推送到仓库
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

# 配置
REPO_DIR = Path.home() / "github-trending-daily"
CONTENT_DIR = REPO_DIR / "content"
SEEN_FILE = Path.home() / ".hermes" / "cron" / "github-trending-seen.json"
GITHUB_TRENDING_URL = "https://github.com/trending"
PROXY = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}

def load_seen():
    """加载已推送的项目记录"""
    if SEEN_FILE.exists():
        with open(SEEN_FILE) as f:
            data = json.load(f)
            return data.get("seen", [])
    return []

def save_seen(seen_list):
    """保存已推送的项目记录"""
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SEEN_FILE, "w") as f:
        json.dump({"seen": seen_list, "last_update": datetime.now().strftime("%Y-%m-%d")}, f, indent=2)

def clean_old_seen(seen_list, days=7):
    """清理超过指定天数的旧记录"""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return [item for item in seen_list if item["date"] >= cutoff]

def fetch_trending():
    """抓取 GitHub Trending 页面"""
    try:
        # 使用 web_extract 抓取
        from hermes_tools import web_extract
        result = web_extract([GITHUB_TRENDING_URL])
        if result and "results" in result:
            content = result["results"][0].get("content", "")
            return parse_trending(content)
    except Exception as e:
        print(f"web_extract failed: {e}")
    
    # 备用方案：直接 requests
    try:
        resp = requests.get(GITHUB_TRENDING_URL, proxies=PROXY, timeout=30)
        resp.raise_for_status()
        return parse_trending_html(resp.text)
    except Exception as e:
        print(f"requests failed: {e}")
        return []

def parse_trending(content):
    """从 markdown 内容解析 trending 项目"""
    projects = []
    lines = content.split("\n")
    
    current_project = None
    for line in lines:
        # 匹配项目名（通常是链接格式）
        match = re.search(r'\[([^\]]+)\]\((https://github\.com/[^)]+)\)', line)
        if match:
            name = match.group(1).strip()
            url = match.group(2).strip()
            
            # 提取 owner/repo
            repo_match = re.search(r'github\.com/([^/]+/[^/]+)', url)
            if repo_match:
                repo = repo_match.group(1)
                if current_project:
                    projects.append(current_project)
                current_project = {
                    "name": name,
                    "repo": repo,
                    "url": url,
                    "desc": "",
                    "stars": "",
                    "today": "",
                    "lang": ""
                }
        
        # 提取描述
        if current_project and not current_project["desc"]:
            if line.strip() and not line.startswith("#") and not line.startswith("["):
                current_project["desc"] = line.strip()[:200]
        
        # 提取 star 数
        star_match = re.search(r'(\d+[\d,]*)\s*stars?', line, re.IGNORECASE)
        if star_match and current_project:
            current_project["stars"] = star_match.group(1)
        
        # 提取今日新增
        today_match = re.search(r'([+-]?\d+[\d,]*)\s*(?:stars?\s*)?today', line, re.IGNORECASE)
        if today_match and current_project:
            current_project["today"] = today_match.group(1)
    
    if current_project:
        projects.append(current_project)
    
    return projects

def parse_trending_html(html):
    """从 HTML 解析 trending 项目"""
    projects = []
    
    # 使用正则解析 HTML
    articles = re.findall(r'<article class="Box-row">(.*?)</article>', html, re.DOTALL)
    
    for article in articles:
        # 提取项目名
        name_match = re.search(r'<h2[^>]*>\s*<a[^>]*href="(/[^"]+)"[^>]*>(.*?)</a>', article, re.DOTALL)
        if not name_match:
            continue
        
        href = name_match.group(1).strip()
        name = re.sub(r'<[^>]+>', '', name_match.group(2)).strip()
        name = re.sub(r'\s+', '', name)  # 移除空白
        
        # 提取描述
        desc_match = re.search(r'<p class="col-[^"]*">(.*?)</p>', article, re.DOTALL)
        desc = ""
        if desc_match:
            desc = re.sub(r'<[^>]+>', '', desc_match.group(1)).strip()
        
        # 提取 star 数
        stars_match = re.search(r'href="' + re.escape(href) + r'/stargazers"[^>]*>\s*(\d+[\d,]*)', article)
        stars = stars_match.group(1) if stars_match else ""
        
        # 提取今日新增
        today_match = re.search(r'(\d+[\d,]*)\s*stars?\s*today', article)
        today = today_match.group(1) if today_match else ""
        
        # 提取语言
        lang_match = re.search(r'itemprop="programmingLanguage"[^>]*>(.*?)<', article)
        lang = lang_match.group(1).strip() if lang_match else ""
        
        projects.append({
            "name": name.split("/")[-1] if "/" in name else name,
            "repo": href.lstrip("/"),
            "url": f"https://github.com{href}",
            "desc": desc,
            "stars": stars,
            "today": today,
            "lang": lang
        })
    
    return projects

def filter_projects(projects, seen_repos, limit=10):
    """筛选项目：去重 + 排序"""
    # 去重
    filtered = [p for p in projects if p["repo"] not in seen_repos]
    
    # 按今日新增排序（如果有）
    def sort_key(p):
        today = p.get("today", "0")
        today = re.sub(r'[^0-9]', '', today)
        return int(today) if today else 0
    
    filtered.sort(key=sort_key, reverse=True)
    
    # 取前 limit 个
    return filtered[:limit]

def generate_markdown(projects, date_str):
    """生成 markdown 内容"""
    lines = []
    lines.append(f"# 🔥 GitHub Trending Daily | {date_str}")
    lines.append("")
    lines.append(f"> 自动抓取于 {datetime.now().strftime('%Y-%m-%d %H:%M')}，共 {len(projects)} 个项目")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    for i, p in enumerate(projects, 1):
        lines.append(f"## {i}. [{p['name']}]({p['url']})")
        lines.append("")
        
        if p['desc']:
            lines.append(f"📌 {p['desc']}")
            lines.append("")
        
        stats = []
        if p['stars']:
            stats.append(f"⭐ {p['stars']}")
        if p['today']:
            stats.append(f"📈 +{p['today']} today")
        if p['lang']:
            stats.append(f"💻 {p['lang']}")
        
        if stats:
            lines.append(" | ".join(stats))
            lines.append("")
        
        lines.append("---")
        lines.append("")
    
    lines.append("*由 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 自动生成*")
    
    return "\n".join(lines)

def push_to_repo(date_str, content):
    """推送到 GitHub 仓库"""
    md_file = CONTENT_DIR / f"{date_str}.md"
    md_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(md_file, "w") as f:
        f.write(content)
    
    # 更新 README.md 中的最新一期链接
    update_readme(date_str)
    
    # git add, commit, push
    os.chdir(REPO_DIR)
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-m", f"📅 {date_str} 期更新"], check=True)
    subprocess.run(["git", "push", "origin", "master"], check=True)
    
    return True

def update_readme(date_str):
    """更新 README.md 中的最新一期链接"""
    readme = REPO_DIR / "README.md"
    if not readme.exists():
        return
    
    with open(readme) as f:
        content = f.read()
    
    # 在 ## 📅 更新频率 后面添加最新一期
    pattern = r'(## 📅 更新频率\n\n每天早上 10:00（北京时间）自动更新。)'
    replacement = f'\\1\n\n**最新一期：** [{date_str}](content/{date_str}.md)'
    
    new_content = re.sub(pattern, replacement, content)
    
    with open(readme, "w") as f:
        f.write(new_content)

def main():
    """主函数"""
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"📅 开始抓取 {today} 的 GitHub Trending...")
    
    # 加载已推送记录
    seen = load_seen()
    seen = clean_old_seen(seen, days=7)
    seen_repos = {item["repo"] for item in seen}
    
    print(f"📊 已推送 {len(seen_repos)} 个项目（7天内）")
    
    # 抓取 trending
    projects = fetch_trending()
    print(f"🔍 抓取到 {len(projects)} 个项目")
    
    if not projects:
        print("❌ 没有抓取到项目，退出")
        sys.exit(1)
    
    # 筛选项目
    selected = filter_projects(projects, seen_repos, limit=10)
    print(f"✅ 筛选出 {len(selected)} 个项目")
    
    if not selected:
        print("⚠️ 没有新项目（全部已推送），退出")
        sys.exit(0)
    
    # 生成 markdown
    content = generate_markdown(selected, today)
    
    # 推送到仓库
    try:
        push_to_repo(today, content)
        print(f"✅ 已推送到仓库")
    except Exception as e:
        print(f"❌ 推送失败: {e}")
        sys.exit(1)
    
    # 更新已推送记录
    for p in selected:
        seen.append({"repo": p["repo"], "date": today})
    save_seen(seen)
    
    print(f"🎉 完成！已更新 {len(selected)} 个项目")
    
    # 输出摘要
    print("\n📋 本期项目：")
    for i, p in enumerate(selected, 1):
        print(f"{i}. {p['name']} - {p['desc'][:50]}...")

if __name__ == "__main__":
    main()
