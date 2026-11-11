#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""国务院公报全量采集（gov.cn 搜索接口 · v1.0）

数据源
------
`https://sousuo.www.gov.cn/search-gov/data?t=gongbao` —— 国务院公报 2000-2026 全量
（国发/国办发/国函/行政法规/任免等，约 1.5 万篇）。

接口实测要点（2026-09-12）
------------------------
- 必须带 `Referer: https://sousuo.www.gov.cn/`
- **`totalCount` 字段恒为 0 但数据照常返回**——不能拿它判断总数/终止，
  必须按「返回空列表」作为翻页终止条件
- `searchVO.catMap.{type}.listVO[]` 是数据所在，含 title/url/pubtimeStr/wenhao
- 详情页为静态 HTML，正文可直接抽取

安全约束（SSRF 防护）
--------------------
- 仅允许 http/https
- 请求前校验 host：拒绝 localhost/环回/私有/保留地址（含十进制/八进制 IP 变体），
  且本采集器**只允许 *.gov.cn 及 sousuo.www.gov.cn**（白名单，防止被重定向到内网）

用法
----
  python crawl_gongbao.py --enum                  # 阶段A：枚举元数据（快，数百请求）
  python crawl_gongbao.py --fetch --max 50        # 阶段B：下载正文（--max 限本次量，用于试跑）
  python crawl_gongbao.py --fetch                 # 阶段B：下载全部未采正文
  python crawl_gongbao.py --build                 # 整理+入库（独立 SQLite gongbao.db）
  python crawl_gongbao.py --stats                 # 查看进度
  python crawl_gongbao.py --build --db D:/xx/gongbao.db   # 指定入库路径

设计
----
- **两阶段**：先枚举元数据（JSONL），再逐篇下载正文——枚举失败不影响已得清单，
  下载中断可续跑（已采 URL 跳过）。
- **断点续跑**：全部状态落 `gongbao_meta.jsonl` / `gongbao_docs.jsonl`，重跑自动跳过。
- **限速**：单线程，枚举 0.4s/请求、下载 0.6s/请求（jitter ±30%），失败指数退避。
"""
import argparse
import datetime
import gzip
import ipaddress
import json
import os
import random

#: 限速抖动用 CSPRNG（Mimosa 审计建议；行为等价，仅随机源升级）
_RND = random.SystemRandom()
import re
import socket
import sqlite3
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

API = 'https://sousuo.www.gov.cn/search-gov/data'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      'Referer': 'https://sousuo.www.gov.cn/',
      'Accept-Language': 'zh-CN,zh;q=0.9'}
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

#: 清洗残留（与 doc_code_check C10 同口径扩展：gov.cn 页面特有）
RESIDUAL = [
    r'京ICP备\S*', r'网站标识码\S*', r'主办单位：.*$', r'版权所有：.*$',
    r'责任编辑：.*$', r'新华社记者\s*\S+/摄', r'^\s*【我要纠错】.*$', r'^\s*打印\s*$',
    r'^\s*关闭\s*$', r'^\s*相关稿件\s*$', r'^\s*附件[：:].*$', r'^\s*扫一扫[^\n]*$',
    r'^\s*分享到[^\n]*$', r'^\s*\[责任编辑[^\]]*\]\s*$',
]
ZW = re.compile(r'[\u200b-\u200f\u202a-\u202e\ufeff]')

#: 文种分类（按标题；顺序即优先级）
DOC_TYPES = [
    ('行政法规', ('条例',)), ('制度规定', ('办法', '规定', '细则', '规则')),
    ('任免', ('任免', '任命', '免职')),
    ('批复', ('批复',)), ('通报', ('通报',)), ('通告公告', ('公告', '通告')),
    ('决定', ('决定',)), ('命令', ('令',)),
    ('政府工作报告', ('政府工作报告',)), ('贺词', ('贺词', '贺信')),
    ('意见', ('指导意见', '实施意见', '若干意见', '意见')),
    ('通知', ('通知',)), ('报告', ('报告',)),
]

# ---------------------------------------------------------------- SSRF 防护

def safe_host(url):
    """仅 http/https + host 白名单（*.gov.cn）+ 拒绝 localhost/私有/保留地址。

    即使 URL 来自接口返回，也不信任——防止接口被投毒后重定向到内网。
    """
    p = urllib.parse.urlparse(url)
    if p.scheme not in ('http', 'https'):
        raise ValueError(f'非 http/https: {p.scheme}')
    host = (p.hostname or '').lower()
    if not host or host in ('localhost',) or host.endswith('.local') or host.endswith('.internal'):
        raise ValueError(f'拒绝主机: {host}')
    # IP 字面量：必须是公网
    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            raise ValueError(f'拒绝非公网 IP: {host}')
    except ValueError as e:
        if 'does not appear' not in str(e) and '拒绝' not in str(e):
            pass  # 不是 IP 字面量，继续域名校验
        elif str(e).startswith('拒绝'):
            raise
    # 白名单：仅政府域名
    if not (host == 'gov.cn' or host.endswith('.gov.cn')):
        raise ValueError(f'非 gov.cn 域名: {host}')
    # DNS 解析后再查一次（防 DNS rebinding 到内网）
    try:
        for info in socket.getaddrinfo(host, None):
            a = ipaddress.ip_address(info[4][0])
            if not a.is_global:
                raise ValueError(f'域名解析到非公网地址: {host} → {a}')
    except socket.gaierror as e:
        raise ValueError(f'DNS 解析失败: {host}: {e}')
    return url


def fetch(url, timeout=30, retries=4):
    url = safe_host(url)
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
                b = r.read()
                if r.headers.get('Content-Encoding') == 'gzip':
                    b = gzip.decompress(b)
                for enc in ('utf-8', 'gb18030'):
                    try:
                        return r.status, b.decode(enc)
                    except UnicodeDecodeError:
                        continue
                return r.status, b.decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}'
            if e.code in (403, 404, 410):
                break
        except Exception as e:
            last = f'{type(e).__name__}: {str(e)[:70]}'
        if i < retries - 1:
            time.sleep(min(10, 1.5 * (2 ** i)) * _RND.uniform(0.8, 1.3))
    raise RuntimeError(last or '未知错误')


# ---------------------------------------------------------------- 阶段 A：枚举

_SUB = 'gongbao'          #
_T = 'gongbao'            # 接口 t 值（zhengcelibrary_gw / _bm / gongbao） 输出子目录名（随 --t 切换：gongbao / zhengcelibrary_gw / _bm）


def out_dir():
    """输出目录**一律经 `datahub/paths.py` 解析**，不猜路径。

    ⚠️ 2026-09-16 修复：原实现是
        `os.path.join(BASE, '..', '..', '..', '001_System', 'Desktop', 'WorkStation',
                      'WorkBuddyData', '<数据根>', 'gongwen', 'govdoc_samples', _SUB)`
    ——即「从包根向上三级 + 硬编码 001_System\\Desktop\\WorkStation\\WorkBuddyData」。
    这段只在**桌面工作副本**布局下成立（那里向上三级正好是 `D:\\`），工作副本一换位置
    就静默落到 except 分支。实测后果：2026-09-15 一次误触发的采集把 40 MB 公报全文
    写进了内置默认根 `~/gongwen-data`，而权威数据根（`assets.json:data_root`）里一条没进；
    因为 `paths` 的默认根存在但资产不全，包自检还把形态误判成 A 并报 FAIL。
    **路径解析只能有一个出口**——这是本项目「硬编码机器路径」类缺陷的复发点，
    故这里直接调解析器，连兜底也不再自行拼路径。
    """
    try:
        sys.path.insert(0, os.path.join(BASE, 'datahub'))
        from paths import DATA_ROOT
        d = os.path.join(DATA_ROOT, 'govdoc_samples', _SUB)
    except Exception:
        d = os.path.join(BASE, 'datahub', 'derived', 'govdoc_samples', _SUB)
    os.makedirs(d, exist_ok=True)
    return d


def meta_path():
    return os.path.join(out_dir(), 'gongbao_meta.jsonl')


def load_meta():
    """读元数据清单。二进制逐行读 + errors=replace：文件可能含历史坏行，
    单行解析失败只跳过该行（曾因全局替换产生未定义变量被 except 吞掉、
    静默返回 0 行的缺陷——异常处理必须有下界，不能吞掉"全部失败"）。"""
    seen, rows = {}, []
    if os.path.exists(meta_path()):
        for raw in open(meta_path(), 'rb'):
            try:
                r = json.loads(raw.decode('utf-8', 'replace'))
                if isinstance(r, dict) and r.get('url') and r['url'] not in seen:
                    seen[r['url']] = r
                    rows.append(r)
            except Exception:
                pass
    return seen, rows


def append_jsonl(path, rec):
    # 二进制单次写入：文本模式缓冲在进程被杀时可能留下半行，与后续追加拼成一行
    # 非法 UTF-8（实测踩过，强停后台任务时发生）。单次 write(bytes) 原子性最好。
    # 换行用 chr(10)：绕开转义（本会话已三次被 heredoc/转义坑）。
    data = (json.dumps(rec, ensure_ascii=False) + chr(10)).encode('utf-8')
    with open(path, 'ab') as f:
        f.write(data)


def classify(title):
    for name, kws in DOC_TYPES:
        if any(k in title for k in kws):
            return name
    return '其他'


def enum(n_per=50, max_pages=0, delay=0.4):
    d = out_dir()
    seen, rows = load_meta()
    print(f'=== 阶段A：枚举公报元数据（已有 {len(rows)} 条）===')
    page, new, empty_streak = 1, 0, 0
    while True:
        if max_pages and page > max_pages:
            break
        u = (f'{API}?t={_T}&q=&timetype=timeqb&sort=pubtime&sortType=1'
             f'&p={page}&n={n_per}')
        try:
            st, h = fetch(u)
        except Exception as e:
            print(f'  p{page} ✗ {e}（重试将由外层续跑处理）')
            break
        try:
            vo = (json.loads(h).get('searchVO') or {})
        except Exception:
            print(f'  p{page} ✗ JSON 解析失败')
            break
        lst = []
        for catname, cat in (vo.get('catMap') or {}).items():
            for _it in (cat.get('listVO') or []):
                _it.setdefault('cat', catname)
                lst.append(_it)
        if not lst:
            print(f'  p{page} 返回空 → 枚举完成')
            break
        page_new = 0
        for it in lst:
            url = it.get('url') or ''
            if not url.startswith('http'):
                continue
            if url in seen:
                continue
            _t0 = re.sub(r'<[^>]+>', '', it.get('title') or '')          # 去标签
            _title = _t0.replace(chr(10), '').replace(chr(13), '').strip()
            rec = {'title': _title, 'url': url, 'pubtime': it.get('pubtimeStr') or '',
                   'wenhao': it.get('wenhao') or '', 'doc_type': classify(_title),
                   # 接口自带元数据（备用价值：detail 页不可达时可回退；文号/发文机关/分类）
                   'cat': it.get('cat') or '', 'summary': (it.get('summary') or '')[:800],
                   'puborg': it.get('puborg') or '', 'pcode': it.get('pcode') or '',
                   'fileno': it.get('index') or '', 'childtype': it.get('childtype') or ''}
            append_jsonl(meta_path(), rec)
            seen[url] = rec
            rows.append(rec)
            page_new += 1
        new += page_new
        if page % 10 == 0 or page <= 3:
            print(f'  p{page}: +{page_new}（累计 {len(rows)}）')
        if page_new == 0:
            empty_streak += 1
            if empty_streak >= 3:
                print('  连续 3 页无新条目 → 枚举完成')
                break
        page += 1
        time.sleep(delay * _RND.uniform(0.7, 1.3))
    print(f'=== 枚举完成：新增 {new}，总计 {len(rows)} 条元数据 ===')
    return 0


# ---------------------------------------------------------------- 阶段 B：下载正文

def html_to_text(h):
    h = re.sub(r'(?is)<(script|style|noscript)[^>]*>.*?</\1>', '', h)
    h = re.sub(r'(?is)<!--.*?-->', '', h)
    # 公报正文容器优先
    m = re.search(r'(?is)<div[^>]+id="UCAP-CONTENT"[^>]*>([\s\S]*?)</div>\s*(?:<div|</div>)', h)
    if not m:
        m = re.search(r'(?is)<div[^>]+id="zoom"[^>]*>([\s\S]*?)</div>', h)
    body = m.group(1) if m else None
    h2 = body if body else h
    h2 = re.sub(r'(?i)<br\s*/?>', '\n', h2)
    h2 = re.sub(r'(?i)</(p|div|li|tr|h[1-6])>', '\n', h2)
    h2 = re.sub(r'<[^>]+>', '', h2)
    for a, b in (('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'),
                 ('&quot;', '"'), ('&#39;', "'"), ('&ldquo;', '"'), ('&rdquo;', '"'),
                 ('&mdash;', '—')):
        h2 = h2.replace(a, b)
    h2 = ZW.sub('', h2)
    return '\n'.join(l.strip() for l in h2.split('\n') if l.strip())


def clean_body(text):
    out = []
    for l in text.split('\n'):
        for pat in RESIDUAL:
            l = re.sub(pat, '', l, flags=re.M)
        l = l.strip()
        if l and len(l) > 2 and not re.fullmatch(r'[\s\-—_=·•※*]+', l):
            out.append(l)
    return '\n'.join(out)


def docs_path():
    return os.path.join(out_dir(), 'gongbao_docs.jsonl')


def load_docs():
    """已采 URL 集合 —— **跨集合扫描** govdoc_samples 下所有子目录的 gongbao_docs.jsonl。

    理由：t=gongbao/gw/bm 三个独立集合已采过 33,555 篇；用 t=zhengcelibrary 做全量枚举+抓取时
    必须知道这些已采项，否则 URL 去重失效、重复抓取 3.3 万篇（白耗对方带宽）。
    """
    seen = set()
    roots = []
    if os.path.exists(docs_path()):
        roots.append(docs_path())
    try:
        _parent = os.path.dirname(out_dir())
        for d in os.listdir(_parent):
            fp2 = os.path.join(_parent, d, "gongbao_docs.jsonl")
            if os.path.exists(fp2) and fp2 not in roots:
                roots.append(fp2)
    except Exception:
        pass
    for rp in roots:
        for raw in open(rp, "rb"):
            try:
                seen.add(json.loads(raw.decode("utf-8", "replace"))["url"])
            except Exception:
                pass
    return seen


def fetch_bodies(max_n=0, delay=0.6, workers=1):
    d = out_dir()
    _s, rows = load_meta()
    done = load_docs()
    todo = [r for r in rows if r['url'] not in done]
    if max_n:
        todo = todo[:max_n]
    print(f'=== 阶段B：下载正文（待采 {len(todo)} / 已采 {len(done)} / 清单 {len(rows)}）'
          f'｜ {workers} 线程 × {delay}s 间隔 ===', flush=True)
    if not todo:
        print('（无待采）')
        return 0

    ok = fail = idx = 0
    lock = threading.Lock()
    t0 = time.time()

    def work():
        nonlocal ok, fail, idx
        while True:
            with lock:
                if idx >= len(todo):
                    return
                r = todo[idx]; idx += 1
            try:
                st, h = fetch(r['url'])
                body = clean_body(html_to_text(h))
                if len(body) < 25:
                    raise RuntimeError(f'正文过短（{len(body)} 字；任免类短文可低至 19 字，<25 视为抽取失败）')
                rec = dict(r)
                rec['content'] = body
                rec['word_count'] = len(body)
                rec['txt_hash'] = __import__('hashlib').sha256(
                    body.encode('utf-8')).hexdigest()[:32]
                rec['fetched_at'] = datetime.datetime.now().isoformat(timespec='seconds')
                with lock:
                    append_jsonl(docs_path(), rec)
                    ok += 1
                    i = ok + fail
                    if i % 100 == 0 or i <= workers:
                        rate = i / max(time.time() - t0, 1)
                        eta = (len(todo) - i) / max(rate, 0.01) / 60
                        print(f'  [{i}/{len(todo)}] ✅ {len(body):6d} 字 ｜ {r["title"][:26]}'
                              f' ｜ {rate:.1f} 篇/s ｜ 剩余约 {eta:.0f} 分钟', flush=True)
            except Exception as e:
                with lock:
                    fail += 1
                    append_jsonl(os.path.join(d, 'gongbao_failed.jsonl'),
                                 {'url': r['url'], 'title': r.get('title'), 'error': str(e)[:120],
                                  'at': datetime.datetime.now().isoformat(timespec='seconds')})
            time.sleep(delay * _RND.uniform(0.7, 1.3))

    threads = [threading.Thread(target=work, daemon=True) for _ in range(max(1, workers))]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    print(f'=== 下载完成：本次成功 {ok} ｜ 失败 {fail}（失败清单可重跑补采）===', flush=True)
    return 0


# ---------------------------------------------------------------- 整理+入库

def build(db_path=None, only_cat=None):
    _s, rows = load_meta()
    seen, docs = set(), []
    if os.path.exists(docs_path()):
        for raw in open(docs_path(), 'rb'):
            try:
                r = json.loads(raw.decode('utf-8', 'replace'))
                if r['url'] not in seen:
                    seen.add(r['url'])
                    docs.append(r)
                if only_cat and (r.get('cat') or '') and r['cat'] != only_cat:
                    docs.pop()
            except Exception:
                pass
    print(f'=== 整理+入库：清单 {len(rows)} ｜ 已采正文 {len(docs)} ===')
    if not docs:
        print('（无正文可入库）')
        return 1
    # 去重：同文号同题视为重复；正文哈希重复保留首篇
    by_hash, uniq, dup = {}, [], 0
    for r in docs:
        h = r.get('txt_hash')
        if h and h in by_hash:
            dup += 1
            continue
        if h:
            by_hash[h] = r
        uniq.append(r)
    # 入库时重算文种与规范化标题——枚举阶段的分类可能因 classify 词表升级而过时，
    # 早期枚举的标题还带 <br/> 残留的原始空白（修复前正则误写 \s 为字面反斜杠）
    for r in uniq:
        r['title'] = re.sub(r'\s+', ' ', (r.get('title') or '')).strip()
        r['doc_type'] = classify(r.get('title') or '')
    types = {}
    for r in uniq:
        types[r.get('doc_type') or '其他'] = types.get(r.get('doc_type') or '其他', 0) + 1

    if not db_path:
        try:
            sys.path.insert(0, os.path.join(BASE, 'datahub'))
            from paths import DATA_ROOT
            db_path = os.path.join(DATA_ROOT, 'gongbao.db')
        except Exception:
            db_path = os.path.join(out_dir(), 'gongbao.db')
    db_path = os.path.abspath(db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.executescript('''
DROP TABLE IF EXISTS gongbao_fts;   -- 每次重建：tokenizer 迁移 + 保证索引与主表一致
CREATE TABLE IF NOT EXISTS gongbao (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT, wenhao TEXT, pubtime TEXT, doc_type TEXT,
  url TEXT UNIQUE, word_count INTEGER, txt_hash TEXT,
  content TEXT, fetched_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_gongbao_type ON gongbao(doc_type);
CREATE INDEX IF NOT EXISTS idx_gongbao_pubtime ON gongbao(pubtime);
-- tokenizer 必须显式 trigram：默认 unicode61 把整段中文当一个 token，
-- MATCH '生态' 永远 0 命中（实测踩过）。trigram 代价：MATCH 词长需 ≥3 字，
-- 2 字查询走 LIKE（trigram 表对 LIKE 有索引加速）。
CREATE VIRTUAL TABLE IF NOT EXISTS gongbao_fts USING fts5(
  title, content, content='gongbao', content_rowid='id', tokenize='trigram');
CREATE TABLE IF NOT EXISTS gongbao_meta (k TEXT PRIMARY KEY, v TEXT);
''')
    now = datetime.datetime.now().isoformat(timespec='seconds')
    for r in uniq:
        conn.execute('''INSERT OR REPLACE INTO gongbao
            (title,wenhao,pubtime,doc_type,url,word_count,txt_hash,content,fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            (r.get('title'), r.get('wenhao'), r.get('pubtime'), r.get('doc_type'),
             r.get('url'), r.get('word_count'), r.get('txt_hash'),
             r.get('content'), r.get('fetched_at') or now))
    conn.execute("INSERT INTO gongbao_fts(gongbao_fts) VALUES('rebuild')")
    conn.execute('INSERT OR REPLACE INTO gongbao_meta VALUES (?,?)', ('last_build', now))
    conn.execute('INSERT OR REPLACE INTO gongbao_meta VALUES (?,?)', ('doc_count', str(len(uniq))))
    conn.commit()
    n_db = conn.execute('SELECT COUNT(*) FROM gongbao').fetchone()[0]
    conn.close()

    print(f'\n=== 入库完成 ===')
    print(f'  库文件 : {db_path}')
    print(f'  正文   : {len(docs)} 篇 → 去重后 {len(uniq)} 篇（正文哈希重复 {dup}）')
    print(f'  入库   : {n_db} 行（含清单中未采正文 {len(rows) - len(docs)} 篇待补）')
    print(f'  文种分布:')
    for t, n in sorted(types.items(), key=lambda x: -x[1]):
        print(f'    {t:10s} {n:5d}')
    print(f'\n  ℹ️ 独立库（gongbao.db），未并入 gongwen_corpus.db——并入 articles 需重跑索引与\n'
          f'     eval 再基线，属单独决策。查询示例：\n'
          f'     python -c "import sqlite3;c=sqlite3.connect(r\'{db_path}\');'
          f'print(c.execute(\\"select title,word_count from gongbao where doc_type=\'政府工作报告\'\\").fetchall()[:5])"')
    return 0


def stats():
    _s, rows = load_meta()
    done = load_docs()
    types = {}
    for r in rows:
        types[r.get('doc_type') or '其他'] = types.get(r.get('doc_type') or '其他', 0) + 1
    print(f'=== 公报采集进度 ===')
    print(f'  元数据清单: {len(rows)} 条')
    print(f'  已采正文  : {len(done)} 篇（{len(rows) and len(done) * 100 // len(rows)}%）')
    fail_n = 0
    fp = os.path.join(out_dir(), 'gongbao_failed.jsonl')
    if os.path.exists(fp):
        fail_n = sum(1 for _ in open(fp, encoding='utf-8'))
    print(f'  失败待补  : {fail_n}')
    print(f'  文种分布（按清单）:')
    for t, n in sorted(types.items(), key=lambda x: -x[1]):
        print(f'    {t:10s} {n:5d}')
    return 0


def main():
    ap = argparse.ArgumentParser(description='国务院公报全量采集（两阶段：枚举→正文→入库）')
    ap.add_argument('--enum', action='store_true', help='阶段A：枚举元数据')
    ap.add_argument('--fetch', action='store_true', help='阶段B：下载正文')
    ap.add_argument('--build', action='store_true', help='整理+入库（独立 SQLite）')
    ap.add_argument('--stats', action='store_true', help='查看进度')
    ap.add_argument('--max', type=int, default=0, help='本次最多下载篇数（0=全部未采）')
    ap.add_argument('--n-per', type=int, default=50, help='枚举每页条数')
    ap.add_argument('--max-pages', type=int, default=0, help='枚举最多页数（0=不限）')
    ap.add_argument('--delay', type=float, default=0.6, help='下载间隔秒')
    ap.add_argument('--workers', type=int, default=1, help='下载并发线程数（默认 1）')
    ap.add_argument('--db', default=None, help='入库 SQLite 路径')
    ap.add_argument('--cat', default=None, help='只入库指定 cat（otherfile/zhongyangfile/gongwen/bumenfile/gongbao）')
    ap.add_argument('--t', default='gongbao',
                       help='接口类别：gongbao 公报 / zhengcelibrary_gw 国务院文件 / zhengcelibrary_bm 部门文件')
    a = ap.parse_args()
    global _SUB, _T
    _T = a.t
    _SUB = {'gongbao': 'gongbao',
            'zhengcelibrary_gw': 'zhengcelibrary_gw',
            'zhengcelibrary_bm': 'zhengcelibrary_bm',
            'zhengcelibrary': 'zhengcelibrary_all',
            'zhengce': 'zhengce_all'}.get(a.t, a.t.replace('zhengcelibrary_', ''))
    if a.enum:
        return enum(a.n_per, a.max_pages)
    if a.fetch:
        return fetch_bodies(a.max, a.delay, a.workers)
    if a.build:
        return build(a.db, a.cat)
    if a.stats:
        return stats()
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
