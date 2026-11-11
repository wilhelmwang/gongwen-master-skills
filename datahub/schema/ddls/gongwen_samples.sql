-- gongwen_samples.db（范文池分层库） 表结构 DDL（由 datahub/schema/gen_ddl.py 自实库导出）
-- 源库：gongwen_samples.db
-- 说明：三层设计：raw_pages 原始层（清洗前原文）/ samples 治理层（按当前判据重算）/ review_state 审核台账。JSONL（govdoc_samples/collected.jsonl）为唯一事实源，本库为派生物，可整库重建。
-- 本文件为**生成物**：schema 变更后请重跑 gen_ddl.py，并同步 schema-registry.json / assets.json。

-- ============ 表 ============
CREATE TABLE quality_det (
  url TEXT NOT NULL,
  rule_ver TEXT NOT NULL,
  struct INTEGER NOT NULL,
  clean INTEGER NOT NULL,
  fmt INTEGER NOT NULL,
  verdict TEXT,
  veto TEXT,
  evidence_json TEXT,
  batch_id TEXT,
  scored_at TEXT,
  PRIMARY KEY (url, rule_ver)
);

CREATE TABLE quality_llm (
  url TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  tili INTEGER, neirong INTEGER, yuyan INTEGER, wanzheng INTEGER, jiazhi INTEGER,
  tier TEXT NOT NULL,
  need_full INTEGER DEFAULT 0,
  type_mismatch INTEGER DEFAULT 0,
  why TEXT,
  labeled_at TEXT,
  PRIMARY KEY (url, batch_id)
);

CREATE TABLE raw_pages (
         id INTEGER PRIMARY KEY,
         url TEXT NOT NULL UNIQUE,
         source_key TEXT,
         doc_type TEXT,
         fetched_at TEXT,
         raw_text TEXT NOT NULL,
         raw_sha256 TEXT,
         clean_version TEXT);

CREATE TABLE review_state (
         url TEXT PRIMARY KEY,
         batch_id TEXT,
         tier TEXT,
         scores_json TEXT,
         why TEXT,
         need_full INTEGER DEFAULT 0,
         reviewed_at TEXT,
         full_reviewed_at TEXT,
         reviewer TEXT, review_kind TEXT, payload_json TEXT);

CREATE TABLE samples (
         id INTEGER PRIMARY KEY,
         url TEXT NOT NULL UNIQUE,
         raw_ref INTEGER,
         title TEXT,
         doc_type TEXT,
         source_key TEXT,
         pub_date TEXT,
         content TEXT NOT NULL,
         chars INTEGER,
         skel TEXT,
         txt_hash TEXT,
         clean_version TEXT, dup_of TEXT, dup_kind TEXT);

CREATE VIRTUAL TABLE samples_fts USING fts5(title, content, content='samples', content_rowid='id', tokenize='trigram');

CREATE TABLE samples_meta (k TEXT PRIMARY KEY, v TEXT);

-- ============ 索引 ============
CREATE INDEX idx_qdet_ver_verdict ON quality_det(rule_ver, verdict);

CREATE INDEX idx_qllm_batch_tier ON quality_llm(batch_id, tier);

CREATE INDEX ix_samples_skel ON samples(skel);

CREATE INDEX ix_samples_type ON samples(doc_type, clean_version);

-- ============ 视图 ============