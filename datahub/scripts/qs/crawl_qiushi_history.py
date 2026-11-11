import os

def _find_root():
    import os
    p = os.path.dirname(os.path.abspath(__file__))
    while not os.path.exists(os.path.join(p, 'VERSION')) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    return p

_DATA_ROOT = os.path.join(_find_root(), 'datahub')
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""求是历史期次补抓 v1.0（方案A，2026-09-01）
输入期次页 URL 列表 → 逐期抓文章入库（url 去重，复用 crawl_qiushi_fill 逻辑）
用法: python crawl_qiushi_history.py --issues "2018,1,https://...|2018,2,https://..." [--rebuild]
"""
import sqlite3, os, re, time, sys, argparse
from datetime import datetime
import urllib.request, ssl

# v7.3.1：TLS 校验默认开启（原为无条件 CERT_NONE —— 抓取链路可被中间人替换内容）。
# 若目标站证书链在本机环境不可信且无法修复，可显式设 GONGWEN_INSECURE_TLS=1 退回不校验（自担风险）。
def _ssl_ctx():
    ctx = ssl.create_default_context()
    if os.environ.get('GONGWEN_INSECURE_TLS') == '1':
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


ctx = _ssl_ctx()
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

# 数据路径：统一经 datahub/paths.py 解析（v7.3.0 单一事实源）
# 此前指向包内 datahub/sqlite/qs_articles.db —— 该库自 2026-09-09 起为 0 字节占位，抓取会写进空壳。
sys.path.insert(0, _DATA_ROOT)
from paths import db_path
DB = db_path()
BASE = "https://www.qstheory.cn"

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


def fetch(u, retries=3):
    u = _safe_url(u)
    for i in range(retries):
        try:
            req = urllib.request.Request(u, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
                return r.read().decode('utf-8', 'ignore')
        except Exception:
            if i < retries - 1:
                time.sleep(2)
    return None

def extract_articles(html):
    arts = []
    pairs = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S)
    for u, t in pairs:
        t = re.sub(r'<[^>]+>', '', t).strip()
        if not t or len(t) < 4:
            continue
        if re.search(r'\d{4}年第\d+期', t):
            continue
        if t in ('本期导读', '网站声明', '版权声明', '求是网') or '二维码' in t:
            continue
        if '/c.html' not in u and 'c_' not in u:
            continue
        if u.startswith('//'):
            u = 'https:' + u
        elif u.startswith('/'):
            u = BASE + u
        arts.append((t, u))
    return arts

def parse_article(html):
    r = {'title': '', 'author': '', 'source': '', 'publish_date': '', 'content': ''}
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
    if m:
        r['title'] = re.sub(r'<[^>]+>', '', m.group(1)).strip()
    m = re.search(r'来源[：:]\s*([^<\s]+)', html)
    if m:
        r['source'] = m.group(1).strip()
    m = re.search(r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})', html)
    if m:
        r['publish_date'] = f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
    m = re.search(r'作者[：:]\s*([^<\n]+)', html)
    if m:
        r['author'] = m.group(1).strip()
    m = re.search(r'<div class=["\']TRS_Editor["\'][^>]*>(.*?)</div>', html, re.S)
    body = m.group(1) if m else html
    paras = re.findall(r'<p[^>]*>(.*?)</p>', body, re.S)
    clean = []
    for p in paras:
        txt = re.sub(r'<[^>]+>', '', p).strip()
        if len(txt) > 10:
            clean.append(txt)
    r['content'] = '\n\n'.join(clean)
    r['word_count'] = len(r['content'])
    return r

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--issues', required=True, help='期次列表: 年,期,url|年,期,url|...')
    ap.add_argument('--rebuild', action='store_true')
    args = ap.parse_args()

    issues = []
    for seg in args.issues.split('|'):
        parts = seg.split(',')
        issues.append((int(parts[0]), int(parts[1]), parts[2]))

    conn = sqlite3.connect(DB)
    existing = set(r[0] for r in conn.execute('SELECT url FROM articles WHERE data_source="求是杂志"'))
    conn.close()
    print(f"[*] 库内已有求是URL: {len(existing)}")
    print(f"[*] 待抓期次: {len(issues)}")

    total_new = total_skip = 0
    for y, n, guide in issues:
        h = fetch(guide)
        if not h:
            print(f"[!] 期次页失败 {y}/{n}")
            continue
        arts = extract_articles(h)
        iss_new = 0
        for title, url in arts:
            if url in existing:
                total_skip += 1
                continue
            ah = fetch(url)
            if not ah:
                continue
            p = parse_article(ah)
            if not p['title']:
                p['title'] = title
            if p['word_count'] < 80:
                existing.add(url)
                continue
            conn = sqlite3.connect(DB)
            try:
                c = conn.cursor()
                c.execute('''INSERT OR IGNORE INTO articles
                    (title, author, source, publish_date, issue_year, issue_num, url, content, keywords, word_count, data_source, crawl_time)
                    VALUES (?,?,?,?,?,?,?,?,?,?,'求是杂志',?)''',
                    (p['title'], p['author'], p['source'], p['publish_date'], y, n,
                     url, p['content'], '', p['word_count'], datetime.now().isoformat()))
                conn.commit()
                if c.rowcount > 0:
                    total_new += 1
                    existing.add(url)
                    iss_new += 1
            except Exception as e:
                print(f"    [!] 存错 {title[:20]}: {e}")
            finally:
                conn.close()
            time.sleep(0.3)
        print(f"  [DONE] {y}/{n}: 目录 {len(arts)} 篇, 新增 {iss_new}")
    print(f"\n=== 历史补抓完成：新增 {total_new} 篇，跳过 {total_skip} 篇 ===")

    if args.rebuild and total_new > 0:
        print("[*] 重建索引...")
        sys.path.insert(0, os.path.dirname(os.path.abspath(DB)))
        from qiushi_engine import SemanticSearch, INDEX_PATH
        ss = SemanticSearch()
        ss.build_index()
        print(f"[*] 索引重建完成: {len(ss.article_ids)} 篇")

if __name__ == '__main__':
    main()