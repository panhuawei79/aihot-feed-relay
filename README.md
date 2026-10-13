# AIHOT 境外信源中转(GitHub Actions 方案)

服务器在境内,4 个境外信源直连被墙。本仓库在 GitHub Actions 的境外 runner 上定时抓取,
结果提交到本仓库 `data/feeds.json`;内网服务器再用 `api.github.com`(境内可达)拉回,
经 AIHOT 的 `/api/ingest/items` 推进入库,走标准判重/精选/聚簇管线。

## 组成

| 文件 | 运行位置 | 作用 |
|---|---|---|
| `feeds.json` | — | 中转信源清单(sourceId 与 AIHOT 内信源一致,保证聚簇时来源归属正确) |
| `fetch.py` | GitHub Actions | 抓取+解析 RSS/Atom(纯标准库),写 `data/feeds.json` |
| `.github/workflows/fetch.yml` | GitHub Actions | 每 30 分钟跑一次,有变化就提交 |
| `server-pull.py` | 10.5.105.94 | 从 api.github.com 拉回数据,按 seen 去重后推送 AIHOT |

## 部署步骤

1. **建仓库**(public,Actions 免费额度无限;数据只是公开新闻,不含任何密钥):
   ```bash
   gh repo create aihot-feed-relay --public --source=. --push
   ```
   (或网页新建后 `git push`)
2. **手动触发一次**:Actions → fetch-overseas-feeds → Run workflow,确认 `data/feeds.json` 生成。
3. **服务器侧**:`server-pull.py` 已放在 `/home/ninebot/aihot-relay/`,把其中 `REPO` 改成实际仓库名后:
   ```bash
   python3 /home/ninebot/aihot-relay/server-pull.py --dry-run   # 先看会推什么
   crontab -e  # 加一行,每 30 分钟拉一次:
   */30 * * * * /usr/bin/python3 /home/ninebot/aihot-relay/server-pull.py >> /home/ninebot/aihot-relay/pull.log 2>&1
   ```
4. **验证**:AIHOT 后台 → 运行记录,或查库:
   ```sql
   select source_id, count(*) from materials where created_at > now() - interval '1 hour' group by 1;
   ```

## 增删信源

改 `feeds.json`(加一条 sourceId/url),push 即可,两边脚本自动跟进。
sourceId 建议与 AIHOT `sources` 表中的 id 保持一致;新 id 会由 ingest 自动建源。
