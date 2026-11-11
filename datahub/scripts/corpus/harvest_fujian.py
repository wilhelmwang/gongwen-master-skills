#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""福建省统一平台关键词收割器（was5 全省站群检索 · v1.0）

为什么存在：一个省级统一检索 API = 全省市县站群。按关键词直接收割五类事务性公文，
比逐个市县找栏目（每个都要逆向 URL 模式）杠杆高一个量级。
实测（2026-09-12）：searchword=常务会议纪要 → 全省命中 99 条。

要点
----
- 响应 JSON 内含未转义控制字符 → json.loads(strict=False)（strict 默认 True 会炸）
- 落盘与 crawl_govdoc_samples.py 同一 collected.jsonl（URL 去重），单线程追加安全
- 正文抽取复用 crawl_govdoc_samples 的通用逻辑
"""
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_samples = os.path.join(BASE, 'datahub', 'scripts', 'corpus', 'crawl_govdoc_samples.py')
sys.path.insert(0, os.path.dirname(_samples))
import importlib.util
_spec = importlib.util.spec_from_file_location('cgs', _samples)
cgs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cgs)

#: 输出目录（与 crawl_govdoc_samples 的 main() 内联逻辑同源；它无独立函数可复用）
sys.path.insert(0, os.path.join(BASE, 'datahub'))
try:
    from paths import DATA_ROOT as _DATA_ROOT
    OUT_DIR = os.path.join(_DATA_ROOT, 'govdoc_samples')
except Exception:
    OUT_DIR = os.path.join(BASE, 'datahub', 'derived', 'govdoc_samples')

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = cgs.UA
API = 'http://www.fujian.gov.cn/was5/web/search'
#: (检索词, 归类文种)
KEYWORDS = [
    ('会议纪要', '会议纪要'),
    ('常务会议纪要', '会议纪要'),
    ('政府工作报告', '工作报告'),
    ('工作总结', '工作总结'),
    ('调研报告', '调研报告'),
]


def search(kw, page=1, prepage=20):
    q = urllib.parse.quote(kw)
    u = f'{API}?channelid=229105&templet=docs.jsp&searchword={q}&prepage={prepage}&page={page}'
    st, h = cgs.fetch(u)
    s = h[h.index('{'):h.rindex('}') + 1]
    return json.loads(s, strict=False)


def main(delay=0.8, pages=12, workers=4):
    # 写自己的 collected_fj.jsonl（主样本文件正被后台链写入，避免双进程并发写同一文件）
    seen = set()
    p = os.path.join(OUT_DIR, 'collected_fj.jsonl')
    for name in ('collected.jsonl', 'collected_fj.jsonl'):
        fp = os.path.join(OUT_DIR, name)
        if os.path.exists(fp):
            for line in open(fp, 'rb'):
                try:
                    seen.add(json.loads(line.decode('utf-8', 'replace'))['url'])
                except Exception:
                    pass
    print(f'已采去重基线: {len(seen)} 条')
    for kw, dtype in KEYWORDS:
        got, page, empty = 0, 1, 0
        while page <= pages:
            try:
                j = search(kw, page)
            except Exception as e:
                print(f'  [{kw}] p{page} ✗ {str(e)[:50]}')
                break
            docs = j.get('docs') or []
            if not docs:
                break
            todo = [(d.get('url') or '', re.sub(r'<[^>]+>|\s+', '', d.get('title') or ''))
                    for d in docs if (d.get('url') or '').startswith('http')]
            todo = [(u2, t) for u2, t in todo if u2 not in seen]
            for u2, title in todo:
                try:
                    st, hh = cgs.fetch(u2)
                    body = cgs.clean_body(cgs.html_to_text(hh))
                except Exception as e:
                    continue
                if len(body) < 100:
                    seen.add(u2)
                    continue
                m = re.search(r'(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})', body[:300])
                pub = '-'.join(f'{int(x):02d}' for x in m.groups()) if m else ''
                rec = dict(key='fj_platform', source='福建省统一平台（was5 站群检索）', doc_type=dtype,
                           title=title, url=u2, pub_date=pub, chars=len(body),
                           chars_raw=len(body), dropped_lines=0,
                           fetched_at=__import__('datetime').datetime.now().isoformat(timespec='seconds'),
                           content=body)
                cgs.append_jsonl(p, rec)
                seen.add(u2)
                got += 1
                time.sleep(delay)
            page += 1
            time.sleep(0.3)
        print(f'  「{kw}」→ {dtype}: +{got} 篇', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
