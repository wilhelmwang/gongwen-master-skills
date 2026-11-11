# datahub 数据规范（v1.0 · 2026-09-08）

## 一、数据库清单

| 库 | 路径 | 定位 |
|---|---|---|
| qs_articles.db | **<数据根>/**（2026-09-09 迁移，快照留源包） | 主库：求是/红旗/求是网/任仲平/贺词文章 |
| hs.db | **<数据根>/**（已并入 gongwen_corpus.db，快照留源包） | 地方特色库 |
| jhsjk.db | 002/45（原件）→ 已并入 gongwen_corpus.db（<数据根>） | 人民网领袖人物库——引用源 |
| lilun.db | 002/45（跨工程，见 assets.json） | 思想理论书籍库——书籍蒸馏源 |

## 二、articles 表字段规范（13+6 列）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| id | INTEGER PK 自增 | 系统 | |
| title | TEXT | ✅ | 标题（去重键之一） |
| author | TEXT | ✅ | 作者/署名（个人名/评论员/编辑部） |
| source | TEXT | ✅ | 来源刊（求是/红旗文稿/求是网/人民日报-任仲平/新年贺词…） |
| publish_date | TEXT | ✅ | **ISO 日期 YYYY-MM-DD**（期次号不入此列） |
| issue_year | INTEGER | 期次年份（杂志文） | |
| issue_num | INTEGER | 期次号（杂志文） | |
| url | TEXT | 推荐 | 原文链接（**URL 去重键**） |
| content | TEXT | ✅ | 正文全文（UTF-8） |
| keywords | TEXT | 可空 | |
| word_count | INTEGER | ✅ | 字数 |
| crawl_time | TEXT | ✅ | 采集时间 YYYY-MM-DD |
| data_source | TEXT | ✅ | 采集批次标记（求是杂志/求是网采集/任仲平专项采集/贺词采集） |
| genre/topic/level/arg_style/field/paradigm | TEXT | 可空 | 六维分类标签（回填自分类语料） |

## 三、命名与类型规范

1. **编码**：全部 UTF-8（SQLite TEXT / JSON / MD）。
2. **日期**：一律 `YYYY-MM-DD`；期次号独立 `issue_year/issue_num`，不与日期混存。
3. **JSONL 语料文件**：每目录附 `schema.json`；字段命名遵循本表（**date → publish_date**）。
4. **去重**：入库前按 `url` 查重（idx_articles_url 索引）；无 url 的按 title 精确匹配。
5. **纯扫描标记**：lilun.db `scan_only=1` 的 1,852 册无文本，蒸馏跳过。
6. **两套分类法适用域**：
   - 书籍分类（lilun.db category，20 类）：经济与管理/政治与社会治理/马恩著作…
   - 文章分类（articles topic，8-10 箱）：政治理论与主题教育/经济与高质量发展/民生与社会治理…
   - 两者不通用，蒸馏时按对象选表。

## 四、jhsjk.db / lilun.db 引用方式

- 位置：`<数据区>/002成果资产/45_思想理论语料库_IdeologyCorpus_v1.0.0/`
- 跨工程引用一律读 `datahub/assets.json` 的 `databases.jhsjk.path / databases.lilun.path`，不硬编码路径。
- jhsjk.db 含 FTS5 全文索引（jhsjk_fts）。


## 五、归档快照保留声明（2026-09-08 P2）

`datahub/backups*/` 与 `backups_removed_20260904_archived_to_002/` 下的 11 个历史库快照（snapshot_*/pre-migrate_*/merge-hs_*/qiushi.db 旧版等）**永久保留，不清理**：

1. 用途：数据可追溯（版本回滚/事故恢复/口径考古）；
2. 体积可控：全部位于归档区，不参与运行时加载；
3. 红线：`只增不删`——清理需用户明确指令。

**引用规则**：正式引用一律读 `datahub/sqlite/` 主库；快照仅供追溯，不参与检索。


## 六、合并库 jhsjk_fts 结构（2026-09-23 重建）

### 曾有的两个问题（均已修复）

**问题 1 · external content 指错表**：原 DDL 为 `content='articles'`（应为 `jhsjk_articles`）。
索引数据取自 jhsjk_articles，外部内容却从 articles 读，导致
`SELECT title FROM jhsjk_fts WHERE MATCH` 返回 articles 的标题，与命中 rowid 在
jhsjk_articles 里对应的文章**不是同一篇**（实测 rowid 176：fts 返回"新时代全面深化改革的重大成就"，
源表实为"习近平在河北雄安新区考察…"）。

**问题 2 · unicode61 对中文等于不分词**：原 `tokenize='unicode61'` 把连续汉字整段当作单个 token。
实测 `'生产力'` 命中 0 条、`'发展 AND 生产力'` 命中 0 条，只有整句短语才命中——
按关键词检索领袖语录因此不可用。

### 当前结构（jieba 分词物化，与 articles_fts 同构）

```sql
CREATE VIRTUAL TABLE jhsjk_fts USING fts5(
    jid UNINDEXED, title_t, body_t, tokenize='unicode61');
```

`title_t` / `body_t` 存 jieba 分词后的空格串，unicode61 再按空格切分即得词元；
检索词经 `tokenize()` 处理后直接作 MATCH 参数（参数绑定，无拼接）。
重建脚本：`datahub/scripts/qs/rebuild_jhsjk_fts.py`（55 秒 / 14,901 行，含校验）。

**实测效果**（修复后）：`'生产力'` 588 条、`'高质量发展'` 1,999 条、`'中国式现代化'` 735 条。

### 检索入口

```bash
python datahub/scripts/qs/search_jhsjk.py "新质生产力"          # 全文检索
python datahub/scripts/qs/search_jhsjk.py "中国式现代化" --year 2024
python datahub/scripts/qs/search_jhsjk.py --show 40756462      # 按 id 读全文
```

> ⚠️ 领袖著作**不在** qiushi_engine 的 `articles` 表内（该表 data_source 不含领袖域），
> hybrid3 检索查不到领袖语录，必须走上述入口。

注：articles_fts 亦为 jieba 分词物化结构（article_id/title_t/body_t），
增删 articles 行后需重跑 `rebuild_fts.py` 或走 `--incremental`。
