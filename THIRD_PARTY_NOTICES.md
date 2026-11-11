# 第三方组件与数据来源声明

本仓库聚合或引用了下列第三方开源组件与外部数据。各自遵循其原始许可证，本项目的 Apache-2.0 不覆盖第三方内容。

## 一、本仓库自身许可

| 项目 | 说明 |
|---|---|
| 公文大师（gongwen-master 及 govdoc-\* / shuji / qiushi-db / article-review 等模块） | Apache License 2.0，Copyright 2026 Gongwen Master Contributors |

## 二、第三方开源组件

| 组件 | 用途 | 许可证 |
|---|---|---|
| jieba | 中文分词 | MIT |
| numpy | 数值计算 | BSD-3-Clause |
| scikit-learn | TF-IDF 向量化与相似度 | BSD-3-Clause |
| rank-bm25 | BM25 关键词检索 | Apache-2.0 |
| sentence-transformers | 句向量推理（可选） | Apache-2.0 |
| BAAI/bge-small-zh-v1.5 | 中文语义嵌入模型（可选，不随仓库分发） | MIT |
| sqlite3（Python 标准库） | 数据存储 | PSF License |

安装方式：`pip install -r requirements.txt`。向量检索需另行下载 bge 模型，见 `datahub/scripts/qs/embed_qiushi_vec.py` 头部说明。

## 三、随仓库分发的数据

| 数据 | 位置 | 体量 | 来源 | 权利状态 |
|---|---|---|---|---|
| 国务院公报 | `datahub/sqlite/gongwen_corpus.db.gz` → `articles` | 14,863 篇 | 中国政府网国务院公报栏目 | 行政性质文件，不适用著作权保护；保留 `url` 与 `source` 字段 |
| 国家法律法规 | 同上 | 50 篇 | 国家法律法规数据库 | 官方文本 |
| 中央部委政策 | 同上 | 20 篇 | 中央部委官网 | 行政性质文件 |

## 四、明确不随仓库分发的内容

以下语料曾在项目内部使用，因版权原因**不纳入本仓库**，也不在 Apache-2.0 授权范围内：

- 理论刊物文章（含《求是》《红旗文稿》等）及其摘编、金句提取物
- 报纸与通讯社报道
- 图书原文及其章节切分
- 地方统计年鉴、地方机构名录与地方政务文本
- 第三方敏感词表的原始词库

需要上述语料的，请自行取得授权后通过 `GONGWEN_DATA_ROOT` 接入，责任由接入方承担。详见 [DATA_LICENSE.md](DATA_LICENSE.md)。

## 五、自行整理的词表

| 词表 | 位置 | 权利状态 |
|---|---|---|
| 易混词对照表（4,272 组） | `references/govdoc-polish/references/govdoc-qc/dictionaries/merged/confusion_words_all.txt` | 本项目整理，Apache-2.0 |

第三方敏感词原始词库已移除。质检脚本在词库缺失时自动跳过该项检查，不影响其余功能。

## 六、致谢

版式设计思路参考了开源项目 official-document-drafting 的公开实现。本项目自 v7.1 起为独立重写，仓库内不含其代码，此处仅作学术致谢。
