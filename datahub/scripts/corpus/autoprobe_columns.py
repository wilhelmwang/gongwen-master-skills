#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路径模板批量探测器（v1.0 · 自给自足的源发现）

政府网站路径高度模板化——同类栏目在不同站点常用同一批路径词。
本器把「域名清单 × 路径模板」做笛卡尔积探测，命中即采（不落清单文件，命中行打印在日志里）。

验证口径（吸取软 404 教训）：HTTP 200 且**页面有 ≥3 个标题含目标关键词的静态详情链接**。
只有 200 不算命中——很多站对失效路径返回门户首页。

用法
----
  python autoprobe_columns.py --type 工作总结
  python autoprobe_columns.py --all
  python autoprobe_columns.py --all --dry      # 只探不采
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_columns as sw          # 同目录普通导入（复用 fetch/detect/sweep_one）
try:
    from probe_targets import PORTALS as _PORTALS, DEPTS as _DEPTS
except ImportError:
    _PORTALS, _DEPTS = [], []

#: 地级市政府门户（拼音域名，高置信度的一批）
CITY = [
 'suzhou', 'wuxi', 'changzhou', 'nantong', 'zhenjiang', 'yangzhou', 'yancheng',
 'huaian', 'suqian', 'xuzhou',
 'hangzhou', 'ningbo', 'wenzhou', 'shaoxing', 'jiaxing', 'jinhua', 'huzhou', 'quzhou', 'lishui', 'zhoushan',
 'jinan', 'zibo', 'zaozhuang', 'dongying', 'yantai', 'weifang', 'jining', 'taian', 'weihai', 'rizhao',
 'linyi', 'dezhou', 'liaocheng', 'binzhou', 'heze',
 'zhengzhou', 'kaifeng', 'luoyang', 'pingdingshan', 'anyang', 'hebi', 'xinxiang', 'jiaozuo',
 'puyang', 'xuchang', 'luohe', 'sanmenxia', 'nanyang', 'shangqiu', 'xinyang', 'zhoukou', 'zhumadian',
 'chengdu', 'zigong', 'panzhihua', 'luzhou', 'deyang', 'mianyang', 'guangyuan', 'suining', 'neijiang',
 'leshan', 'nanchong', 'meishan', 'yibin', 'guangan', 'dazhou', 'bazhong', 'ziyang',
 'changsha', 'zhuzhou', 'xiangtan', 'hengyang', 'shaoyang', 'yueyang', 'changde',
 'zhangjiajie', 'yiyang', 'chenzhou', 'yongzhou', 'huaihua', 'loudi',
 'wuhan', 'local', 'shiyan', 'yichang', 'xiangyang', 'ezhou', 'jingmen', 'xiaogan',
 'jingzhou', 'huanggang', 'xianning', 'suizhou',
 'hefei', 'wuhu', 'bengbu', 'huainan', 'maanshan', 'huaibei', 'tongling', 'anqing', 'huangshan',
 'chuzhou', 'fuyang', 'luan', 'bozhou', 'chizhou', 'xuancheng',
 'nanchang', 'jingdezhen', 'pingxiang', 'jiujiang', 'xinyu', 'yingtan', 'ganzhou', 'jian',
 'yichun', 'shangrao',
 'shijiazhuang', 'tangshan', 'qinhuangdao', 'handan', 'xingtai', 'baoding', 'zhangjiakou',
 'chengde', 'cangzhou', 'langfang', 'hengshui',
 'nanning', 'liuzhou', 'guilin', 'wuzhou', 'beihai', 'fangchenggang', 'qinzhou',
 'guigang', 'baise', 'hezhou', 'hechi', 'laibin', 'chongzuo',
 'guiyang', 'liupanshui', 'zunyi', 'anshun', 'bijie', 'tongren',
 'kunming', 'qujing', 'yuxi', 'baoshan', 'zhaotong', 'lijiang', 'puer', 'lincang',
]

#: 三类文种的路径模板（来自已验证站点的共性）
TEMPLATES = {
 '工作总结': [
   '/xxgk/fdzdgknr/ghjh/jhzj/', '/zwgk/fdzdgknr/ghjh/jhzj/',
   '/xxgk/ghjh/ndgzjhjzj/', '/zwgk/ghjh/ndgzjhjzj/', '/xxgk/zwgk/ghjh/ndjh/',
   '/xxgk/zfxxgkzl/bgzj/bmgzzj/', '/zwgk/zfxxgkzl/bgzj/bmgzzj/',
   '/zwgk/fdzdgknr/qtzfxx/gzbg/bmgzzj/', '/gk/fdzdgknr/ghjh/ndjhjzj/',
 ],
 '工作报告': [
   '/zfxxgk/zfgzbg/', '/zwgk/zfgzbg/', '/zfgzbg/', '/xxgk/zfgzbg/',
   '/zwgk/zdgk/ghjh/zfgzbg/', '/zfxxgkml/fdzdgknr/qtfdxx/zfgzbg/',
   '/xxgk/fdzdgknr/zfgzbg/', '/zwgk/zfxxgk/fdzdgknr/zfgzbg/',
 ],
 '调研报告': [
   '/dcyj/', '/gzyj/', '/llyj/', '/llyjh/', '/gztt/', '/scdy/', '/dybg/',
   '/e/action/ListInfo/?classid=10', '/jdgz/dysc/',
 ],
}
KW = {'工作总结': ['总结'], '工作报告': ['工作报告'], '调研报告': ['调研', '研究', '视察']}

#: 调研类域名形态（人大/政协）
RESEARCH_HOSTS = ['{d}rd.gov.cn', 'www.{d}rd.gov.cn', '{d}zx.gov.cn', 'www.{d}zx.gov.cn']


def base_list(dtype):
    """候选基址分组：每组是一个域名的若干主机形态（同域命中后即停，避免重复探测）"""
    groups = []
    if dtype == '调研报告':
        for d in CITY:
            groups.append(['http://' + h.format(d=d) for h in RESEARCH_HOSTS])
    else:
        # 拼音域名（猜）+ 站群挖掘出的真实域名（probe_targets，可靠性高得多）
        for d in CITY:
            groups.append([f'https://www.{d}.gov.cn'])
        for d in _PORTALS:
            groups.append([f'https://www.{d}', f'https://{d}'])
        if dtype == '工作总结':
            for d in _DEPTS:                     # 部门站：瞄部门年度总结
                groups.append([f'https://www.{d}', f'https://{d}'])
    return groups


def probe_one(url, kws):
    """返回 (命中数, 示例)；口径：标题含关键词的静态详情链接数"""
    try:
        st, h = sw.cgs.fetch(url, timeout=15, retries=1)
    except Exception:
        return 0, ''
    items = sw.detect_items(h, url, kws)
    if len(items) < 3:
        return len(items), ''
    ex = next(iter(items.items()))
    return len(items), f'{ex[1][:30]} → {ex[0][:60]}'


def main():
    ap = argparse.ArgumentParser(description='路径模板批量探测器')
    ap.add_argument('--type', action='append', default=[])
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--delay', type=float, default=0.7)
    ap.add_argument('--min-links', type=int, default=3)
    a = ap.parse_args()

    types = a.type if a.type else (list(TEMPLATES) if a.all else [])
    if not types:
        print('指定 --type 或 --all')
        return 2

    seen = set()
    fp = os.path.join(sw.OUT_DIR, 'collected.jsonl')     # 只读，路径为常量
    if os.path.exists(fp):
        for l in open(fp, 'rb'):
            try:
                r = json.loads(l.decode('utf-8', 'replace'))
                if r.get('url'):
                    seen.add(r['url'])
            except Exception:
                pass
    print(f'去重基线: {len(seen)}', flush=True)

    verified = []
    for dtype in types:
        groups = base_list(dtype)
        tpls = TEMPLATES[dtype]
        kws = KW[dtype]
        print(f'\n=== 探测 {dtype}：{len(groups)} 域 × {len(tpls)} 模板 ===', flush=True)
        for grp in groups:
            hit = False
            for base in grp:
                for t in tpls:
                    u = base + t
                    n, ex = probe_one(u, kws)
                    if n >= a.min_links:
                        verified.append((dtype, u, kws, n))
                        print(f'  HIT\t{dtype}\t{n}\t{u}\t{ex[:60]}', flush=True)
                        hit = True
                        break
                    time.sleep(a.delay * 0.35)
                if hit:
                    break
                time.sleep(a.delay * 0.35)
            time.sleep(a.delay * 0.35)

    print(f'\n=== 命中 {len(verified)} 个栏目 ===', flush=True)
    if a.dry:
        return 0

    total = 0
    for dtype, u, kws, _n in verified:
        key = 'auto_' + re.sub(r'\W+', '', u.split('//')[-1])[:26]
        got, failed, fails = sw.sweep_one(key, dtype, u, kws, 10, 0.9, seen)
        total += got
        print(f'  [{key}] +{got}（失败 {failed}）', flush=True)
    print(f'\n=== 探测器采集合计: +{total} 篇 ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
