#!/usr/bin/env python3
"""部署在内网服务器(10.5.105.94)上:从 GitHub API 拉回中转数据,推入 AIHOT。
- 数据源:api.github.com 的仓库 contents 接口(境内可达,无需代理)
- 去重:本地 seen 文件记录已推送 URL,只推新增
- 推送:每个信源一次 POST /api/ingest/items,Bearer INGEST_TOKEN
用法: python3 server-pull.py [--repo owner/repo] [--dry-run]
cron(每 30 分钟):由部署脚本写入 crontab。
"""
import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

REPO = "OWNER/REPO"  # 部署时替换为实际仓库名
SEEN_FILE = Path("/home/ninebot/.relay-seen.json")
SEEN_MAX = 5000
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # 可选,提升 API 限额
SITE = "http://127.0.0.1:3000"


def gh_contents(path: str) -> dict:
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "aihot-relay"})
    if GITHUB_TOKEN:
        req.add_header("Authorization", "Bearer " + GITHUB_TOKEN)
    with urllib.request.urlopen(req, timeout=30) as r:
        meta = json.loads(r.read().decode())
    if meta.get("encoding") != "base64":
        raise RuntimeError("unexpected encoding: " + str(meta.get("encoding")))
    return json.loads(base64.b64decode(meta["content"]))


def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except Exception:
            pass
    return set()


def push(source_id, source_name, items):
    token = None
    for line in open("/home/ninebot/aihot/.env"):
        if line.startswith("INGEST_TOKEN="):
            token = line.strip().split("=", 1)[1]
    if not token:
        raise RuntimeError("INGEST_TOKEN 未配置")
    body = {"sourceId": source_id, "sourceName": source_name, "items": items[:50]}
    req = urllib.request.Request(SITE + "/api/ingest/items",
                                 data=json.dumps(body, ensure_ascii=False).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=30) as r:
        return len(items), r.read().decode()[:120]


def main() -> int:
    dry = "--dry-run" in sys.argv
    try:
        data = gh_contents("data/feeds.json")
    except urllib.error.HTTPError as e:
        print(f"拉取失败 HTTP {e.code}(仓库不存在或未产生数据?)")
        return 1
    seen = load_seen()
    total_new = 0
    for sid, feed in data["feeds"].items():
        fresh = [it for it in feed["items"]
                 if it.get("title") and it.get("url") and it["url"] not in seen]
        if not fresh:
            print(f"  {sid}: 无新增")
            continue
        for it in fresh:
            seen.add(it["url"])
        if dry:
            print(f"  {sid}: [dry-run] {len(fresh)} 条待推")
            for it in fresh[:5]:
                print("   -", it["title"][:80])
        else:
            n, resp = push(sid, feed.get("sourceName") or sid, fresh)
            total_new += n
            print(f"  {sid}: 推送 {n} 条 {resp}")
    if not dry and total_new:
        SEEN_FILE.write_text(json.dumps(list(seen)[-SEEN_MAX:]))
    print(f"完成,本轮共推送 {total_new} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
