#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
求是文章数据库引擎
功能：NLP语义检索 + 自动增量更新 + 多数据源整合
"""

import sqlite3
import os
import sys
def _find_root():
    """包根探测：向上找含 VERSION 的目录（目录改名/跨机部署自适应）"""
    import os
    p = os.path.dirname(os.path.abspath(__file__))
    while not os.path.exists(os.path.join(p, 'VERSION')) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    return p

_DATA_ROOT = os.path.join(_find_root(), 'datahub')

import re
import time
import json
import pickle
from datetime import datetime
from html import unescape

import jieba
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from rank_bm25 import BM25Okapi

# 数据路径：统一经 datahub/paths.py 解析（v7.3.0 单一事实源）
# 支持 GONGWEN_DATA_ROOT 环境变量覆盖；数据缺失时显式降级而非静默失败。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DATA_ROOT)
from paths import db_path, index_path, vectors_path, vectors_meta_path, bge_model_status
DB_PATH = db_path()
INDEX_PATH = index_path()
META_PATH = os.path.join(_DATA_ROOT, "derived", "qs_meta.json")

BASE_URL = "https://www.qstheory.cn"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# 停用词
STOPWORDS = set('的了是在我有和就不人都一上也很到说要去你会着没有看好自己这那他她它们而与及或但如果因为所以虽然然而并且还是或者就是这个那个什么怎么为什么哪里如何可以能够应该必须需要已经正在将要曾经一直总是经常常常有时偶尔仅仅只是不过另外此外因此于是然后接着最后首先其次再次总之综上据此由此可见'.split())


def init_db():
    """初始化数据库，扩展schema支持多数据源"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 主表（如果不存在则创建）
    c.execute('''CREATE TABLE IF NOT EXISTS articles (
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
        data_source TEXT DEFAULT '求是杂志',
        crawl_time TEXT
    )''')
    
    # 元数据表
    c.execute('''CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    
    # FTS5全文索引
    try:
        c.execute('''CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
            title, content, author,
            content='articles', content_rowid='id'
        )''')
    except:
        pass  # FTS5可能不支持，忽略
    
    # 检查并添加缺失的列（兼容旧表）
    c.execute('PRAGMA table_info(articles)')
    columns = [row[1] for row in c.fetchall()]
    if 'data_source' not in columns:
        c.execute('ALTER TABLE articles ADD COLUMN data_source TEXT DEFAULT "求是杂志"')
    if 'crawl_time' not in columns:
        c.execute('ALTER TABLE articles ADD COLUMN crawl_time TEXT')
    
    # 索引
    c.execute('CREATE INDEX IF NOT EXISTS idx_title ON articles(title)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_date ON articles(publish_date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_source ON articles(data_source)')
    
    conn.commit()
    conn.close()


def get_meta(key, default=None):
    """获取元数据"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT value FROM meta WHERE key=?', (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default


def set_meta(key, value):
    """设置元数据"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', (key, str(value)))
    conn.commit()
    conn.close()


def tokenize(text):
    """jieba分词，去停用词"""
    words = jieba.cut(text)
    return ' '.join([w for w in words if w.strip() and w not in STOPWORDS and len(w) > 1])


class SemanticSearch:
    """NLP混合检索引擎：TF-IDF语义 + BM25关键词，RRF融合"""

    def __init__(self):
        self.vectorizer = None
        self.tfidf_matrix = None
        self.bm25 = None
        self.corpus_tokens = None
        self.article_ids = []
        self.article_titles = []
        self._load_index()

    def _vec_search(self, query, top_n=20):
        """向量路（v6.8.1 修复 P0-1）：委托模块级 _vec_search_impl。
        原实现为 monkey-patch 且位于 __main__ 之后，CLI 直接执行时未挂载，
        hybrid3 检索必崩 AttributeError；改为类方法惰性委托，任何入口均生效。"""
        impl = globals().get('_vec_search_impl')
        return impl(self, query, top_n) if impl else None
    
    def _load_index(self):
        """加载或构建索引"""
        if os.path.exists(INDEX_PATH):
            try:
                with open(INDEX_PATH, 'rb') as f:
                    data = pickle.load(f)
                self.vectorizer = data['vectorizer']
                self.tfidf_matrix = data['tfidf_matrix']
                self.article_ids = data['article_ids']
                self.article_titles = data['article_titles']
                self.bm25 = data.get('bm25')
                self.corpus_tokens = data.get('corpus_tokens')
                print(f"[NLP] 索引加载成功: {len(self.article_ids)} 篇文章 (TF-IDF + BM25)")
                return
            except:
                print("[NLP] 索引加载失败，重新构建")
        
        self.build_index()
    
    def build_index(self):
        """从数据库构建TF-IDF + BM25索引"""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT id, title, content FROM articles WHERE content IS NOT NULL AND length(content) > 100')
        rows = c.fetchall()
        conn.close()
        
        if not rows:
            print("[NLP] 数据库为空，无法构建索引")
            return
        
        self.article_ids = []
        self.article_titles = []
        documents = []
        self.corpus_tokens = []
        
        for aid, title, content in rows:
            self.article_ids.append(aid)
            self.article_titles.append(title)
            doc = tokenize(title + ' ' + title + ' ' + content)
            documents.append(doc)
            self.corpus_tokens.append(doc.split())
        
        print(f"[NLP] 正在构建索引: {len(documents)} 篇文章...")
        self.vectorizer = TfidfVectorizer(max_features=50000, ngram_range=(1, 2))
        self.tfidf_matrix = self.vectorizer.fit_transform(documents)
        
        # 构建BM25索引
        print("[NLP] 构建BM25索引...")
        self.bm25 = BM25Okapi(self.corpus_tokens)
        
        # 保存索引（写点 containment 校验：索引必须落在数据根内）
        from paths import DATA_ROOT as _dr
        import pathlib as _pl
        _ir = os.path.realpath(INDEX_PATH)
        _root = os.path.realpath(_dr)
        if os.path.commonpath([_ir, _root]) != _root:
            raise ValueError('索引写点越界')
        _pl.Path(INDEX_PATH).write_bytes(pickle.dumps({
                'vectorizer': self.vectorizer,
                'tfidf_matrix': self.tfidf_matrix,
                'bm25': self.bm25,
                'corpus_tokens': self.corpus_tokens,
                'article_ids': self.article_ids,
                'article_titles': self.article_titles,
            }))
        
        print(f"[NLP] 索引构建完成: {len(self.article_ids)} 篇, {self.tfidf_matrix.shape[1]} 特征")
    
    def _tfidf_search(self, query, top_n=50):
        """TF-IDF语义检索"""
        query_vec = self.vectorizer.transform([tokenize(query)])
        similarities = cosine_similarity(query_vec, self.tfidf_matrix).flatten()
        return similarities
    
    def _bm25_search(self, query, top_n=50):
        """BM25关键词检索"""
        query_tokens = tokenize(query).split()
        scores = self.bm25.get_scores(query_tokens)
        return np.array(scores)

    @staticmethod
    def format_citation_card(hits, style='block'):
        """来源卡（v7.1 T3）：把检索命中格式化为可交付的溯源卡片。

        style: block（对话内展示，多行）| inline（正文附注行）
        每卡含：标题/刊源期次/发布日期/URL/摘录首句。
        """
        if not hits:
            return '（无检索命中，来源卡为空）'
        lines = []
        if style == 'block':
            lines.append('📚 来源卡（引用可溯，共 %d 条）' % len(hits))
            for i, h in enumerate(hits, 1):
                lines.append(f"  [{i}] 《{h.get('title', '')}》")
                issue = (f"{h.get('issue_year')}年第{h.get('issue_num')}期"
                         if h.get('issue_num') else h.get('issue_year'))
                meta = ' · '.join(x for x in (
                    h.get('source') or h.get('data_source'), issue,
                    h.get('publish_date')) if x)
                if meta:
                    lines.append(f'      {meta}')
                if h.get('url'):
                    lines.append(f"      URL: {h['url']}")
                snip = (h.get('snippet') or '')[:80]
                if snip:
                    lines.append(f'      摘录: {snip}…')
            return '\n'.join(lines)
        return '  '.join(
            f"[来源{i}: 《{h.get('title', '')}》{h.get('publish_date', '')}]"
            for i, h in enumerate(hits, 1))

    def search(self, query, top_n=10, min_similarity=0.02, mode='hybrid3'):
        """
        混合检索：TF-IDF语义 + BM25关键词，RRF融合
        mode: 'hybrid3'(词面+向量三路RRF,默认) / 'hybrid' / 'tfidf' / 'bm25' / 'vec'
        """
        if self.tfidf_matrix is None or len(self.article_ids) == 0:
            return []
        
        # RRF融合：1/(k+rank)，k=60
        k = 60
        rrf_scores = np.zeros(len(self.article_ids))

        # v7.1.2：话题同义词扩展（口语→规范概念词，缓解拒答率 21%）
        try:
            from topic_synonyms import expand_query
            _exp = expand_query(query)
        except Exception:
            _exp = [query]
        # 扩展词的 RRF 贡献权重减半（0.5），原词保持 1.0——扩展补充召回不打乱原序
        _exp = [t for t in _exp if t != query]

        # v6.9.0：候选窗口与 top_n 解耦（固定 100 深度），保证结果前缀不随 top_n 漂移
        _POOL = 100
        if mode in ('hybrid', 'tfidf', 'hybrid3'):
            tfidf_scores = self._tfidf_search(query)
            tfidf_ranks = np.argsort(tfidf_scores)[::-1]
            for rank, idx in enumerate(tfidf_ranks[:_POOL]):
                rrf_scores[idx] += 1.0 / (k + rank + 1)
            for _t in _exp:
                _ts = self._tfidf_search(_t)
                _tr = np.argsort(_ts)[::-1]
                for rank, idx in enumerate(_tr[:_POOL]):
                    rrf_scores[idx] += 0.5 / (k + rank + 1)

        if mode in ('hybrid', 'bm25', 'hybrid3') and self.bm25 is not None:
            bm25_scores = self._bm25_search(query)
            bm25_ranks = np.argsort(bm25_scores)[::-1]
            for rank, idx in enumerate(bm25_ranks[:_POOL]):
                rrf_scores[idx] += 1.0 / (k + rank + 1)
            for _t in _exp:
                _bs = self._bm25_search(_t)
                _br = np.argsort(_bs)[::-1]
                for rank, idx in enumerate(_br[:_POOL]):
                    rrf_scores[idx] += 0.5 / (k + rank + 1)
        
        # ---- 向量语义路（hybrid3 第三路，bge-small-zh，vec/ 惰性加载）----
        _vec_only = {}                      # vec 模式专用：idx → 余弦相似度
        if mode in ('hybrid3', 'vec'):
            vec_hits = self._vec_search(query, max(top_n * 5, _POOL))
            if vec_hits is not None:
                if mode == 'vec':
                    for aid, _s in vec_hits:
                        _vec_only[self.article_ids.index(aid)] = _s
                        if len(_vec_only) >= top_n:
                            break
                else:
                    for rnk, (aid, _s) in enumerate(vec_hits):
                        rrf_scores[self.article_ids.index(aid)] += 1.0 / (k + rnk + 1)

        # 按RRF分数排序（v6.9.0：np.argsort 有并列分数时次序不稳定，改用
        # 稳定排序 lexsort——主键 RRF 分降序、次键索引号升序，保证同分先后确定）
        if mode == 'vec':
            # vec 模式不走 RRF（rrf_scores 恒为 0，若按其排序会把结果全部过滤掉）；
            # _vec_search 已按相似度降序返回，保序即可
            top_indices = list(_vec_only.keys())
        else:
            _order = np.lexsort((np.arange(len(rrf_scores)), -rrf_scores))
            top_indices = _order[:top_n * 2]
        
        results = []
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        for idx in top_indices:
            if mode != 'vec' and rrf_scores[idx] <= 0:
                continue
            aid = self.article_ids[idx]
            c.execute('''SELECT id, title, author, source, publish_date, issue_year, issue_num, 
                         word_count, url, data_source, substr(content, 1, 500) 
                         FROM articles WHERE id=?''', (aid,))
            row = c.fetchone()
            if row:
                # 同时返回tfidf和bm25的原始分数
                tfidf_sim = float(self._tfidf_search(query)[idx]) if mode != 'bm25' else 0
                results.append({
                    'id': row[0],
                    'title': row[1],
                    'author': row[2],
                    'source': row[3],
                    'publish_date': row[4],
                    'issue_year': row[5],
                    'issue_num': row[6],
                    'word_count': row[7],
                    'url': row[8],
                    'data_source': row[9],
                    'snippet': row[10],
                    'similarity': round(float(_vec_only[idx]) if mode == 'vec'
                                        else float(rrf_scores[idx]), 4),
                    'tfidf_score': round(tfidf_sim, 4),
                    'search_mode': mode,
                })
            if len(results) >= top_n:
                break
        
        conn.close()
        return results
    
    def get_article_content(self, article_id):
        """获取文章全文"""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT title, author, source, publish_date, content FROM articles WHERE id=?', (article_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return {
                'title': row[0], 'author': row[1], 'source': row[2],
                'publish_date': row[3], 'content': row[4]
            }
        return None


def _safe_url(url):
    """外发请求护栏：仅 http/https 公网地址（防 file:/内网/loopback SSRF）"""
    import ipaddress
    from urllib.parse import urlparse
    u = urlparse(url)
    if u.scheme not in ('http', 'https'):
        raise ValueError(f'非 http(s) 地址已拒绝: {url[:60]}')
    host = (u.hostname or '').lower()
    bad = not host or host == 'localhost' or host.endswith('.local')
    if not bad:
        try:
            ip = ipaddress.ip_address(host)
            bad = ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
        except ValueError:
            bad = False
    if bad:
        raise ValueError(f'内网/保留地址已拒绝: {host or url[:60]}')
    return url


def fetch_url(url, retries=3):
    """获取URL内容"""
    import urllib.request
    _safe_url(url)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
                try:
                    return raw.decode('utf-8')
                except:
                    return raw.decode('gbk', errors='replace')
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                return None
    return None


def get_latest_issue():
    """获取求是网最新期数信息"""
    html = fetch_url("https://www.qstheory.cn/")
    if not html:
        return None, None
    
    # 匹配 "2026年第16期" 格式
    pattern = r'(\d{4})年第(\d+)期'
    matches = re.findall(pattern, html)
    if matches:
        # 取最大的期数
        matches.sort(key=lambda x: (int(x[0]), int(x[1])), reverse=True)
        year, num = matches[0]
        return int(year), int(num)
    
    return None, None


def get_issue_articles(issue_url):
    """获取一期的文章列表"""
    html = fetch_url(issue_url)
    if not html:
        return []
    
    pattern = r'<a[^>]+href=["\']([^"\']*(?:c_\d+\.htm|/c\.html)[^"\']*)["\'][^>]*>([^<]+)</a>'
    matches = re.findall(pattern, html)
    articles = []
    for url, title in matches:
        title = unescape(title.strip())
        if not title or len(title) < 3:
            continue
        if title.startswith('《求是') or '网站声明' in title or title == '本期导读':
            continue
        if url.startswith('//'):
            url = 'https:' + url
        elif url.startswith('/'):
            url = BASE_URL + url
        articles.append({'url': url, 'title': title})
    return articles


def parse_article(html, url):
    """解析文章页"""
    result = {'title': '', 'author': '', 'source': '', 'publish_date': '', 'content': ''}
    
    title_match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
    if title_match:
        result['title'] = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
    
    source_match = re.search(r'来源[：:]\s*([^<\s]+)', html)
    if source_match:
        result['source'] = source_match.group(1).strip()
    
    date_match = re.search(r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})', html)
    if date_match:
        result['publish_date'] = f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"
    
    author_match = re.search(r'作者[：:]\s*([^<\n]+)', html)
    if author_match:
        result['author'] = author_match.group(1).strip()
    
    # 提取<p>标签
    paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', html, re.DOTALL)
    clean_paras = []
    for p in paragraphs:
        text = re.sub(r'<[^>]+>', '', p)
        text = unescape(text).strip()
        if len(text) > 10:
            clean_paras.append(text)
    
    result['content'] = '\n\n'.join(clean_paras)
    result['word_count'] = len(result['content'])
    return result


def incremental_update():
    """
    增量更新：检查最新期数，只爬新文章
    返回: 新增文章数
    """
    print(f"\n{'='*60}")
    print(f"[UPDATE] 开始增量更新 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    
    init_db()
    
    # 获取数据库中最新的文章日期
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT MAX(publish_date) FROM articles WHERE data_source="求是杂志"')
    last_date = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM articles WHERE data_source="求是杂志"')
    total_before = c.fetchone()[0]
    conn.close()
    
    print(f"[UPDATE] 数据库现有 {total_before} 篇求是文章，最新日期: {last_date}")
    
    # 获取最新期数
    latest_year, latest_num = get_latest_issue()
    print(f"[UPDATE] 求是网最新: {latest_year}年第{latest_num}期")
    
    if not latest_year:
        print("[UPDATE] 无法获取最新期数，跳过更新")
        return 0
    
    # 获取年份总目录页，找到所有期数链接
    year_index_url = f"https://www.qstheory.cn/dukan/qs/{latest_year}-01/01/c_1130050739.htm"
    # 尝试从mulu获取
    mulu_html = fetch_url("http://qstheory.com/qs/mulu.htm")
    year_links = {}
    if mulu_html:
        links = re.findall(r'href=["\']([^"\']*/dukan/qs/\d{4}-\d{2}/\d{2}/c_\d+\.htm)["\']', mulu_html)
        for link in links:
            if link.startswith('//'):
                link = 'https:' + link
            ym = re.search(r'/(\d{4})-(\d{2})/', link)
            if ym:
                y = int(ym.group(1))
                if y not in year_links:
                    year_links[y] = link
    
    new_articles = 0
    
    # 爬取最新年份的所有期数（增量）
    for year in [latest_year, latest_year - 1]:  # 检查最近两年
        if year not in year_links:
            continue
        
        print(f"\n[UPDATE] 检查 {year} 年...")
        issues_html = fetch_url(year_links[year])
        if not issues_html:
            continue
        
        issue_pattern = r'href=["\']([^"\']*/dukan/qs/\d+/(\d{4})-(\d{2})-(\d{2})/c_\d+\.htm)["\'][^>]*>[^<]*《求是》\s*(\d{4})年第(\d+)期'
        issues = re.findall(issue_pattern, issues_html)
        
        for url, y, m, d, iy, num in issues:
            if url.startswith('//'):
                url = 'https:' + url
            
            # 检查这期是否已爬（通过URL前缀判断）
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('SELECT COUNT(*) FROM articles WHERE url LIKE ?', (f'%{url.split("/")[-1].replace(".htm","")}%',))
            exists = c.fetchone()[0] > 0
            conn.close()
            
            if exists:
                continue
            
            print(f"[UPDATE] 爬取 {iy}年第{num}期...")
            articles = get_issue_articles(url)
            
            for art in articles:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute('SELECT id FROM articles WHERE url=?', (art['url'],))
                if c.fetchone():
                    conn.close()
                    continue
                conn.close()
                
                html = fetch_url(art['url'])
                if html:
                    parsed = parse_article(html, art['url'])
                    parsed['url'] = art['url']
                    if not parsed['title']:
                        parsed['title'] = art['title']
                    
                    conn = sqlite3.connect(DB_PATH)
                    c = conn.cursor()
                    try:
                        c.execute('''INSERT OR IGNORE INTO articles 
                            (title, author, source, publish_date, issue_year, issue_num, url, content, keywords, word_count, data_source, crawl_time)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '求是杂志', ?)''',
                            (parsed.get('title',''), parsed.get('author',''), parsed.get('source',''),
                             parsed.get('publish_date',''), int(iy), int(num),
                             parsed.get('url',''), parsed.get('content',''), '', 
                             parsed.get('word_count',0), datetime.now().isoformat()))
                        conn.commit()
                        if c.rowcount > 0:
                            new_articles += 1
                            print(f"  + {parsed['title'][:40]} ({parsed['word_count']}字)")
                    except Exception as e:
                        print(f"  ✗ 保存失败: {e}")
                    conn.close()
                
                time.sleep(0.3)
    
    # 更新元数据
    set_meta('last_update', datetime.now().isoformat())
    set_meta('total_articles', total_before + new_articles)
    
    print(f"\n[UPDATE] 增量更新完成，新增 {new_articles} 篇")
    
    # 如果有新文章，重建NLP索引
    if new_articles > 0:
        print("[UPDATE] 有新文章，重建NLP索引...")
        search_engine = SemanticSearch()
        if os.path.exists(INDEX_PATH):
            os.remove(INDEX_PATH)
        search_engine.build_index()
    
    return new_articles


def fts_search(query, top_n=10):
    """FTS5 快路检索（v6.9.0 P1-1）：预物化 jieba 分词列 + BM25，冷启动毫秒级。
    依赖 articles_fts 虚表（由 rebuild_fts.py 生成）；缺表时返回 None 由调用方降级。
    返回格式与 SemanticSearch.search 一致（title/snippet/similarity）。"""
    import os as _os
    db = _os.environ.get('GONGWEN_QS_DB', DB_PATH)
    if not _os.path.exists(db):
        return None
    conn = sqlite3.connect(db)
    try:
        has_fts = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='articles_fts'").fetchone()
        if not has_fts:
            return None
        q_tokens = ' '.join(tokenize(query).split())
        if not q_tokens:
            return None
        t0 = time.time()
        rows = conn.execute(
            '''SELECT a.id, a.title, a.author, a.source, a.publish_date, a.issue_year, a.issue_num,
                      a.word_count, a.url, substr(a.content, 1, 500), f.s
               FROM (SELECT article_id, bm25(articles_fts) AS s
                     FROM articles_fts WHERE articles_fts MATCH ?
                     ORDER BY s LIMIT ?) f
               JOIN articles a ON a.id = f.article_id
               ORDER BY f.s LIMIT ?''',
            (q_tokens, top_n * 3, top_n)).fetchall()
        _ms = (time.time() - t0) * 1000
        # 归一化分数（bm25 负值越小越相关 → 转 0-1 正向）
        out = []
        for r in rows:
            sim = round(min(1.0, max(0.0, 1.0 + r[10] / 20.0)), 4)
            out.append({'id': r[0], 'title': r[1], 'author': r[2], 'source': r[3],
                        'publish_date': r[4], 'issue_year': r[5], 'issue_num': r[6],
                        'word_count': r[7], 'url': r[8], 'snippet': r[9],
                        'similarity': sim, 'search_mode': 'fts', 'latency_ms': round(_ms, 1)})
        return out
    except Exception:
        return None
    finally:
        conn.close()


def search_database(query, top_n=10, use_semantic=True):
    """
    统一检索接口：语义检索 + 关键词检索 + FTS 快路（v6.9.0）
    use_semantic=True: NLP语义理解（默认，hybrid3 全量路）
    use_semantic=False: 纯关键词LIKE检索
    环境变量 GONGWEN_FAST=1 时优先 FTS 快路（毫秒级），缺表/异常自动降级全量路
    """
    if use_semantic:
        if os.environ.get('GONGWEN_FAST') == '1':
            r = fts_search(query, top_n=top_n)
            if r is not None:
                return r
        engine = SemanticSearch()
        return engine.search(query, top_n=top_n)
    else:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''SELECT id, title, author, source, publish_date, issue_year, issue_num, 
                     word_count, url, substr(content, 1, 500)
                     FROM articles 
                     WHERE title LIKE ? OR content LIKE ?
                     ORDER BY publish_date DESC LIMIT ?''',
                  (f'%{query}%', f'%{query}%', top_n))
        rows = c.fetchall()
        conn.close()
        return [{'id': r[0], 'title': r[1], 'author': r[2], 'source': r[3],
                 'publish_date': r[4], 'issue_year': r[5], 'issue_num': r[6],
                 'word_count': r[7], 'url': r[8], 'snippet': r[9], 'similarity': None} for r in rows]


def get_stats():
    """获取数据库统计"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM articles')
    total = c.fetchone()[0]
    c.execute('SELECT data_source, COUNT(*) FROM articles GROUP BY data_source')
    by_source = c.fetchall()
    c.execute('SELECT issue_year, COUNT(*) FROM articles WHERE issue_year IS NOT NULL GROUP BY issue_year ORDER BY issue_year')
    by_year = c.fetchall()
    c.execute('SELECT SUM(word_count) FROM articles')
    total_words = c.fetchone()[0]
    last_update = get_meta('last_update')
    conn.close()
    
    return {
        'total': total,
        'total_words': total_words,
        'by_source': by_source,
        'by_year': by_year,
        'last_update': last_update,
    }


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == 'update':
            incremental_update()
        
        elif cmd == 'search':
            query = ' '.join(sys.argv[2:])
            print(f"\n语义检索: {query}")
            print("=" * 60)
            results = search_database(query, top_n=10, use_semantic=True)
            for i, r in enumerate(results, 1):
                print(f"\n{i}. [{r['similarity']}] {r['title']}")
                print(f"   作者:{r['author']} 日期:{r['publish_date']} {r['word_count']}字")
                print(f"   摘要: {r['snippet'][:100]}...")
        
        elif cmd == 'stats':
            stats = get_stats()
            print(f"\n数据库统计:")
            print(f"  总文章数: {stats['total']}")
            print(f"  总字数: {stats['total_words']:,}")
            print(f"  最后更新: {stats['last_update']}")
            print(f"\n按来源:")
            for s, n in stats['by_source']:
                print(f"  {s}: {n}篇")
            print(f"\n按年份:")
            for y, n in stats['by_year']:
                print(f"  {y}年: {n}篇")
        
        elif cmd == 'reindex':
            if os.path.exists(INDEX_PATH):
                os.remove(INDEX_PATH)
            engine = SemanticSearch()
            engine.build_index()
        
        else:
            print("用法: python qiushi_engine.py [update|search <query>|stats|reindex]")
    else:
        # 默认：显示统计
        stats = get_stats()
        print(f"数据库: {stats['total']}篇, {stats['total_words']:,}字")
        print(f"最后更新: {stats['last_update']}")

# ---- v6.6.0 向量语义检索（hybrid3 第三路，惰性加载）----
_VEC = {'V': None, 'meta': None, 'model': None}

def _lazy_load_vec():
    import os, json, numpy as np
    vp = vectors_path()
    cp = vectors_meta_path()
    if not os.path.exists(vp):
        return False
    if _VEC['V'] is None:
        _VEC['V'] = np.load(vp)
        _VEC['meta'] = json.load(open(cp, encoding='utf-8'))['meta']
    return True

def _vec_query_embed(query):
    if _VEC['model'] is None:
        # v7.5.0：模型目录改经 paths.bge_model_status() 解析（环境变量 → assets.json 登记项）。
        # 此前只认 GONGWEN_BGE_MODEL，机器上模型明明在位却因"没人 export"而长期静默降级，
        # 门禁量到的 98%/0.937/gold 72% 实为无向量路成绩（开向量路为 99%/0.974/gold 74.0%）。
        if _VEC.get('failed'):
            return None
        ok, MODEL, _src, why = bge_model_status()
        if not ok:
            _VEC['failed'] = True
            print(f'[gongwen] 向量路关闭：{why} → 已降级词面检索（TF-IDF + BM25）。')
            return None
        try:
            from sentence_transformers import SentenceTransformer
            _VEC['model'] = SentenceTransformer(MODEL)
        except Exception as e:
            _VEC['failed'] = True
            print(f'[gongwen] 向量模型加载失败（{MODEL}）：{e} → 已降级词面检索。')
            return None
    return _VEC['model'].encode([query], normalize_embeddings=True)[0]

def _vec_search_impl(self, query, top_n=20):
    "向量路：查询嵌入 → 余弦，块级 max 聚合到篇级 → [(aid, score)]"
    if not _lazy_load_vec():
        return None
    try:
        qv = _vec_query_embed(query)
        if qv is None:
            return None
        import numpy as np
        sims = _VEC['V'] @ qv.astype('float32')
        aid_max = {}
        for (aid, _idx), s in zip(_VEC['meta'], sims.tolist()):
            if s > aid_max.get(aid, 0.0):
                aid_max[aid] = s
        return sorted(aid_max.items(), key=lambda x: -x[1])[:top_n]
    except Exception:
        return None

# v6.8.1：_vec_search 已在 SemanticSearch.__init__ 中挂载（原此处 monkey-patch
# 位于 __main__ 之后，CLI 路径下 hybrid3 检索必崩 AttributeError，已修复）

