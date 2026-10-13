#!/usr/bin/env python3
"""境外 RSS 中转抓取器:在 GitHub Actions(境外 runner)上运行。
读取 feeds.json,抓取每个源,解析 RSS/Atom,把条目写入 data/feeds.json。
只用标准库,兼容 RSS 2.0 与 Atom。失败的单个源跳过,不影响其他源。
"""
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (compatible; aihot-relay/1.0)"


def fetch(url, timeout=30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def as_utc(ts):
    if not ts:
        return None
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(ts)
    except Exception:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def text_of(el, *names):
    for child in el:
        if strip_ns(child.tag) in names:
            return (child.text or "").strip() or None
    return None


def link_of(el):
    for child in el:
        tag = strip_ns(child.tag)
        if tag == "link":
            rel = child.attrib.get("rel")
            if rel in (None, "alternate"):
                return (child.text or child.attrib.get("href") or "").strip() or None
    return None


def parse_feed(raw: bytes) -> list:
    root = ET.fromstring(raw)
    root_tag = strip_ns(root.tag)
    entries = []

    def handle(entry_tags, title_tags, date_tags, author_tags):
        for el in root.iter():
            if strip_ns(el.tag) not in entry_tags:
                continue
            title = text_of(el, *title_tags)
            link = link_of(el) or text_of(el, "link", "guid", "id")
            entries.append({
                "title": title,
                "url": link,
                "publishedAt": as_utc(text_of(el, *date_tags)),
                "author": text_of(el, *author_tags),
            })

    if root_tag == "rss":  # RSS 2.0:<rss><channel><item>
        for channel in root.iter():
            if strip_ns(channel.tag) == "channel":
                for item in channel:
                    if strip_ns(item.tag) == "item":
                        entries.append({
                            "title": text_of(item, "title"),
                            "url": text_of(item, "link") or text_of(item, "guid"),
                            "publishedAt": as_utc(text_of(item, "pubDate", "date")),
                            "author": text_of(item, "author", "creator", "dc:creator"),
                        })
    elif root_tag == "feed":  # Atom:<feed><entry>
        handle({"entry"}, {"title"}, {"published", "updated"}, {"author", "name"})
    else:
        raise ValueError(f"unsupported feed root: {root_tag}")

    return [e for e in entries if e["title"] and e["url"]]


def main() -> int:
    cfg = json.loads((ROOT / "feeds.json").read_text(encoding="utf-8"))
    out = {"fetchedAt": datetime.now(timezone.utc).isoformat(), "feeds": {}}
    failures = []
    for feed in cfg["feeds"]:
        sid = feed["sourceId"]
        try:
            items = parse_feed(fetch(feed["url"]))[: feed.get("maxItems", 25)]
            out["feeds"][sid] = {
                "sourceName": feed["sourceName"],
                "originUrl": feed["url"],
                "items": items,
            }
            print(f"ok   {sid}: {len(items)} items")
        except Exception as exc:
            failures.append(sid)
            print(f"fail {sid}: {exc}", file=sys.stderr)
    data = ROOT / "data"
    data.mkdir(exist_ok=True)
    (data / "feeds.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    # 全部失败视为 job 失败,保留上一版 data(由 Actions 的 git diff 逻辑保证不覆盖已提交版本)
    return 1 if len(failures) == len(cfg["feeds"]) else 0


if __name__ == "__main__":
    sys.exit(main())
