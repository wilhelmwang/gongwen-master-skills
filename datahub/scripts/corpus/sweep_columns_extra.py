# -*- coding: utf-8 -*-
"""第二批栏目配置（2026-09-13 第二轮发现子 agent 逐一实抓验证，48 个）

由 sweep_columns.py 在 COLUMNS 之后 extend。字段：(key, doc_type, 列表URL, 标题过滤词, 翻页深度)
标题过滤词 None = 链接形态启发式（栏目本身即该文种专栏时用）。

注意：昆明/哈尔滨的详情链接无 .html 后缀（32位hash 直路径 / c01_{id}），
detect_items 已放宽接受这类形态。
"""

EXTRA = [
 # ---- 工作报告（22）----
 ('bt_report', '工作报告', 'https://www.baotou.gov.cn/zfxxgk/zfgzbg/', ['报告'], 12),
 ('wh_report', '工作报告', 'https://www.wuhan.gov.cn/zfgzbg/', ['报告'], 12),
 ('jn_report', '工作报告', 'https://www.jinan.gov.cn/zfgzbg/', ['报告'], 12),
 ('zy_report', '工作报告', 'https://www.zunyi.gov.cn/zwgk/zfgzbg/', ['报告'], 12),
 ('yt_report2', '工作报告', 'https://www.yantai.gov.cn/zfgzbg/', ['报告'], 12),
 ('km_report', '工作报告', 'https://www.km.gov.cn/zfxxgk/fdzdgknr/zfgzbg/', ['报告'], 12),
 ('yc_report', '工作报告', 'https://www.yinchuan.gov.cn/xxgk/szf/zfgzbg_68781/', ['报告'], 12),
 ('sy_report', '工作报告', 'https://www.sanya.gov.cn/sanyasite/zfgzbg/simple_list.shtml', ['报告'], 12),
 ('gz_report2', '工作报告', 'https://www.ganzhou.gov.cn/zwgk/zfgzbg/', ['报告'], 15),
 ('qd_report', '工作报告', 'http://www.qingdao.gov.cn/zwgk/zdgk/ghjh/zfgzbg/', ['报告'], 12),
 ('bj_report2', '工作报告', 'https://www.bijie.gov.cn/zwgk/zfgzbg/', ['报告'], 12),
 ('cz_report', '工作报告', 'https://www.changzhou.gov.cn/zwgk/zfgzbg/', ['报告'], 12),
 ('sz_report2', '工作报告', 'https://www.suzhou.gov.cn/zwgk/zfgzbg/', ['报告'], 12),
 ('yz_report', '工作报告', 'https://www.yangzhou.gov.cn/zwgk/zfgzbg/', ['报告'], 12),
 ('yl_report', '工作报告', 'https://www.yl.gov.cn/zwgk/zfgzbg/', ['报告'], 12),
 ('zj_report', '工作报告', 'https://www.zhanjiang.gov.cn/zfgzbg/', ['报告'], 12),
 ('hrb_report', '工作报告', 'https://www.harbin.gov.cn/haerbin/c104564/navlist.shtml', ['报告'], 12),
 ('yy_report', '工作报告', 'https://www.yueyang.gov.cn/zfgzbg/', ['报告'], 12),
 ('csx_report', '工作报告', 'http://www.csx.gov.cn/zwgk/zfxxgkml/fdzdgknr/qtfdxx/zfgzbg/', ['报告'], 12),
 ('tx_report', '工作报告', 'http://www.tianxin.gov.cn/qzf/zfgzbg/', ['报告'], 12),
 ('gd_report', '工作报告', 'https://www.gd.gov.cn/zwgk/zfgzbg/', ['报告'], 25),
 ('hn_report2', '工作报告', 'https://www.hainan.gov.cn/zwgk/zfgzbg/', ['报告'], 25),
 # ---- 调研报告（17）----
 ('hcrd_research', '调研报告', 'http://www.hbhcrd.gov.cn/e/action/ListInfo/?classid=10', ['调研'], 12),
 ('xgrd_research', '调研报告', 'http://www.xgrd.gov.cn/dcyj/', ['调研'], 12),
 ('esrd_research', '调研报告', 'http://www.esrd.gov.cn/gzyj/', ['调研', '研究'], 12),
 ('jsrdcg_research', '调研报告', 'http://www.jsrd.gov.cn/llyjh/cgjc/', ['调研', '研究'], 25),
 ('jlrd_research', '调研报告', 'http://www.jlrd.gov.cn/cwhgz/gzyj/', ['调研', '研究'], 12),
 ('zyrd_research', '调研报告', 'http://www.zyrd.gov.cn/lldy1.asp', ['调研'], 12),
 ('hhrd_research', '调研报告', 'http://www.hhrd.gov.cn/articles.aspx?id=62', ['调研'], 12),
 ('fxrd_research', '调研报告', 'http://www.fxrd.gov.cn/lfgz/lfdy/', ['调研'], 12),
 ('szrd_research', '调研报告', 'https://www.szrd.gov.cn/v1/llyj/', ['研究'], 12),
 ('npc_research', '调研报告', 'http://www.npc.gov.cn/c2597/zgrmdbdhzdllyjh/', ['研究'], 12),
 ('cppcc_research', '调研报告', 'http://www.cppcc.gov.cn/llyj/', ['研究'], 12),
 ('cppcc_dy', '调研报告', 'http://www.cppcc.gov.cn/zxgz/scdy/', ['调研'], 15),
 ('bjrd2_research', '调研报告', 'https://www.bjrd.gov.cn/xwzx/llyj/', ['研究'], 12),
 ('hnrd_research', '调研报告', 'https://www.hnrd.gov.cn/channel/16083.html', ['研究', '调研'], 12),
 ('nxrd_research', '调研报告', 'http://www.nxrd.gov.cn/rdsc/llysj/index.html', ['研究'], 12),
 ('qhrd_research', '调研报告', 'http://www.qhrd.gov.cn/zyfb/rdgzyj/', ['研究', '调研'], 12),
 ('szzx_research', '调研报告', 'https://www.szzx.gov.cn/szzx/llyjh/', ['调研', '研究'], 12),
 # ---- 工作总结（11）----
 ('szps_summary', '工作总结', 'https://www.szpsq.gov.cn/zwgk/ghjh/ndgzjhjzj/', ['总结'], 15),
 ('szgxj_summary', '工作总结', 'https://gxj.sz.gov.cn/xxgk/xxgkml/ghjh/ndgzjhjzj/', ['总结'], 12),
 ('yz_summary', '工作总结', 'https://www.yangzhou.gov.cn/xxgk/fdzdgknr/ghjh/jhzj/', ['总结'], 12),
 ('sz_summary', '工作总结', 'https://www.suzhou.gov.cn/xxgk/fdzdgknr/ghjh/jhzj/', ['总结'], 12),
 ('cz_summary', '工作总结', 'https://www.changzhou.gov.cn/xxgk/fdzdgknr/ghjh/jhzj/', ['总结'], 12),
 ('gx_summary', '工作总结', 'http://www.ganxian.gov.cn/gxqxxgk/c111122/index.shtml', ['总结'], 8),
 ('zjg_summary', '工作总结', 'https://www.zjg.gov.cn/xxgk/fdzdgknr/ghjh/jhzj/', ['总结'], 12),
 ('tc_summary', '工作总结', 'https://www.taicang.gov.cn/xxgk/fdzdgknr/ghjh/jhzj/', ['总结'], 12),
 ('css_summary', '工作总结', 'https://www.changshu.gov.cn/xxgk/fdzdgknr/ghjh/jhzj/', ['总结'], 12),
 ('yzx_summary', '工作总结', 'https://www.yizheng.gov.cn/xxgk/fdzdgknr/ghjh/jhzj/', ['总结'], 12),
 ('wj_summary', '工作总结', 'https://www.wujiang.gov.cn/xxgk/fdzdgknr/ghjh/jhzj/', ['总结'], 12),
]
