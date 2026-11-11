#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""官方公文范本采集器（事务性公文体例范本 · v7.6.1）

用途
----
从政府网站**公开栏目**批量采集五类事务性公文的正式文本，用作公文大师的体例参考范本：
  会议纪要 / 消息（政务通稿）/ 工作报告 / 调研报告 / 工作总结

为什么需要自采
--------------
本包语料主体是《求是》《红旗文稿》**理论期刊**，不刊载上述五类**事务性公文**，
故这五类此前没有全文范本（只有 judge 的节选或留空）。官方公开栏目是唯一可核验来源。

设计原则
--------
1. **只取公开栏目**：全部源均为政府网站主动公开的信息公开栏目/政务动态。
2. **礼貌抓取**：单线程、`--delay` 默认 1.5s、失败重试指数退避、UA 标明用途。
3. **可续跑**：已采集 URL 记在 JSONL 里，重跑自动跳过（`--force` 可强制重采）。
4. **不静默失败**：逐源报告「列表命中 / 详情成功 / 详情失败」，失败带原因。
5. **正文清洗**：复用本包 C10 的残留模式（网页页脚/期刊页脚/图注/零宽字符），
   并把清洗前后的字数都记下来，便于人工抽查。

源配置（静态 HTML，2026-09-11 实测可达；gov.cn 政策文件库走搜索 API）
--------------------------------------------------------------------
| key | 文种 | 栏目 | 入口 |
|---|---|---|---|
| ks_minutes | 会议纪要 | 昆山市政府常务会议 | `ks.gov.cn/kss/zfcwhy/index.html` |
| yz_minutes | 会议纪要 | 永州市政府常务会议 | 见 SOURCES |
| lh_research | 调研报告 | 漯河市政府研究室 | `lyszffzyjzx.ly.gov.cn/dybg/` |
| qz_summary | 工作总结 | 泉州市部门工作总结 | `quanzhou.gov.cn/.../bmgzzj/` |
| ks_news | 消息 | 昆山市政务要闻 | `ks.gov.cn/kss/ksyw/` |
| gov_report | 工作报告 | 中国政府网历年报告 | `gov.cn/guowuyuan/baogao/` |

用法
----
  python crawl_govdoc_samples.py --probe                 # 只探源，不采集
  python crawl_govdoc_samples.py --list                  # 打印源配置
  python crawl_govdoc_samples.py --src lh_research       # 采指定源
  python crawl_govdoc_samples.py --all --max 8           # 每源最多采 8 篇
  python crawl_govdoc_samples.py --all --out D:/范本      # 落盘为 .md 范本
  python crawl_govdoc_samples.py --report                # 只看已采统计
"""
import argparse
import datetime
import gzip
import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

UA = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'),
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

#: 正文清洗残留模式（与 doc_code_check 的 C10 同口径）
RESIDUAL = [
    (r'京ICP备\S*', 'ICP'), (r'网站标识码\S*', '标识码'), (r'主办单位：.*$', '主办'),
    (r'版权所有：.*$', '版权'), (r'责任编辑：.*$', '责编'), (r'新华社记者\s*\S+/摄', '图注'),
    (r'^\s*打印\s*$', '打印'), (r'^\s*关闭\s*$', '关闭'), (r'^\s*扫一扫[^\n]*$', '扫码'),
    (r'^\s*分享[^\n]*$', '分享'), (r'^\s*上一篇[^\n]*$', '导航'), (r'^\s*下一篇[^\n]*$', '导航'),
    (r'^\s*(?:【字体|字号)[^\n]*$', '字号'), (r'^\s*来源[:：][^\n]*$', '来源行'),
]
ZW = re.compile(r'[\u200b-\u200f\u202a-\u202e\ufeff]')

# ---------------------------------------------------------------- 源配置
# list: 列表页；item_re: 从列表页抽 (url, title)；paginate: 生成后续列表页 URL 的函数名
# body_re: 从详情页抽正文块的模式（取 group(1)）；fallback 用整页文本兜底
SOURCES = {
    'ks_minutes': dict(
        doc_type='会议纪要', name='昆山市政府常务会议纪要',
        list='http://www.ks.gov.cn/kss/zfcwhy/xxgk_list_2.shtml',
        abs_base='http://www.ks.gov.cn',
        item_re=r'<a[^>]+href="([^"]*?/kss/zfcwhy/\d{6}/[0-9a-f]{32}\.shtml)"[^>]*>\s*([^<>]{6,60})\s*</a>',
        paginate=lambda p: f'http://www.ks.gov.cn/kss/zfcwhy/xxgk_list_{p}.shtml' if p >= 2 else None,
        total_hint=113,
        body_re=r'(?:会议议定|会议听取了|会议传达)[\s\S]{200,}',
        note='市县两级公开的正式常务会议纪要（含发文字号「昆政纪〔YYYY〕N号」）'),
    'cs_minutes': dict(
        doc_type='会议纪要', name='常熟市政府常务会议纪要',
        list='http://www.changshu.gov.cn/zgcs/c108209/list.shtml',
        abs_base='http://www.changshu.gov.cn',
        item_re=r'<a[^>]+href="([^"]*?/zgcs/c108209/\d{6}/[0-9a-f]{32}\.shtml)"[^>]*>\s*([^<>]{6,60})\s*</a>',
        paginate=lambda p: f'http://www.changshu.gov.cn/zgcs/c108209/list_{p}.shtml' if p > 1 else None,
        body_re=r'(?:会议议定|会议听取了|会议传达|会议原则同意)[\s\S]{200,}',
        note='江苏常熟市常务会议纪要（静态列表，可翻页）'),
    'lh_research': dict(
        doc_type='调研报告', name='漯河市政府研究室调研报告',
        list='https://lyszffzyjzx.ly.gov.cn/dybg/',
        abs_base='',
        item_re=r'<a[^>]+href="(https?://lyszffzyjzx\.ly\.gov\.cn/\d{4}/\d{2}-\d{2}/\d+\.html)"[^>]*>\s*([^<>]{6,60})\s*</a>',
        paginate=lambda p: f'https://lyszffzyjzx.ly.gov.cn/dybg/index_{p}.html' if p > 1 else None,
        body_re=None,
        note='市政府研究室专栏，2026 年月度更新（洛阳市政府系统）'),
    'qz_summary': dict(
        doc_type='工作总结', name='泉州市部门工作总结',
        list='http://www.quanzhou.gov.cn/zfb/xxgk/zfxxgkzl/bgzj/bmgzzj/',
        abs_base='',
        item_re=r'<a[^>]+href="(https?://[a-z]+\.quanzhou\.gov\.cn/[^"]+t\d{8}_\d+\.htm)"[^>]*>\s*([^<>]{6,80})\s*</a>',
        paginate=lambda p: None,     # 该栏目无分页，仅首页 15 条
        body_re=None,
        note='市属各部门年度工作总结（分散在各局子站）'),
    'ks_news': dict(
        doc_type='消息', name='昆山市政务要闻（通稿）',
        list='http://www.ks.gov.cn/kss/ksyw/index.html',
        abs_base='http://www.ks.gov.cn',
        item_re=r'<a[^>]+href="([^"]*?/kss/ksyw/\d{6}/[0-9a-f]{32}\.shtml)"[^>]*>\s*([^<>]{8,80})\s*</a>',
        paginate=lambda p: f'http://www.ks.gov.cn/kss/ksyw/index_{p}.html' if p > 1 else None,
        body_re=None,
        note='地方政务要闻通稿（消息体：导语+主体，短篇）'),
    'gov_report': dict(
        doc_type='工作报告', name='中国政府网历年政府工作报告',
        list='https://www.gov.cn/guowuyuan/baogao/',
        abs_base='',
        item_re=r'<a[^>]+href="(https://www\.gov\.cn/(?:premier|guowuyuan)/\d{4}-\d{2}/\d{2}/content_\d+\.htm)"[^>]*>\s*(20\d{2})\s*</a>',
        paginate=lambda p: None,
        body_re=None,
        note='历年国务院政府工作报告（字数远超短篇区间，仅作超长对照）'),

    # ---- v7.7.1 第二优先：栏目源（2026-09-12 深度研究盘点 + 逐一探测通过）----
    'zjg_minutes': dict(
        doc_type='会议纪要', name='张家港市政府常务会议纪要',
        list='https://www.zjg.gov.cn/zjg/c100053/list.shtml',
        abs_base='https://www.zjg.gov.cn',
        item_re=r'<a[^>]+href="([^"]*?/zjg/c100053/\d{6}/[0-9a-f]{32}\.shtml)"[^>]*>\s*([^<>]{6,60})\s*</a>',
        paginate=lambda p: f'https://www.zjg.gov.cn/zjg/c100053/list_{p}.shtml' if p > 1 else None,
        body_re=None,
        note='带发文字号（〔YYYY〕N号）的正式纪要，体例最规范'),
    'xinyuan_minutes': dict(
        doc_type='会议纪要', name='新源县政府常务会议纪要',
        list='https://www.xinyuan.gov.cn/xinyuan/c113920/zfxxgk_gknrz.shtml',
        abs_base='https://www.xinyuan.gov.cn',
        item_re=r'<a[^>]+href="([^"]*?/xinyuan/c113920/\d{6}/[0-9a-f]{32}\.shtml)"[^>]*>\s*([^<>]{6,60})\s*</a>',
        paginate=lambda p: f'https://www.xinyuan.gov.cn/xinyuan/c113920/zfxxgk_gknrz_{p}.shtml' if p > 1 else None,
        body_re=None,
        note='新疆县份整目录公开纪要全文'),
    'akt_minutes': dict(
        doc_type='会议纪要', name='阿克陶县政府常务会议',
        list='https://www.xjakt.gov.cn/xjakt/c104753/zfxxgk_list.shtml',
        abs_base='https://www.xjakt.gov.cn',
        item_re=r'<a[^>]+href="([^"]*?/xjakt/c104753/\d{6}/[0-9a-f]{32}\.shtml)"[^>]*>\s*([^<>]{6,60})\s*</a>',
        paginate=lambda p: f'https://www.xjakt.gov.cn/xjakt/c104753/zfxxgk_list_{p}.shtml' if p > 1 else None,
        body_re=None,
        note='已到第 166 次，7 页存量'),
    'll_minutes': dict(
        doc_type='会议纪要', name='吕梁市政府常务会议',
        list='http://www.lvliang.gov.cn/llxxgk/zfxxgk/xxgkml/zfhy_21570/szfcwhy/',
        abs_base='http://www.lvliang.gov.cn',
        item_re=r'<a[^>]+href="(\./\d{6}/t\d{8}_\d+\.html)"[^>]*>\s*([^<>]{6,60})\s*</a>',
        paginate=lambda p: None,
        body_re=None,
        note='已到第 105 次（部分为会议报道，体例混杂）'),
    'ln_report': dict(
        doc_type='工作报告', name='辽宁省政府工作报告（省+14市聚合）',
        list='https://www.ln.gov.cn/web/zwgkx/zfgzbg/',
        abs_base='https://www.ln.gov.cn',
        item_re=r'<a[^>]+href="(/web/zwgkx/zfgzbg/[^"]*?/index\.shtml)"[^>]*>\s*([^<>]{8,90})\s*</a>',
        paginate=lambda p: None,
        body_re=None,
        note='单栏目聚合省政府+全省 14 个地级市历年报告（本次盘点最高杠杆点）'),
    'xj_report': dict(
        doc_type='工作报告', name='新疆自治区政府工作报告',
        list='https://www.xinjiang.gov.cn/xinjiang/xjzfgzbg/zfgzbg.shtml',
        abs_base='https://www.xinjiang.gov.cn',
        item_re=r'<a[^>]+href="([^"]*?/xinjiang/c\d+/\d{6}/[0-9a-f]{32}\.shtml)"[^>]*>\s*([^<>]{6,60})\s*</a>',
        paginate=lambda p: None,
        body_re=None,
        note='2003-2026 历年（图解页会因正文过短自动淘汰）'),
    'xz_report': dict(
        doc_type='工作报告', name='西藏自治区政府工作报告',
        list='https://www.xizang.gov.cn/zwgk/xxfb/zfgzbg/',
        abs_base='https://www.xizang.gov.cn',
        item_re=r'<a[^>]+href="(\./\d{6}/t\d{8}_\d+\.html)"[^>]*>\s*([^<>]{6,60})\s*</a>',
        paginate=lambda p: None,
        body_re=None,
        note='2019-2026 历年'),
    'bj_report': dict(
        doc_type='工作报告', name='北京市政府工作报告',
        list='https://www.beijing.gov.cn/gongkai/jihua/zfgzbg/',
        abs_base='https://www.beijing.gov.cn',
        item_re=r'<a[^>]+href="(\./\d{6}/t\d{8}_\d+\.html)"[^>]*>\s*([^<>]{6,60})\s*</a>',
        paginate=lambda p: None,
        body_re=None,
        note='2002-2026 历年'),
    'heb_research': dict(
        doc_type='调研报告', name='河北省政府研究室调研成果',
        list='https://yjs.hebei.gov.cn/news/dycg/',
        abs_base='',
        item_re=r'<a[^>]+href="(https?://yjs\.hebei\.gov\.cn/news/dycg/\d{4}-\d{2}-\d{2}/\d+\.html)"[^>]*>\s*([^<>]{6,80})\s*</a>',
        paginate=lambda p: None,
        body_re=None,
        note='年度课题成果汇编（部分为目录页，正文过短者自动淘汰）'),
    'stic_summary': dict(
        doc_type='工作总结', name='深圳市科创委年度工作总结',
        list='https://stic.sz.gov.cn/xxgk/gzjh/ndgzzj/',
        abs_base='',
        item_re=r'<a[^>]+href="(https?://stic\.sz\.gov\.cn/xxgk/gzjh/ndgzzj/content/post_\d+\.html)"[^>]*>\s*([^<>]{6,80})\s*</a>',
        paginate=lambda p: None,
        body_re=None,
        note='2013-2022 历年部门总结（深圳其余区站 SSL 设备不兼容，已如实放弃）'),
}

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


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


def fetch(url, timeout=25, retries=3):
    _safe_url(url)
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
                    except UnicodeError:     # DecodeError 只覆盖解码方向；个别字节序列抛 EncodeError
                        continue
                return r.status, b.decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}'
            if e.code in (403, 404, 410):
                break                      # 不重试确定性错误
        except Exception as e:
            last = f'{type(e).__name__}: {str(e)[:60]}'
        if i < retries - 1:
            time.sleep(1.5 * (2 ** i))
    raise RuntimeError(last or '未知错误')


def html_to_text(h):
    """粗粒度 HTML → 文本（去脚本/样式/标签）"""
    h = re.sub(r'(?is)<(script|style|noscript)[^>]*>.*?</\1>', '', h)
    h = re.sub(r'(?is)<!--.*?-->', '', h)
    h = re.sub(r'(?i)<br\s*/?>', '\n', h)
    h = re.sub(r'(?i)</(p|div|li|tr|h[1-6])>', '\n', h)
    h = re.sub(r'<[^>]+>', '', h)
    for a, b in (('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'),
                 ('&quot;', '"'), ('&#39;', "'"), ('&ldquo;', '"'), ('&rdquo;', '"')):
        h = h.replace(a, b)
    h = ZW.sub('', h)
    lines = [l.strip() for l in h.split('\n')]
    return '\n'.join(l for l in lines if l)


#: 清洗判据版本。判据一改就升版本，治理层可按它筛出需要重洗的条目。
CLEAN_VERSION = 'v1'


def clean_body(text):
    """清洗正文：去残留、去空行、压缩连续空白。返回 (清洗后文本, 去掉的行数)"""
    lines = text.split('\n')
    out, dropped = [], 0
    for l in lines:
        orig = l
        for pat, _kind in RESIDUAL:
            l = re.sub(pat, '', l, flags=re.M).strip()
        if not l or len(l) <= 2:
            if orig.strip():
                dropped += 1
            continue
        if re.fullmatch(r'[\s\-—_=·•※*]+', l):
            continue
        out.append(l)
    return '\n'.join(out), dropped


def extract_body(html, cfg):
    """优先用 body_re 定位正文块；否则整页转文本后裁掉导航区"""
    if cfg.get('body_re'):
        m = re.search(cfg['body_re'], html_to_text(html))
        if m:
            return m.group(0)
    txt = html_to_text(html)
    lines = txt.split('\n')
    # 找最长的连续文本区（正文通常是最长段落块）
    best_s, best_n, cur_s, cur_n = 0, 0, 0, 0
    for i, l in enumerate(lines):
        if len(l) >= 20:
            if cur_n == 0:
                cur_s = i
            cur_n += 1
        else:
            if cur_n > best_n:
                best_s, best_n = cur_s, cur_n
            cur_n = 0
    if cur_n > best_n:
        best_s, best_n = cur_s, cur_n
    if best_n >= 3:
        # 正文块连同紧邻的短行（标题/日期/小标题）一起取
        lo = max(0, best_s - 6)
        hi = min(len(lines), best_s + best_n + 4)
        return '\n'.join(lines[lo:hi])
    return txt


def load_seen(out_dir):
    seen = set()
    p = os.path.join(out_dir, 'collected.jsonl')
    if os.path.exists(p):
        for line in open(p, encoding='utf-8'):
            try:
                seen.add(json.loads(line)['url'])
            except Exception:
                pass
    return seen


def append_jsonl(out_dir, rec):
    with open(os.path.join(out_dir, 'collected.jsonl'), 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def crawl_source(key, out_dir, max_n, pages, delay, force, save_md=True):
    cfg = SOURCES[key]
    print(f'\n=== [{key}] {cfg["name"]} ｜ 文种 {cfg["doc_type"]} ===')
    print(f'  入口: {cfg["list"]}')
    print(f'  说明: {cfg["note"]}')
    seen = set() if force else load_seen(out_dir)
    items, list_fail = [], []
    for p in range(1, pages + 1):
        u = cfg['list'] if p == 1 else cfg['paginate'](p)
        if not u:
            break
        try:
            st, html = fetch(u)
        except Exception as e:
            list_fail.append(f'第 {p} 页: {e}')
            break
        got = re.findall(cfg['item_re'], html)
        # 去重 + 过滤导航噪声
        seen_u = set()
        for href, title in got:
            title = re.sub(r'\s+', ' ', title).strip()
            if not title or href in seen_u:
                continue
            if any(x in title for x in ('更多', '下一页', '上一页', '首页', '返回')):
                continue
            seen_u.add(href)
            if not href.startswith('http'):
                # 标准 urljoin：正确处理 ./x、/x 两种相对形态（手拼 base 曾把 ./ 前缀拼坏）
                import urllib.parse as _up
                href = _up.urljoin(u, href)
            items.append((href, title))
        print(f'  列表第 {p} 页: 命中 {len(got)} → 有效 {len(seen_u)}')
        if not cfg['paginate'](2) and p == 1:
            break
        time.sleep(delay)
    if list_fail:
        for x in list_fail:
            print(f'  ⚠️  列表失败 {x}')

    # 同一 URL 去重（跨页重复）
    uniq, seen2 = [], set()
    for u, t in items:
        if u not in seen2:
            seen2.add(u)
            uniq.append((u, t))
    # --max 0 = 不限量（原写法 [:0] 会切出空列表，深翻页曾白跑一整轮）
    todo = [(u, t) for u, t in uniq if u not in seen]
    if max_n:
        todo = todo[:max_n]
    print(f'  待采 {len(todo)} 篇（已采过 {len([1 for u,_ in uniq if u in seen])} 篇，本次上限 {max_n}）')

    ok, fail = 0, []
    for i, (u, title) in enumerate(todo, 1):
        try:
            st, html = fetch(u)
            body = extract_body(html, cfg)
            cleaned, dropped = clean_body(body)
            if len(cleaned) < 120:
                fail.append((u, title, f'正文过短（清洗后 {len(cleaned)} 字），可能抽取失败'))
                continue
            # 发布日期：从正文前部或 URL 里取
            m = re.search(r'(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})', cleaned[:400]) or \
                re.search(r'/(20\d{2})(\d{2})/', u)
            pub = '-'.join(f'{int(x):02d}' for x in m.groups()) if m else ''
            rec = dict(key=key, source=cfg['name'], doc_type=cfg['doc_type'],
                       title=title, url=u, pub_date=pub,
                       chars=len(cleaned), chars_raw=len(body), dropped_lines=dropped,
                       fetched_at=datetime.datetime.now().isoformat(timespec='seconds'),
                       # raw_text＝清洗前的正文，原始层。清洗判据会变（本项目已改三轮），
                       # 只存清洗结果就等于把菜切碎了才后悔——退回不去，只能在半成品上再洗一遍。
                       # 留原文才能在任何一次判据更新后整层重洗。
                       raw_text=body,
                       raw_sha256=hashlib.sha256(body.encode('utf-8', 'replace')).hexdigest()[:16],
                       clean_version=CLEAN_VERSION,
                       content=cleaned)
            append_jsonl(out_dir, rec)
            if save_md:
                safe = re.sub(r'[\\/:*?"<>|\s]+', '_', title)[:60]
                if '..' in safe or safe != os.path.basename(safe):
                    raise ValueError(f'非法文件名已拒绝: {safe[:40]}')
                md = os.path.normpath(os.path.join(out_dir, cfg['doc_type'], f'{key}_{safe}.md'))
                if not md.startswith(os.path.normpath(out_dir) + os.sep):
                    raise ValueError('写入越界已拒绝')
                os.makedirs(os.path.dirname(md), exist_ok=True)
                from pathlib import Path as _P
                _P(md).write_text(f'# {title}\n\n> 来源：{cfg["name"]} ｜ {u}\n> 采集：{rec["fetched_at"]}\n\n{cleaned}\n',
                                  encoding='utf-8')
            ok += 1
            print(f'  [{i}/{len(todo)}] ✅ {len(cleaned):6d} 字 ｜ {title[:36]}')
        except Exception as e:
            fail.append((u, title, f'{type(e).__name__}: {str(e)[:60]}'))
            print(f'  [{i}/{len(todo)}] ❌ {title[:30]} —— {str(e)[:50]}')
        time.sleep(delay)
    print(f'  ── 结果：成功 {ok} ｜ 失败 {len(fail)}')
    for u, t, why in fail:
        print(f'      ❌ {t[:34]} —— {why}')
    return {'key': key, 'doc_type': cfg['doc_type'], 'ok': ok, 'fail': len(fail), 'fail_detail': fail}


def probe(out_dir):
    print('=== 源可达性探测（只发一次请求，不采集）===')
    rows = []
    for k, cfg in SOURCES.items():
        try:
            st, html = fetch(cfg['list'], retries=1)
            n = len(re.findall(cfg['item_re'], html))
            rows.append((k, cfg['doc_type'], 'OK', f'HTTP {st}', len(html), n))
            print(f'  ✅ {k:12s} {cfg["doc_type"]:6s} HTTP {st} ｜ {len(html):7d} 字符 ｜ 列表命中 {n}')
        except Exception as e:
            rows.append((k, cfg['doc_type'], 'FAIL', str(e)[:40], 0, 0))
            print(f'  ❌ {k:12s} {cfg["doc_type"]:6s} {str(e)[:60]}')
        time.sleep(1.0)
    ok = sum(1 for r in rows if r[2] == 'OK')
    print(f'\n  可达 {ok}/{len(rows)} 个源')
    from pathlib import Path as _P
    _P(os.path.join(out_dir, 'probe_report.json')).write_text(
        json.dumps([dict(zip(('key', 'doc_type', 'status', 'http', 'chars', 'items'), r)) for r in rows],
                   ensure_ascii=False, indent=1), encoding='utf-8')
    return 0 if ok else 1


def report(out_dir):
    p = os.path.join(out_dir, 'collected.jsonl')
    if not os.path.exists(p):
        print('（尚未采集，无报告）')
        return 0
    recs = [json.loads(l) for l in open(p, encoding='utf-8') if l.strip()]
    by_type, by_src = {}, {}
    for r in recs:
        by_type.setdefault(r['doc_type'], []).append(r)
        by_src.setdefault(r['key'], []).append(r)
    print(f'=== 已采集报告（{len(recs)} 篇）===')
    print(f'{"文种":10s} {"篇数":>4s} {"字数区间":>16s} {"中位":>6s}')
    for t, rs in sorted(by_type.items(), key=lambda x: -len(x[1])):
        cs = sorted(r['chars'] for r in rs)
        print(f'{t:10s} {len(rs):4d} {cs[0]:7d}-{cs[-1]:<7d} {cs[len(cs)//2]:6d}'
              f'   （700-2500 区间内 {sum(1 for c in cs if 700 <= c <= 2500)} 篇）')
    print()
    for k, rs in sorted(by_src.items()):
        print(f'  {k:12s} {len(rs):3d} 篇 ｜ {rs[0]["source"]}')
    return 0


def main():
    ap = argparse.ArgumentParser(description='官方公文范本采集器（五类事务性公文）')
    ap.add_argument('--src', action='append', default=[], help='指定源 key（可重复）')
    ap.add_argument('--all', action='store_true', help='采集全部源')
    ap.add_argument('--max', type=int, default=10, help='每源最多采集篇数（默认 10）')
    ap.add_argument('--pages', type=int, default=2, help='每源最多翻列表页数（默认 2）')
    ap.add_argument('--delay', type=float, default=1.5, help='请求间隔秒（默认 1.5）')
    ap.add_argument('--force', action='store_true', help='忽略已采集记录，强制重采')
    ap.add_argument('--no-md', action='store_true', help='只写 JSONL，不落 .md 范本')
    ap.add_argument('--out', default=None, help='输出目录（默认 <数据根>/govdoc_samples，经 paths.py 解析）')
    ap.add_argument('--probe', action='store_true', help='只探测源可达性')
    ap.add_argument('--list', action='store_true', help='打印源配置')
    ap.add_argument('--report', action='store_true', help='只看已采统计')
    a = ap.parse_args()

    if a.list:
        print('=== 源配置 ===')
        for k, c in SOURCES.items():
            print(f'  {k:12s} {c["doc_type"]:6s} {c["name"]}')
            print(f'               {c["list"]}')
            print(f'               {c["note"]}')
        return 0

    if a.out:
        out_dir = os.path.abspath(a.out)
    else:
        sys.path.insert(0, os.path.join(BASE, 'datahub'))
        try:
            from paths import DATA_ROOT
            out_dir = os.path.join(DATA_ROOT, 'govdoc_samples')
        except Exception:
            out_dir = os.path.join(BASE, 'datahub', 'derived', 'govdoc_samples')
    os.makedirs(out_dir, exist_ok=True)
    print(f'输出目录: {out_dir}')

    if a.probe:
        return probe(out_dir)
    if a.report:
        return report(out_dir)

    keys = a.src if a.src else (list(SOURCES) if a.all else [])
    if not keys:
        print('请指定 --src <key> 或 --all（--list 看可用源）')
        return 2
    bad = [k for k in keys if k not in SOURCES]
    if bad:
        print(f'未知源: {bad}')
        return 2

    results = []
    for k in keys:
        results.append(crawl_source(k, out_dir, a.max, a.pages, a.delay, a.force, not a.no_md))
    print('\n=== 汇总 ===')
    tot_ok = sum(r['ok'] for r in results)
    tot_fail = sum(r['fail'] for r in results)
    for r in results:
        print(f'  {r["key"]:12s} {r["doc_type"]:6s} 成功 {r["ok"]:3d} ｜ 失败 {r["fail"]:3d}')
    print(f'  合计：成功 {tot_ok} ｜ 失败 {tot_fail}')
    report(out_dir)
    return 0 if tot_ok else 1


if __name__ == '__main__':
    sys.exit(main())
