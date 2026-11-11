-- qs_articles.db 表结构 DDL（导出自 v6.7.0，2026-09-03）

CREATE INDEX idx_date ON articles(publish_date);

CREATE INDEX idx_keywords ON articles(keywords);

CREATE INDEX idx_source ON articles(data_source);

CREATE INDEX idx_title ON articles(title);

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
    , data_source TEXT DEFAULT "求是杂志");

CREATE VIRTUAL TABLE articles_fts USING fts5(
            title, content, author,
            content='articles', content_rowid='id'
        );

CREATE TABLE 'articles_fts_config'(k PRIMARY KEY, v) WITHOUT ROWID;

CREATE TABLE 'articles_fts_data'(id INTEGER PRIMARY KEY, block BLOB);

CREATE TABLE 'articles_fts_docsize'(id INTEGER PRIMARY KEY, sz BLOB);

CREATE TABLE 'articles_fts_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID;

CREATE TABLE meta (
        key TEXT PRIMARY KEY,
        value TEXT
    );

CREATE TABLE sqlite_sequence(name,seq);