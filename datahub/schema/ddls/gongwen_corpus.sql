-- gongwen_corpus.db 表结构 DDL（由 datahub/schema/gen_ddl.py 自实库导出）
-- 源库：gongwen_corpus.db
-- 说明：合并库中地方业务表带 hs_ 前缀；其 FTS 虚表（pages_fts / pages_fts_jieba）不带前缀。
-- 本文件为**生成物**：schema 变更后请重跑 gen_ddl.py，并同步 schema-registry.json / assets.json。

-- ============ 表 ============
CREATE TABLE articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        author TEXT,
        source TEXT,
        publish_date TEXT,
        issue_year INTEGER,
        issue_num INTEGER,
        url TEXT UNIQUE,
        content TEXT,
        keywords TEXT,
        word_count INTEGER,
        crawl_time TEXT
    , data_source TEXT DEFAULT "求是杂志", genre TEXT, topic TEXT, level TEXT, arg_style TEXT, field TEXT, paradigm TEXT);

CREATE VIRTUAL TABLE articles_fts USING fts5(article_id UNINDEXED, title_t, body_t, tokenize='unicode61');

CREATE TABLE books24 (
        id INTEGER PRIMARY KEY,
        book TEXT, author TEXT, chapter_no INTEGER, chapter_title TEXT,
        content TEXT, chars INTEGER, source_path TEXT);

CREATE VIRTUAL TABLE books24_fts USING fts5(
        book, chapter_title, content, content='books24', content_rowid='id', tokenize='unicode61');

CREATE TABLE golden_quotes (
    id INTEGER PRIMARY KEY,
    type TEXT, quote TEXT, article TEXT, author TEXT, idx INTEGER);

CREATE TABLE hs_core_series (
    year INTEGER, topic TEXT, indicator TEXT,
    value REAL, unit TEXT, growth REAL, source TEXT,
    PRIMARY KEY (year, indicator)
);

CREATE TABLE hs_county_series (
    indicator TEXT, year INTEGER, region TEXT, value REAL, unit TEXT, source TEXT
);

CREATE TABLE hs_doc_sources (
    doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type TEXT,
    doc_name TEXT,
    file_path TEXT,
    year INTEGER,
    pages INTEGER,
    note TEXT
);

CREATE TABLE hs_facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year INTEGER, topic TEXT, indicator TEXT,
        value REAL, unit TEXT, growth REAL, source TEXT
    , page_num INTEGER, excerpt TEXT, doc_ref TEXT);

CREATE TABLE hs_forecast (
    indicator TEXT, unit TEXT, arima_order TEXT, base_year INTEGER, base_value REAL,
    fc1_year INTEGER, fc1_value REAL, fc2_year INTEGER, fc2_value REAL
);

CREATE TABLE hs_history_series (
    year INTEGER, indicator TEXT, value REAL, unit TEXT, note TEXT
);

CREATE TABLE hs_org_chart (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        branch TEXT NOT NULL,        -- 大类：市委/人大/政府/政协/民主党派/群团
        group_name TEXT NOT NULL,    -- 分组：工作部门/直属事业单位/专门委员会…
        org_name TEXT NOT NULL,      -- 机构全称
        sort_order INTEGER,          -- 页面内顺序
        source_url TEXT NOT NULL,    -- 原始网页（精确到子页）
        source_site TEXT,            -- 来源网站名
        published TEXT,              -- 网页发布日期
        fetched TEXT,                -- 抓取日期
        UNIQUE(branch, org_name)
    );

CREATE TABLE hs_org_duties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        org_name TEXT NOT NULL,
        duty_text TEXT NOT NULL,          -- 主要职责（全文/逐条）
        internal_orgs TEXT,               -- 内设机构（逗号分隔）
        headcount TEXT,                   -- 编制信息（原文摘录）
        source_type TEXT NOT NULL,        -- 编办官网 / 部门预算公开 / 手工补录
        source_url TEXT NOT NULL,
        published TEXT,
        fetched TEXT,
        UNIQUE(org_name, source_url)
    );

CREATE TABLE hs_page_kw_index (
    keyword TEXT PRIMARY KEY, hits TEXT
);

CREATE TABLE hs_pages (id INTEGER PRIMARY KEY AUTOINCREMENT,year INTEGER NOT NULL,pdf_name TEXT NOT NULL,page_num INTEGER NOT NULL,content TEXT NOT NULL,has_data INTEGER DEFAULT 0);

CREATE TABLE hs_pages_seg (id INTEGER PRIMARY KEY, seg TEXT);

CREATE TABLE jhsjk_articles (
    id TEXT PRIMARY KEY,
    title TEXT,
    publish_date TEXT,
    source TEXT,
    publishdep TEXT,
    content TEXT,
    chars INTEGER,
    status TEXT,
    url TEXT
);

CREATE VIRTUAL TABLE jhsjk_fts USING fts5(jid UNINDEXED, title_t, body_t, tokenize='unicode61');

CREATE TABLE lilun_books (
    bookid TEXT PRIMARY KEY,
    name TEXT,
    category TEXT,
    status TEXT,
    pages INTEGER,
    scan_pages INTEGER,
    text_chars INTEGER,
    ts TEXT,
    text_path TEXT,
    scan_only INTEGER DEFAULT 0
);

CREATE TABLE lineage (
    table_name TEXT, source_db TEXT, source_path TEXT, source_rows INTEGER,
    synced_at TEXT, sync_mode TEXT);

CREATE TABLE meta("key" TEXT,value TEXT);

CREATE VIRTUAL TABLE pages_fts USING fts5(content, content='hs_pages', content_rowid='id', tokenize='trigram');

CREATE VIRTUAL TABLE pages_fts_jieba USING fts5(seg, content='hs_pages_seg', content_rowid='id', tokenize='unicode61');

CREATE TABLE quotes_noise ( id INTEGER NOT NULL, kind TEXT NOT NULL, reason TEXT, rule_ver TEXT NOT NULL, marked_at TEXT, PRIMARY KEY (id, kind));

CREATE TABLE statements (
    id INTEGER PRIMARY KEY,
    type TEXT, content TEXT, article TEXT, author TEXT, idx INTEGER);

CREATE TABLE txt_corpus_index (
    id INTEGER PRIMARY KEY,
    category TEXT, seq TEXT, title TEXT, file_path TEXT);

-- ============ 索引 ============
CREATE INDEX idx_articles_date ON articles(publish_date);

CREATE INDEX idx_articles_source ON articles(source);

CREATE INDEX idx_articles_topic ON articles(topic);

CREATE INDEX idx_articles_url ON articles(url);

CREATE INDEX idx_gq_type ON golden_quotes(type);

CREATE INDEX idx_jhsjk_date ON jhsjk_articles(publish_date);

CREATE INDEX idx_jhsjk_title ON jhsjk_articles(title);

CREATE INDEX idx_stmt_type ON statements(type);

CREATE INDEX idx_tci_cat ON txt_corpus_index(category);

-- ============ 视图 ============
CREATE VIEW v_articles_corpus AS
SELECT id, title, author, source, publish_date, url, word_count,
       'qiushi' AS domain, genre, topic, level, arg_style, field, paradigm
FROM articles WHERE data_source IN ('求是杂志','求是-转载','求是图书')
UNION ALL
SELECT id, title, author, source, publish_date, url, word_count,
       'hongqi' AS domain, genre, topic, level, arg_style, field, paradigm
FROM articles WHERE data_source = '红旗文稿'
UNION ALL
SELECT id, title, author, source, publish_date, url, word_count,
       'qsweb' AS domain, genre, topic, level, arg_style, field, paradigm
FROM articles WHERE data_source = '求是网采集'
UNION ALL
SELECT id, title, author, source, publish_date, url, word_count,
       'renzhongping' AS domain, NULL, NULL, NULL, NULL, NULL, NULL
FROM articles WHERE data_source = '任仲平专项采集'
UNION ALL
SELECT id, title, author, source, publish_date, url, word_count,
       'helci' AS domain, NULL, NULL, NULL, NULL, NULL, NULL
FROM articles WHERE data_source = '贺词采集'
UNION ALL
SELECT id, title, author, source, publish_date, url, word_count,
       'bumen' AS domain, NULL, NULL, NULL, NULL, NULL, NULL
FROM articles WHERE data_source IN ('部委政策','法律法规','国务院公文')
UNION ALL
SELECT id, title, publishdep AS author, source, publish_date, url, chars AS word_count,
       'jhsjk' AS domain, NULL, NULL, NULL, NULL, NULL, NULL
FROM jhsjk_articles;
