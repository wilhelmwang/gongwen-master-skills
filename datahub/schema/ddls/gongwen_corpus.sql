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
