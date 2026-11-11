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
"""求是增量爬虫 v1.0（方案B，2026-09-01，基于 crawl_qiushi_fill.py 精简）
抓取最新期次文章入库（url 去重）→ 可选重建索引
用法: python crawl_qiushi_incremental.py [--rebuild] [--plan]
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
SEED_2025_01 = "https://www.qstheory.cn/20250101/f1fa7777504340aa8e6609e602eed4d1/c.html"
SEED_2025_LAST = "https://www.qstheory.cn/20251231/2d916da295774130ac2fb223fd208895/c.html"

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

def extract_issue_guides(html):
    guides = {}
    pairs = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S)
    for u, t in pairs:
        t = re.sub(r'<[^>]+>', '', t).strip()
        m = re.search(r'(\d{4})年第(\d+)期', t)
        if m:
            y, n = int(m.group(1)), int(m.group(2))
            if u.startswith('//'):
                u = 'https:' + u
            elif u.startswith('/'):
                u = BASE + u
            guides[(y, n)] = u
    return guides

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
    paras = re.findall(r'<p[^>]*>(.*?)</p>', html, re.S)
    clean = []
    for p in paras:
        txt = re.sub(r'<[^>]+>', '', p).strip()
        if len(txt) > 10:
            clean.append(txt)
    r['content'] = '\n\n'.join(clean)
    r['word_count'] = len(r['content'])
    return r

def check_rewrites(limit=0, fix=False):
    """URL 不变但内容被改写的检测（v7.5.1 · C5④ 落地）

    背景：本爬虫原先只按 `if url in existing: continue` 判重，**URL 不变而正文被改写
    （刊物线上勘误、正文替换、栏目重排）永远发现不了**。assets.json 的 ops.freshness
    却声称"URL 不变内容变更可检测"——该声明此前是假的，本函数把它做成真的。

    做法：对既有 URL 抽样重抓，与 freshness.py 的哈希边车逐条比对。
      limit  重抓上限（0=全部；首次核查建议先用 200 试量）
      fix    确认变更后是否回写库内正文与边车哈希（默认只报不改）

    注意：这是**周/月度核查任务**，不是每次增量都跑——全量重抓 5,800+ 篇有明显网络开销。
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import freshness as FR

    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT url, content FROM articles WHERE data_source='求是杂志' "
        "AND content IS NOT NULL AND content<>'' ORDER BY id DESC").fetchall()
    conn.close()
    if limit and limit > 0:
        rows = rows[:limit]
    d = FR.load_hashes()
    known = d['hashes']
    if not known:
        print('[!] 哈希边车为空，先跑: python datahub/scripts/qs/freshness.py --hash-init')
        return 1

    print(f'[*] 改写核查：待检 {len(rows)} 篇（边车覆盖 {len(known)}）')
    n_changed, n_same, n_fail, n_nohash = [], 0, 0, 0
    for i, (url, old_content) in enumerate(rows, 1):
        if url not in known:
            n_nohash += 1
            continue
        h = fetch(url)
        if not h:
            n_fail += 1
            continue
        p = parse_article(h)
        new_hash = FR.content_hash(p.get('content') or '')
        if new_hash == known[url]:
            n_same += 1
        else:
            n_changed.append({'url': url, 'title': p.get('title') or '',
                              'old_chars': len(old_content or ''),
                              'new_chars': len(p.get('content') or '')})
            if fix:
                conn = sqlite3.connect(DB)
                conn.execute('UPDATE articles SET content=?, word_count=?, crawl_time=? WHERE url=?',
                             (p['content'], p['word_count'], datetime.now().isoformat(), url))
                conn.commit(); conn.close()
                known[url] = new_hash
        if i % 50 == 0:
            print(f'    … 已检 {i}/{len(rows)}（变更 {len(n_changed)}）')
        time.sleep(0.2)

    if fix and n_changed:
        d['hashes'] = known
        d['meta']['rewrites_applied'] = d['meta'].get('rewrites_applied', 0) + len(n_changed)
        d['meta']['last_rewrite_scan'] = datetime.now().isoformat(timespec='seconds')
        FR.save_hashes(d)

    print('\n=== 改写核查完成 ===')
    print(f'  相同 {n_same} ｜ **内容已改写 {len(n_changed)}** ｜ 抓取失败 {n_fail} ｜ 边车无记录 {n_nohash}')
    for c in n_changed[:20]:
        print(f'   ⚠️  {c["title"][:34]:34s} {c["old_chars"]}字 → {c["new_chars"]}字  {c["url"][:70]}')
    if n_changed and not fix:
        print('\n  提示：加 --fix-rewrites 可回写库内正文与边车（默认只报不改，避免误覆盖人工修订）。')
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rebuild', action='store_true', help='抓取后重建索引')
    ap.add_argument('--plan', action='store_true', help='仅列出待抓期次')
    ap.add_argument('--check-rewrites', type=int, metavar='N', default=None,
                    help='仅做"URL 不变内容改写"核查，重抓最近 N 篇（N=0 全部）后退出')
    ap.add_argument('--fix-rewrites', action='store_true',
                    help='核查发现改写时回写库内正文与边车哈希（默认只报不改）')
    args = ap.parse_args()

    if args.check_rewrites is not None:
        return check_rewrites(args.check_rewrites, args.fix_rewrites)

    conn0 = sqlite3.connect(DB)
    existing = set(r[0] for r in conn0.execute('SELECT url FROM articles WHERE data_source="求是杂志"'))
    conn0.close()
    print(f"[*] 库内已有求是URL: {len(existing)}")

    issues = {}
    for seed in (SEED_2025_01, SEED_2025_LAST):
        h = fetch(seed)
        if not h:
            print(f"[!] 种子页失败: {seed[-30:]}")
            continue
        g = extract_issue_guides(h)
        print(f"[*] 种子 {seed[-30:]} -> {len(g)} 期次")
        issues.update(g)
    issues[(2025, 1)] = SEED_2025_01
    issues = {k: v for k, v in sorted(issues.items())}
    print(f"[*] 合计期次: {len(issues)}")

    total_new = total_skip = 0
    for (y, n), guide in issues.items():
        h = fetch(guide)
        if not h:
            print(f"[!] 目录页失败 {y}/{n}")
            continue
        arts = extract_articles(h)
        if args.plan:
            print(f"  [PLAN] {y}/{n}: {len(arts)} 篇")
            continue
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
        print(f"  [DONE] {y}/{n}: 本期新增 {iss_new} 篇")
    print(f"\n=== 增量完成：新增 {total_new} 篇，跳过已存在 {total_skip} 篇 ===")

    if args.rebuild and total_new > 0:
        print("[*] 重建索引...")
        sys.path.insert(0, os.path.dirname(os.path.abspath(DB)))
        from qiushi_engine import SemanticSearch, INDEX_PATH
        ss = SemanticSearch()
        ss.build_index()
        print(f"[*] 索引重建完成: {len(ss.article_ids)} 篇")
        # v6.9.0：FTS 快路增量联动（articles_fts 补新行，不重建全表）
        try:
            print("[*] FTS 快路增量同步...")
            import rebuild_fts
            rebuild_fts.incremental()
            print("[*] FTS 增量完成")
        except Exception as _e:
            print(f"[!] FTS 增量失败（快路将降级，可手动 python rebuild_fts.py）: {_e}")

if __name__ == '__main__':
    main()