# datahub/sqlite/ —— 包内数据位置说明

> 更新：2026-09-11（v7.3.0）；数字校订：2026-09-28

## 结论：本目录当前**故意为空**

2026-09-09 起，公文数据库族统一收归外置数据根：

```
<数据根>/
├── gongwen_corpus.db      749.6MB  求是+地方+jhsjk+lilun+公报 合并主库（49 表）
├── qs_index.pkl             569MB  TF-IDF + BM25 索引
├── qs_vectors.npy / .json    64MB  bge 向量（hybrid3 第三路）
├── qs_statements.json        10MB  论断库
└── corpus_jinyu_full.md       9MB  金句库全量
```

**v7.3.0 已删除此前的 `qs_articles.db` 与 `hs/hs.db` 两个 0 字节占位文件** ——
它们让消费方"看起来有库、实际是空"，导致地方检索静默失效、重建写进空壳、
快照备份空白、自检误报降级。空占位比没有文件更危险，故一并移除。

数据根由 `datahub/paths.py` 统一解析（唯一事实源），顺序为：

1. 环境变量 `GONGWEN_DATA_ROOT`
2. `datahub/assets.json` 的 `data_root` 字段
3. 内置默认（即上表 <数据根>）
4. **回退本目录**（`sqlite/gongwen_corpus.db` 或 `sqlite/qs_articles.db`）

自检：`python datahub/paths.py` 或 `python gongwen_tool.py paths`

## 何时往本目录放数据（形态 B：数据随包）

只在需要**真 standalone 分发**（数据随包走、不依赖 <数据根>）时才放：

```bash
# 方式一：从外部数据目录复制（自动落到解析器期望的位置）
python bootstrap_data.py --from <含 gongwen_corpus.db 的目录>

# 方式二：手工放置（文件名须与 paths.py 的包内候选一致）
#   datahub/sqlite/gongwen_corpus.db      或  datahub/sqlite/qs_articles.db
#   datahub/derived/qs_index.pkl
#   datahub/derived/qs_vectors.npy + qs_vectors.json
#   datahub/derived/qs_statements.json
#   datahub/derived/corpus_jinyu_full.md
```

放置后 `resolve_form()` 会返回 `B`，`verify_install.py` 会如实报告。

## 历史说明（已过时，仅存档）

- `已迁移至_<数据根>_gongwen.md` —— 2026-09-09 迁移时点说明
- `hs/MOVED_已平级化至_sqlite_hs.db.md` —— 更早的地方两库合一说明

这两份记录的是历次布局变更，**不代表当前有效路径**。当前路径一律以
`datahub/paths.py` 的解析结果为准。

## 语料版权红线

求是 / 红旗文稿语料**仅限个人使用，禁止再分发**。对外分发一律走数据/代码分离：
代码 Apache-2.0，语料用户自备（`bootstrap_data.py --from` 或 `--crawl`）。
