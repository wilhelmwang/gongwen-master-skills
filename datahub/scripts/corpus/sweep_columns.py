#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""栏目源扫荡器（v1.0 · 自动模式发现 + 自动分页探测）

为什么存在：56 个新栏目逐站手写 item_re 不现实（每站 CMS 形态各异）。
本脚本对每个栏目**自动发现**详情链接（标题关键词过滤 + 链接形态启发），
并自动探测常见分页变体（index_N / list_N × shtml/html/htm）。

与 crawl_govdoc_samples.py 的关系：共用其 fetch/清洗/落盘（collected.jsonl），
URL 去重全局一致；本脚本只做"发现"，不做配置。

用法
----
  python sweep_columns.py --list                # 看栏目配置
  python sweep_columns.py --type 会议纪要        # 只扫某类
  python sweep_columns.py --all --pages 12      # 全扫，每栏目最多翻 N 页
  python sweep_columns.py --stats               # 范本池统计
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse

BASE = __import__('os').path.dirname(__file__)                 # datahub/scripts/corpus
PKG = __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.dirname(BASE)))  # 包根
sys.path.insert(0, BASE)
import importlib.util
_spec = importlib.util.spec_from_file_location('cgs', __import__('os').path.join(BASE, 'crawl_govdoc_samples.py'))
cgs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cgs)

sys.path.insert(0, __import__('os').path.join(PKG, 'datahub'))
try:
    from paths import DATA_ROOT as _DR
    OUT_DIR = __import__('os').path.join(_DR, 'govdoc_samples')
except Exception:
    OUT_DIR = __import__('os').path.join(PKG, 'datahub', 'derived', 'govdoc_samples')

NAV_JUNK = ('更多', '首页', '上一页', '下一页', '返回', '打印', '关闭', '字号', '版权',
            '网站地图', '设为首页', '加入收藏', '无障碍', '纠错', '分享', '微信', '微博')

#: 栏目配置：(key, doc_type, 列表URL, 标题过滤词列表(None=按链接形态启发), 建议翻页深度)
COLUMNS = [
 # ---- 会议纪要（22）----
 ('xf_minutes', '会议纪要', 'http://www.xiangyang.gov.cn/szf/zfxxgk/fdzdgknr/qtzdgknr/zfhy/', None, 15),
 ('xz_minutes', '会议纪要', 'https://www.whxinzhou.gov.cn/xxgk_29/xxgkml/qtzdgknr/zfhy/', None, 15),
 ('yyx_minutes', '会议纪要', 'https://yyx.gov.cn/37584/38144/', None, 15),
 ('xtx_minutes', '会议纪要', 'https://www.xtx.gov.cn/6571/20211/20212/', None, 15),
 ('xxs_minutes', '会议纪要', 'http://www.xxs.gov.cn/2252/20218/', None, 15),
 ('zz_minutes', '会议纪要', 'http://www.zhuzhou.gov.cn/c15129/index.html', None, 6),
 ('yb_minutes', '会议纪要', 'https://www.yibin.gov.cn/ztzl/zfxxgk/fdzdgk/zdhy/', None, 12),
 ('ps_minutes', '会议纪要', 'https://www.ybps.gov.cn/zwgk/xzfcwhy/', None, 12),
 ('scxw_minutes', '会议纪要', 'https://www.scxw.gov.cn/xwxqt/zzzq/zfcwhy/', None, 10),
 ('my_minutes', '会议纪要', 'https://www.my.gov.cn/mysrmzf/c100093/list.shtml', ['纪要', '常务会议'], 15),
 ('zy_minutes', '会议纪要', 'https://www.zunyi.gov.cn/zwgk/cwhy/dljsrmzfcwhy/', None, 15),
 ('bj_minutes2', '会议纪要', 'https://www.baoji.gov.cn/col9816/col9817/col9833/col9834/', None, 15),
 ('fc_minutes', '会议纪要', 'https://www.fangcheng.gov.cn/zfxxgk/fdzdgknr/zfhy/zfcwhy/', None, 12),
 ('yt_minutes', '会议纪要', 'https://www.yantai.gov.cn/col/col43362/index.html', None, 10),
 ('gs_minutes', '会议纪要', 'http://www.gusu.gov.cn/gsq/zdhyxxgk/', None, 12),
 ('xunwu_minutes', '会议纪要', 'https://www.xunwu.gov.cn/xwxxxgk/xwqt123/xxgk_list.shtml', None, 15),
 ('ats_minutes', '会议纪要', 'https://www.xjats.gov.cn/xjats/c103911/xxgk_ats_gksx.shtml', None, 15),
 ('hj_minutes2', '会议纪要', 'https://www.xjhj.gov.cn/xjhjx/c115136/zwgk_table.shtml', None, 15),
 ('qx_minutes', '会议纪要', 'http://www.qingxiu.gov.cn/gongkai/fdzdgk/jcxxgk/zfhy/qthyhcwhy/', None, 15),
 ('gl_minutes', '会议纪要', 'https://www.guilin.gov.cn/ywdt/zfhy_2/qthyhcwhy/', None, 20),
 # ---- 工作报告（12，含省级聚合）----
 ('hlj_report', '工作报告', 'https://www.hlj.gov.cn/hlj/szfgzbg/list.shtml', ['报告'], 20),
 ('hn_report', '工作报告', 'https://www.henan.gov.cn/zwgk/zfgzbg/', ['报告'], 20),
 ('yn_report', '工作报告', 'https://www.yn.gov.cn/zwgk/zfxxgk/zfgzbg/', ['报告'], 40),
 ('gz_report', '工作报告', 'https://www.guizhou.gov.cn/zwgk/zfgzbg/', ['报告'], 40),
 ('gp_report', '工作报告', 'http://xxgk.sxgp.gov.cn/gpsrmzf/fdzdgknr/zfgzbg/', ['报告'], 15),
 ('gzhou_report', '工作报告', 'https://www.gz.gov.cn/zwgk/zjgb/zfgzbg/', ['报告'], 12),
 ('lg_report', '工作报告', 'https://www.lg.gov.cn/xxgk/zwgk/zfgzbg/index.html', ['报告'], 12),
 ('wc_report', '工作报告', 'https://www.gdwc.gov.cn/bmzz/wcsrmzfw/zwgk/zfgb/zfgzbg/', ['报告'], 15),
 ('ty_report', '工作报告', 'https://taiyuan.gov.cn/zfgzbg.html', ['报告'], 15),
 ('dg_report', '工作报告', 'https://www.dg.gov.cn/zwgk/zfxxgkml/szfbgs/zfgzbg/', ['报告'], 10),
 ('fz_report', '工作报告', 'https://www.fuzhou.gov.cn/zwgk/zfgzbg/', ['报告'], 15),
 ('sz_report', '工作报告', 'https://www.sz.gov.cn/cn/xxgk/zfxxgj/gzbg/szszf/', ['报告'], 8),
 # ---- 调研/研究（5）----
 ('bjrd_research', '调研报告', 'https://www.bjrd.gov.cn/xwzx/rdgzyj/', ['调研', '研究'], 20),
 ('jsrd_research', '调研报告', 'https://www.jsrd.gov.cn/rdlt/gztt/', ['调研', '视察', '研究'], 40),
 ('hppc_research', '调研报告', 'http://www.hppc.gov.cn/rdgz/jdgz/dysc/', ['调研', '视察'], 20),
 ('lytjj_research', '调研报告', 'https://lytjj.ly.gov.cn/sjjd/lysjjd', ['解读', '分析'], 15),
 ('stats_research', '调研报告', 'https://www.stats.gov.cn/sj/sjjd/', ['解读', '分析', '研究'], 40),
 # ---- 工作总结（7）----
 ('qz_summary2', '工作总结', 'https://www.quanzhou.gov.cn/zfb/xxgk/zfxxgkzl/bgzj/bmgzzj/', ['总结'], 8),
 ('szns_summary', '工作总结', 'https://www.szns.gov.cn/xxgk/qzfxxgkml/ghjh/ndgzjhjzj/', ['总结'], 15),
 ('fgw_summary', '工作总结', 'http://fgw.sz.gov.cn/zwgk/ghjh/ndgzjhjzj/', ['总结'], 6),
 ('szft_summary', '工作总结', 'https://www.szft.gov.cn/xxgk/zwgk/ghjh/ndjh/', ['总结'], 20),
 ('wm_summary', '工作总结', 'https://nnms.gov.cn/gk/fdzdgknr/ghjh/ndjhjzj/', ['总结'], 15),
 ('nxlw_summary', '工作总结', 'https://nxlw.gov.cn/zwgk/zfbmzsjgxxgk/lwszjj_29268/xxgkml_29272/ghjh_29278/', ['总结'], 6),
 ('qx_summary', '工作总结', 'https://www.qingxin.gov.cn/bmxz/bm/qxqnyncj/ghjh/gzjhjzj/', ['总结'], 8),
 # ---- 政务要闻（10，消息类）----
 ('gzqz_news', '消息', 'https://www.gzqz.gov.cn/xwdt/jrtt/', None, 12),
 ('zy_news', '消息', 'https://www.zunyi.gov.cn/xwdt/zyyw/', None, 15),
 ('gz_news', '消息', 'https://www.ganzhou.gov.cn/gzszf/c100021/yw.shtml', None, 20),
 ('xunwu_news', '消息', 'https://www.xunwu.gov.cn/xwxrmzf/c103705/list.shtml', None, 10),
 ('jn_news', '消息', 'https://www.jining.gov.cn/col/col14013/index.html', None, 12),
 ('gl_news', '消息', 'https://www.guilin.gov.cn/ywdt/zwdt/', None, 15),
 ('qx_news', '消息', 'http://www.qingxiu.gov.cn/yaowen/', None, 8),
 ('hn_news', '消息', 'https://www.henan.gov.cn/ywdt/hnyw/', None, 15),
 ('ats_news', '消息', 'https://www.xjats.gov.cn/xjats/c103429/list.shtml', None, 10),
 ('hnyw_news', '消息', 'https://www.hunan.gov.cn/hnszf/hnyw/hnyw.html', None, 20),
]

# 第二批（sweep_columns_extra.py，2026-09-13 第二轮发现，48 个已验证栏目）
try:
    from sweep_columns_extra import EXTRA
    COLUMNS += EXTRA
except ImportError:
    pass

# 第三批（sweep_columns_extra2.py，2026-09-13 调研专项，27 个已验证栏目）
try:
    from sweep_columns_extra2 import EXTRA2
    COLUMNS += EXTRA2
except ImportError:
    pass

# 第四批（sweep_columns_extra3.py，2026-09-13 工作总结专项，40 个已验证栏目）
try:
    from sweep_columns_extra3 import EXTRA3
    COLUMNS += EXTRA3
except ImportError:
    pass

# 第五批（sweep_columns_extra4.py，2026-09-13 政府工作报告专项，15 个站群探测命中）
try:
    from sweep_columns_extra4 import EXTRA4
    COLUMNS += EXTRA4
except ImportError:
    pass

#: 详情链接启发式（kws=None 时用）
_ART_HREF = re.compile(
    r'(20\d{2}[-/]\d{1,2}[-/]\d{1,2}|t20\d{6}_\d+|content[_-]?\d+|post_\d+|'
    r'art[_-]?\d+|/\d{6,}|[0-9a-f]{32}|index[_-]?\d+|\.s?html?)', re.I)

#: 分页候选变体（对栏目 URL 逐一尝试）
def page_variants(list_url, p):
    base = list_url
    outs = []
    stem, ext = os.path.splitext(base)
    if ext in ('.html', '.shtml', '.htm'):
        outs.append(stem + f'_{p}' + ext)
        outs.append(re.sub(r'index[^/]*$', f'index_{p}' + ext, base))
        outs.append(re.sub(r'list[^/]*$', f'list_{p}' + ext, base))
    if base.endswith('/'):
        outs.append(base + f'index_{p}.shtml')
        outs.append(base + f'index_{p}.html')
        outs.append(base + f'list_{p}.shtml')
        outs.append(base + f'index_{p}.htm')
    # 去重
    seen, out = set(), []
    for x in outs:
        if x not in seen:
            seen.add(x); out.append(x)
    return out


def detect_items(html, list_url, kws):
    """从栏目页发现详情链接。kws=None 时按链接形态启发。"""
    import urllib.parse as up
    links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>\s*([^<>]{4,100})\s*</a>', html)
    out = {}
    for href, title in links:
        title = re.sub(r'\s+', '', title)
        if len(title) < 8:
            continue
        if any(x in title for x in NAV_JUNK):
            continue
        if kws is not None and not any(k in title for k in kws):
            continue
        if kws is None and not _ART_HREF.search(href):
            continue
        _clean = (href.split('?')[0] or href)
        _has_ext = re.search(r'\.(s?html?|htm)([?#].*)?$', _clean)
        _hashlike = re.search(r'[0-9a-f]{32}|/c01_\d+|/\d{15,}', _clean)
        if not _has_ext and not _hashlike:
            continue
        full = up.urljoin(list_url, href)
        if full in out:
            continue
        out[full] = title
    return out


def sweep_one(key, doc_type, list_url, kws, pages, delay, seen, max_n=0):
    """max_n：单栏最多下载多少篇（0=不限）。

    为什么需要它：kws=None 时要闻栏目会接受**全部**文章形态链接，
    一个 40 页的 /zwdt/ 栏目能出上千篇，按每篇 1-1.5 秒算单栏要跑几小时。
    实测：61 个栏目跑 3 小时 40 分，一栏都没完成。没有上限这条通道不可用。
    """
    import os as _os
    import collections
    fails = collections.Counter()
    got, failed = 0, 0
    tried_pages = 0
    urls_to_fetch = []
    # 页 1
    try:
        st, h = cgs.fetch(list_url)
        items = detect_items(h, list_url, kws)
    except Exception as e:
        print(f'  [{key}] 列表失败: {str(e)[:60]}', flush=True)
        return 0, 1, collections.Counter()
    urls_to_fetch += list(items.items())
    # 分页终止信号只能是「该页没有条目」，**不能是「该页无新条目」**。
    #
    # 这里踩过两次：
    # ① 原实现「一整页无新条目就 break」——续采时栏目第 1-15 页上次已采过，
    #    第 2 页条目全在 seen 里 → 立刻 break，第 16 页之后的存量永远够不到。
    # ② 改成「连续 3 页无新条目」——仍然错：第 2-15 页整体都是已采存量，
    #    连续 12 页 stale 远超容忍值，照样在第 4 页就停。
    # 实测桂林要闻第 16/20/30 页各有 12-19 条在架，就是这么被漏掉的。
    #
    # 正确做法：老实地按页码往下走，把「已采过」当作正常现象；只有连续 3 页
    # **完全取不到条目**（翻过末尾、或站点对超范围页码返回空）才判定到底。
    # 已采过的条目不会再下载（fresh 过滤），代价只是多取几个列表页。
    stale = 0
    for p in range(2, pages + 1):
        got_any = False
        for cand in page_variants(list_url, p):
            try:
                st, h = cgs.fetch(cand, retries=1)
            except Exception:
                continue
            items = detect_items(h, cand, kws)
            if items:
                got_any = True
            fresh = [(u2, t2) for u2, t2 in items.items() if u2 not in seen and u2 not in dict(urls_to_fetch)]
            if fresh:
                urls_to_fetch += fresh
            time.sleep(0.3)
        if max_n and len(urls_to_fetch) >= max_n:
            break                        # 已够上限，不必再翻页
        tried_pages = p
        if not got_any:
            stale += 1
            if stale >= 3:
                break
        else:
            stale = 0
        time.sleep(delay * 0.5)
    # 下载正文
    ok = 0
    for u2, title in (urls_to_fetch[:max_n] if max_n else urls_to_fetch):
        if u2 in seen:
            continue
        try:
            st, hh = cgs.fetch(u2)
            # raw 是清洗前全文——必须留：清洗判据会改（本项目已改三轮），
            # 只存清洗结果就等于把菜切碎了才后悔，退回不去。raw_text 落 L0。
            raw = cgs.html_to_text(hh)
            body, _dropped = cgs.clean_body(raw)
        except Exception as e:
            failed += 1
            fails[type(e).__name__ + ': ' + str(e)[:40]] += 1
            continue
        if len(body) < 250:                    # 过滤导航空壳/图解页
            failed += 1
            fails[f'正文{len(body)}字'] += 1
            continue
        m = re.search(r'(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})', body[:300])
        rec = dict(key=key, source=key, doc_type=doc_type, title=title, url=u2,
                   pub_date='-'.join(f'{int(x):02d}' for x in m.groups()) if m else '',
                   chars=len(body), chars_raw=len(raw), dropped_lines=_dropped,
                   fetched_at=__import__('datetime').datetime.now().isoformat(timespec='seconds'),
                   raw_text=raw,
                   raw_sha256=hashlib.sha256(raw.encode('utf-8', 'replace')).hexdigest()[:16],
                   clean_version=cgs.CLEAN_VERSION,
                   content=body)
        cgs.append_jsonl(OUT_DIR, rec)
        seen.add(u2)
        got += 1
        ok += 1
        time.sleep(delay)
    return got, failed, fails


def main():
    ap = argparse.ArgumentParser(description='栏目源扫荡器（自动模式发现）')
    ap.add_argument('--type', action='append', default=[], help='只扫某类（可重复）')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--pages', type=int, default=12)
    ap.add_argument('--delay', type=float, default=1.0)
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--stats', action='store_true')
    a = ap.parse_args()

    if a.list:
        for k, d, u, kws, pg in COLUMNS:
            print(f'  {k:16s} {d:6s} pg≤{pg}  {u}')
        return 0
    if a.stats:
        import collections
        D = OUT_DIR
        recs = {}
        fp = os.path.join(D, 'collected.jsonl')
        if os.path.exists(fp):
            for l in open(fp, 'rb'):
                try:
                    r = json.loads(l.decode('utf-8', 'replace'))
                    if r.get('url'):
                        recs[r['url']] = r
                except Exception:
                    pass
        by = collections.defaultdict(list)
        for r in recs.values():
            by[r['doc_type']].append(r['chars'])
        print(f'范本池去重总数: {len(recs)}')
        for t in ('会议纪要', '工作报告', '调研报告', '工作总结', '消息'):
            cs = sorted(by.get(t, []))
            fit = sum(1 for c in cs if 700 <= c <= 2500)
            print(f'  {t:8s} {len(cs):5d} ｜ 700-2500字 {fit:4d} ｜ 中位 {cs[len(cs)//2] if cs else 0}')
        return 0

    seen = set()
    import os as _os
    fp = _os.path.join(OUT_DIR, 'collected.jsonl')
    if _os.path.exists(fp):
        for l in open(fp, 'rb'):
            try:
                r = json.loads(l.decode('utf-8', 'replace'))
                if r.get('url'):
                    seen.add(r['url'])
            except Exception as e:
                if len(seen) == 0 and '[shown]' not in dir():
                    print('[baseline-首行异常]', repr(str(e))[:120], flush=True)
                    globals()['_shown'] = True
    print(f'去重基线: {len(seen)}', flush=True)
    todo = [(k, d, u, kws, pg) for k, d, u, kws, pg in COLUMNS
            if a.all or (a.type and d in a.type)]
    total = 0
    for k, d, u, kws, pg in todo:
        got, failed, fails = sweep_one(k, d, u, kws, min(pg, a.pages), a.delay, seen)
        total += got
        print(f'  [{k}] +{got}（失败 {failed}）', flush=True)
        for why, n in fails.most_common(3):
            print(f'        ↳ {n:3d} × {why}', flush=True)
    print(f'\n=== 扫荡完成：新增 {total} 篇 ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
