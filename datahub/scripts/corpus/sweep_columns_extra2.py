# -*- coding: utf-8 -*-
"""第三批栏目配置：调研报告专项（2026-09-13 子 agent 逐一实抓验证，27 个）

来源：调研发现子 agent（配额恢复后第一件事）。该轮搜索引擎全部失效
（Bing 忽略 site:、Baidu/搜狗反爬、360/DDG 空返回），改由 AliDNS DoH 解析 + 直连爬取完成验证。
字段：(key, doc_type, 列表URL, 标题过滤词, 翻页深度)
"""

EXTRA2 = [
 # --- 广州市人大（同站 8 个栏目，post_{id} 形态，index_N.html 分页）---
 ('gzpc_dyyts',    '调研报告', 'https://gzpc.gov.cn/rdlz/dyyts/index.html',      ['调研', '研究', '视察'], 8),
 ('gzpc_jdgz',     '调研报告', 'https://gzpc.gov.cn/rdlz/jdgz/index.html',       ['调研', '研究', '视察'], 6),
 ('gzpc_yjs',      '调研报告', 'https://gzpc.gov.cn/jgzy/yjs/index.html',        ['调研', '研究', '视察'], 2),
 ('gzpc_nszgw',    '调研报告', 'https://gzpc.gov.cn/jgzy/nszgw/index.html',      ['调研', '研究', '视察'], 2),
 ('gzpc_jkwwzgw',  '调研报告', 'https://gzpc.gov.cn/jgzy/jkwwzgw/index.html',    ['调研', '研究', '视察'], 2),
 ('gzpc_shjsgw',   '调研报告', 'https://gzpc.gov.cn/jgzy/shjsgw/index.html',     ['调研', '研究', '视察'], 2),
 ('gzpc_ncnyzgw',  '调研报告', 'https://gzpc.gov.cn/jgzy/ncnyzgw/index.html',    ['调研', '研究', '视察'], 2),
 ('gzpc_cjzgw',    '调研报告', 'https://gzpc.gov.cn/jgzy/cjzgw/index.html',      ['调研', '研究', '视察'], 2),
 # --- 地市州人大 ---
 ('hhrd_dy',       '调研报告', 'https://hhrd.gov.cn/articles.aspx?id=62',        ['调研', '研究', '视察'], 2),
 ('ztrd_ts',       '调研报告', 'https://www.ztrd.gov.cn/c/news/list/c1091/p1_20_0_false.shtml', ['调研', '研究', '视察'], 2),
 ('gzlps_rdyw',    '调研报告', 'https://srd.gzlps.gov.cn/xwzx/rdyw/',            ['调研', '研究', '视察'], 2),
 ('zyrd_jdgz',     '调研报告', 'https://renda.zunyi.gov.cn/gzdt/jdgz/',          ['调研', '研究', '视察'], 2),
 ('asrd_kt',       '调研报告', 'http://www.asrd.gov.cn/jxhfzqgcrnnzassjktyj/index.html', ['调研', '研究', '视察'], 2),
 ('qdnrd_zfjc',    '调研报告', 'http://www.qdnrd.gov.cn/zfjc/index.jhtml',       ['调研', '研究', '视察'], 2),
 ('xtrd_list',     '调研报告', 'http://www.xtrd.gov.cn/?list_13/',              ['调研', '研究', '视察'], 2),
 ('gysrd_jddt',    '调研报告', 'http://www.gysrd.gov.cn/jdzx/jddt/',            ['调研', '研究', '视察'], 2),
 # --- 省级人大 ---
 ('gxrd_diaoyan',  '调研报告', 'https://www.gxrd.gov.cn/html/more924.html',     ['调研', '研究', '视察'], 2),
 ('gxrd_xunwen',   '调研报告', 'https://www.gxrd.gov.cn/html/more925.html',     ['调研', '研究', '视察'], 2),
 ('gxrd_daibiao',  '调研报告', 'https://www.gxrd.gov.cn/html/more1368.html',    ['调研', '研究', '视察'], 2),
 ('scspc_gdll',    '调研报告', 'https://www.scspc.gov.cn/gdll/',                ['调研', '研究', '视察'], 18),
 ('hljrd_cl16',    '调研报告', 'https://hljrd.gov.cn/content_list.html?id=16',  ['调研', '研究', '视察'], 2),
 ('gzrd_zhbd',     '调研报告', 'https://www.gzrd.gov.cn/gzdt/jdgz/zhbd/',       ['调研', '研究', '视察'], 2),
 ('hainanpc_11',   '调研报告', 'http://hainanpc.gov.cn/hainanpc/11/index.html', ['调研', '研究', '视察'], 2),
 # --- 政协 ---
 ('hnzx_scdy',     '调研报告', 'https://www.hnzx.gov.cn/zxgz/scdy/',            ['调研', '研究', '视察'], 2),
 ('hnzx_ysxs',     '调研报告', 'https://www.hnzx.gov.cn/ysxs/',                 ['调研', '研究', '视察'], 2),
 ('gzszx_zwhgz',   '调研报告', 'https://www.gzszx.gov.cn/zxgz/zwhgz/index.shtml', ['调研', '研究', '视察'], 2),
 ('sdzx_ch00326',  '调研报告', 'http://www.sdzx.gov.cn/channels/ch00326/',      ['调研', '研究', '视察'], 2),
]
