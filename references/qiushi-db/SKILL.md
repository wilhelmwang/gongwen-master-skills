---
name: qiushi-db
version: "1.2.0"
description: "当用户需要检索、引用政策文献（求是/红旗文稿/部委法规）或地方本地统计数据用于公文写作时使用我（v7.3.1 数据中枢：求是 hybrid3 五模式检索 + 论断库 31,315 条 + 金句 31,315 条 + 地方 hs_* 11 表 15,400 行带年鉴页码溯源）。触发词：引用求是、查求是、求是文章、红旗文稿、查地方数据、地区生产总值、地方统计、引用数据、防臆造。数据引用必须带来源，禁止编造。"
compatibility: "Designed for WorkBuddy/Claude/豆包等 agent 技能平台（standalone 包）；引擎脚本需 Python 3.10+ 与 requirements.txt 依赖（jieba/numpy/scikit-learn/rank-bm25）；数据层经 datahub/paths.py 解析（外置数据根优先，详见 requires）"
requires:
  engine: "datahub/scripts/qs/qiushi_engine.py"
  data: "经 datahub/paths.py 解析：合并主库 gongwen_corpus.db（求是+红旗+jhsjk+lilun+地方 四库合一）+ 派生 qs_index.pkl / qs_vectors.npy / qs_statements.json / corpus_jinyu_full.md。解析序 GONGWEN_DATA_ROOT → assets.json:data_root → 内置默认 → 包内 datahub/ 回退；形态 A 外置 / B 包内 / C 降级"
  deps: "jieba, numpy, scikit-learn, rank-bm25"
  env: "GONGWEN_BGE_MODEL（可选，hybrid3 向量路）"
permissions:
  fs_write: "只读数据层（rebuild 时例外，需显式执行）"
  network: "无"
  secrets: "无"
display_name: "公文·数据中枢（求是+地方）"
copyright: "Gongwen Master Contributors © Apache-2.0"
---

# 政策文献数据库 + 三级混合检索（接口说明）

## 角色定位

你是「政策文献数据库」检索接口。配套合并库文章域《求是》3,456 篇 + 《红旗文稿》2,073 篇 + 求是网 264 + 部委政策 188 + 法律法规 50 + 求是图书 17 + 任仲平 8 + 国务院公文 7 + 贺词 4 + 国务院公报 14,863（**`articles` 表共 20,931 篇 / 9,405 万字**）+ 论断库 31,315 条 + 金句 31,315 条。
**数据层路径统一经 `datahub/paths.py` 解析**（唯一事实源），不硬编码：

```bash
python datahub/paths.py     # 打印数据根 / 来源 / 形态（A 外置 / B 包内 / C 降级）
```

形态 A 走外置数据根（`<数据根>/gongwen_corpus.db`，749.6MB / 49 表（22 实体表 + 5 FTS 虚表）/ 约 18.0 万行（非阴影表））；
形态 B 走包内 `datahub/`；形态 C 为降级（检索与数据引用关闭，写作能力仍可用）。

## 检索能力（hybrid3 五模式）

| 层 | 引擎（`datahub/scripts/qs/`） | 原理 | 适用 |
|---|---|---|---|
| 词面 | qiushi_engine（tfidf / bm25 / hybrid） | TF-IDF + BM25，RRF 融合 | 精确关键词/术语 |
| 语义 | qiushi_engine（hybrid3 / vec） | 三路 RRF（词面 + bge 向量） | 自然语言/口语查询 |
| 派生 | statements（**去噪版 30,430 条** / db 原表 31,315 条）| 规则式论断聚类 | 引用权威说法速查 |
| 检索条目 | golden_quotes（31,315 条金句）| 四型：排比/号召/对仗/论断 | 写作时插句 |
| 综述 | review_generator.py（取去噪版论断库 + 剥离行尾图片署名）| 检索+论断+跨年汇编 | 定题权威说法手册 |
| **领袖语录** | `datahub/scripts/qs/search_jhsjk.py` | `jhsjk_articles` 14,901 篇 + `jhsjk_fts`（jieba 分词物化），2012-11~2026-09 | **引语原文**：查"总书记指出/强调"的准确表述与出处 |
| **政策原文** | `datahub/scripts/zc/search_zhengce.py` | 四库 trigram FTS（中央 550 / 国务院 5,998 / 部门 12,685 / 其他 8,119，共 **27,352 篇**） | **核依据**：查文号、查条款原文与目标数字 |

> ⚠️ **三条通道分工不同，不要混用**：主库（本技能词面/语义/派生层）是**写作引证**——学文风、取立意，
> 里面的权威期刊与国务院公报用来"像它那样写"；四库是**依据出处**——"这个提法出自哪份文、文号是多少、
> 原文原话怎么写"；领袖语录通道是**引语原文**——"总书记原话怎么说的、出自哪篇讲话"。
> 四库**刻意不并入 hybrid3**：混进来会让引文出处变成基层部门通知（与范文池不入检索同一条理由）。

> ⚠️ **领袖著作不在 hybrid3 内**：`articles` 表的 `data_source` 不含领袖域，故 qiushi_engine **查不到**领袖语录，
> 必须走 `search_jhsjk.py`。用法：
> ```bash
> python datahub/scripts/qs/search_jhsjk.py "新质生产力"              # 全文检索
> python datahub/scripts/qs/search_jhsjk.py "中国式现代化" --year 2024  # 限定年份
> python datahub/scripts/qs/search_jhsjk.py --show 40756462            # 按 id 读全文
> python datahub/scripts/qs/search_jhsjk.py --stats                     # 语料规模
> ```

> `mode` 可选：`hybrid3`（默认）/ `hybrid` / `tfidf` / `bm25` / `vec`。
> 快路：环境变量 `GONGWEN_FAST=1` 启用 FTS（毫秒级，缺表自动降级全量路）。

## 检索引擎（datahub/scripts/qs/ · 包根绝对调用）

```bash
# 主力引擎
python datahub/scripts/qs/qiushi_engine.py stats                 # 统计
python datahub/scripts/qs/qiushi_engine.py search "新质生产力"    # hybrid3 语义检索（默认）
python datahub/scripts/qs/qiushi_engine.py reindex               # 重建 TF-IDF 索引
# 语料工具
python datahub/scripts/qs/review_generator.py "人工智能治理"      # 综述手册
python datahub/scripts/qs/style_router.py "像发改委口吻写"         # 风格语义路由
# 政策原文核对（四库 27,352 篇；只读、无网络）
python datahub/scripts/zc/search_zhengce.py "高标准农田"                    # 跨四库检索
python datahub/scripts/zc/search_zhengce.py --lib gw,bm --per 10 --full    # 限定库 + 正文片段
python datahub/scripts/zc/search_zhengce.py --wenhao "国办发〔2019〕50号"   # **按文号查**
python datahub/scripts/zc/search_zhengce.py --show <url>                   # 打印全文（引用前必看）
python datahub/scripts/zc/search_zhengce.py --stats                        # 四库篇数/文号覆盖/时间跨度
```

```
from qiushi_engine import search_database
results = search_database("人工智能如何赋能实体经济", top_n=10, use_semantic=True)
# mode='hybrid' / 'tfidf' / 'bm25'
```

```bash
# L3 向量路（可选增强）：`qs_vectors.npy` 随数据根提供（外置根 64MB / 包内 derived 亦有副本）
#   启用条件：装 sentence-transformers 且**模型路径已登记**（`assets.json:bge_model`，配置驱动；
#   env GONGWEN_BGE_MODEL 仍可覆盖）。v7.5.0 前只有环境变量一条路，机器上模型在位却因"没人
#   export"长期静默降级——门禁量到的 98% 是那个降级态的成绩，开向量路后为 99%/MRR 0.974。
#   未配置时引擎显式告警并降级 TF-IDF+BM25 词面双路（检索仍可用，语义改写类查询精度下降）
#   ⚠️ 向量路覆盖求是系三源 5,761 篇（索引篇数 20,680，向量 32,847 块）；国务院公报 14,863 篇与政策四库 27,352 篇走词面路。
#   重建：python datahub/scripts/qs/embed_qiushi_vec.py（全量）/ embed_incremental.py（增量）
# R 精排（可选）：reranker_llm.py + datahub/eval/ab_rerank_hard.py，实测收益 ΔMRR ≤0.017 → 不做常驻
```

## 检索结果字段

- `title` / `author` / `source`（《求是》2024/09 等）/ `publish_date`
- `issue_year` / `issue_num` / `word_count` / `url` / `snippet` / `similarity`

## 引用规范

- 引用表述：标注"据《求是》XXXX年第X期《文章标题》"
- 引用数据：标注数据来源和期数
- 引用领导人文章：标注"习近平总书记在《求是》XXXX年第X期发表的《文章标题》中指出"
- **引用领袖讲话/语录**：先经 `search_jhsjk.py` 取原文，标注"据《人民日报》YYYY年M月D日《标题》"或
  "习近平总书记在《求是》XXXX年第X期《标题》中指出…"；**不得**简写为"习近平总书记曾指出"而无出处

### 引用时效性提示（v7.5.1 新增 · C4 轻量版）

**每条引用卡片必须带三项**：`来源日期` + `语料末次出现年份` + `核验提示`。

时效信息用一条命令查：

```bash
python datahub/scripts/qs/freshness.py --phrase-age "提法关键词"
# → 语料年份窗口 / 首见年份 / 末见年份 / 逐年频次 / 最近命中篇目 / 核验提示
```

**规则（只提示、不判定）**：

| 情形 | 卡片上怎么写 |
|---|---|
| 近 3 年内仍有出现 | 正常引用，附「近 N 年仍有出现（末见 XXXX 年）」 |
| 末次出现距今 ≥3 年 | 引用**照常保留**，但附：**"该提法最后一次出现在本语料 XXXX 年，建议核对是否有现行版本或新表述"** |
| 语料中未检出 | 附："本语料（XXXX-XXXX 年窗口）未检出；未检出 ≠ 已失效，可能是年份窗口外或措辞不同"——**不得写成"该提法已失效"** |

> ⚠️ **红线：只提示、不判定。** 本技能**不具备**判定"某政策是否现行有效"的能力。
> 错误标注"已失效"比不提示更危险——作者可能据此删掉正确引用。
> 时效提示只是**线索**，核验决定权始终在作者，且必须以官方原文为准。

> 注意语料年份窗口（当前 2017-2026）：更早年份的经典表述（如"三个代表重要思想"）
> 本就不在窗口内，查不到属正常，**不能据此认为已过时**。

## 使用示例

1. **写方案查依据**：先增量更新 → 语义检索"人工智能 产业发展" → 提取权威表述写入方案 → 标注来源
2. **查主题**："搜一下《求是》里关于新质生产力的文章" → 返回 top10（标题/作者/日期/相似度/摘要）
3. **引用领导人论述**：语义检索"数字经济"，筛选 author="习近平" → 返回全文与引用位置
4. **查提法时效**：`freshness.py --phrase-age "关键词"` → 末见年份与逐年趋势 → 按上表决定卡片附注

## 注意事项

- 检索返回相关文章，引用前需阅读全文确认表述
- 文章仅供学习参考，正式引用以求是网原文为准
- 完整数据：合并库 `articles` 表 20,931 篇（`data_source` 区分：求是/求是-转载/红旗文稿/求是图书/部委政策/法律法规/求是网/任仲平/国务院公文/贺词/国务院公报）；其中可检索 20,680 篇、空正文 175 篇（图表/法规栏目）
- **索引已对齐**（2026-09-21）：TF-IDF/BM25 索引 **20,680 篇 / 库可用 20,680 = 100%**；向量 32,847 块覆盖求是系 5,761 篇
- **内容改写检测**（v7.5.1）：`articles` 的 URL 判重无法发现"URL 不变而正文被改写"，改用哈希边车：`freshness.py --hash-verify`（或爬虫 `--check-rewrites N`）

---

## 第三方组件与许可
本 Skill 聚合或引用了若干第三方开源组件，它们各自遵循其原始许可证（非本文件 Apache-2.0），商业化再分发时须一并保留其许可与声明。完整清单见仓库根目录 `THIRD_PARTY_NOTICES.md`。

## 本地数据（开源版不提供）

本公开版**不随包分发任何地方统计数据库**，原地方数据底座（指标表、年鉴页索引、机构名录与职责表）已整体移出。

写作中如需引用地方数据，须由使用方自行接入数据源，并遵守两条底线：①每条数据标明出处与年份，未查到即如实说明「无此数据」，禁止编造；②跨年口径差异须先核对（如收入类指标的统计口径变化）。

