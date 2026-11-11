# -*- coding: utf-8 -*-
"""第四批栏目配置：工作总结专项（2026-09-13 子 agent 三轮回采集验证，40 个）

方法论（子 agent 实测，供后续轮次复用）：
- 最高效路径：搜「XX局工作总结」拿详情页 → 从详情页面包屑/导航找到「计划总结」栏目 URL
- 浙江系（col/colXXXX）可由详情 art_XXXX_*.html 反推出 /col/colXXXX/index.html
- 命中率最高的 5 个路径词：ghjh/bmjhzj、ghjh/ndgzjhhzj、ghjh/NDJH、jhzj、ndgzjhjzj
- 检索通道：今日头条搜索 so.toutiao.com 不限流（最可靠）；360 移动端 m.so.com 可用
- 抓取：curl（Schannel 版，勿加 --compressed）最稳；lg.gov.cn 等站 urllib 会 SSL BAD_ECPOINT
字段：(key, doc_type, 列表URL, 标题过滤词, 翻页深度)
"""

EXTRA3 = [
 # ---- A 组：区县级「聚合各部门总结」栏目（最优）----
 ('yanta_summary',    '工作总结', 'http://www.yanta.gov.cn/xxgk/jcxxgk/ghjh/bmjhzj/1.html', ['总结'], 6),
 ('gutian_summary',   '工作总结', 'http://www.gutian.gov.cn/zwgk/ghjh/ndgzjhhzj/', ['总结'], 3),
 ('hengzhou_summary', '工作总结', 'http://www.gxhx.gov.cn/xxgk/xxgkml/jcxxgk/ghjh/NDJH/', ['总结'], 4),
 ('luozhuang_summary','工作总结', 'http://www.luozhuang.gov.cn/xzfxxgk/fdzdgknr/jcgk/ghjh/ndjhzj.htm', ['总结'], 6),
 ('jiangan_summary',  '工作总结', 'https://www.jiangan.gov.cn/jaxxw/zfxxgk/fdzdgk/ghjh/bmjhhzj/', ['总结'], 2),
 ('hdct_summary',     '工作总结', 'http://www.hdct.gov.cn/ctqxxgk/bmxx_26530/zfbm/qzfb/fdgknr/ghjh/', ['总结'], 2),
 ('ksqzgz_summary',   '工作总结', 'http://www.ks.gov.cn/kss/qzgz/xxgk_list.shtml', ['总结'], 3),
 ('xdz_summary',      '工作总结', 'https://xdz.xa.gov.cn/zwgk/ghjh/ndjh/1.html', ['总结'], 4),
 ('gxq_summary2',     '工作总结', 'http://gxq.guiyang.gov.cn/zfxxgk/fdzdgknr/qtfdxx/jhzj/', ['总结'], 2),
 ('liangqing_summary','工作总结', 'http://www.liangqing.gov.cn/xxgk/fdzdgk/jcxxgk/ghjh/', ['总结'], 2),
 ('xingbin_summary',  '工作总结', 'http://www.xingbin.gov.cn/zfxxgk_1/fdzdgknr/ghjh/index.shtml', ['总结'], 3),
 ('qzlc_summary',     '工作总结', 'https://www.qzlc.gov.cn/xxgk/ghjh/', ['总结'], 2),
 ('gxll_summary',     '工作总结', 'http://www.gxll.gov.cn/xxgk/jcxxgk/ghjh/', ['总结'], 2),
 # ---- B 组：街道/区局栏目（lg.gov.cn 系 urllib 会 SSL 失败，留档待 curl 通道）----
 ('lgbt_summary',     '工作总结', 'http://www.lg.gov.cn/bmzz/btjdb/xxgk/ghjh/ndgzjhjzj/', ['总结'], 2),
 ('lgjh_summary',     '工作总结', 'http://www.lg.gov.cn/bmzz/jhjdb/xxgk/ghjh/ndgzjhjzj/', ['总结'], 2),
 ('lglc_summary',     '工作总结', 'http://www.lg.gov.cn/bmzz/lcjdb/xxgk/ghjh/ndgzjhjzj/', ['总结'], 2),
 ('lgpd_summary',     '工作总结', 'http://www.lg.gov.cn/bmzz/pdjdb/xxgk/ghjh/ndgzjhjzj/', ['总结'], 2),
 ('lgfl_summary',     '工作总结', 'http://www.lg.gov.cn/bmzz/fl/xxgk/ghjh', ['总结'], 2),
 ('txqzgh_summary',   '工作总结', 'http://www.tianxin.gov.cn/zwgk8/qtdwxxgkml/qzgh/ghjh84/', ['总结'], 2),
 ('txqtjj_summary',   '工作总结', 'http://www.tianxin.gov.cn/zwgk8/bmxxgkml/qtjj26/ghjh63/', ['总结'], 2),
 ('wcqfl_summary',    '工作总结', 'http://www.wangcheng.gov.cn/xxgk_343/gdwxxgk/qtxl/qfl/ghjh_5103/', ['总结'], 2),
 ('wcqcl_summary',    '工作总结', 'http://www.wangcheng.gov.cn/xxgk_343/gdwxxgk/qtxl/qcl/ghjh_5231/', ['总结'], 2),
 ('ws_summary',       '工作总结', 'http://www.wenshang.gov.cn/col/col20153/index.html', ['总结'], 2),
 ('cixi_summary',     '工作总结', 'http://www.cixi.gov.cn/col/col1229041721/index.html', ['总结'], 2),
 # ---- C 组：市级部门 / 省厅 ----
 ('fscg_summary',     '工作总结', 'http://fscg.foshan.gov.cn/zwgk/ghjh/index.html', ['总结'], 2),
 ('nnwjw_summary',    '工作总结', 'http://wjw.nanning.gov.cn/xxgk/xxgkml/ztfl/ghjh/', ['总结'], 2),
 ('nnlyj_summary',    '工作总结', 'http://lyj.nanning.gov.cn/zfxxgk_new/fdzdgknr/ghjh/', ['总结'], 2),
 ('wzjj_summary',     '工作总结', 'http://zjj.wuzhou.gov.cn/xxgk/gzzjhjh/', ['总结'], 2),
 ('wuxicl_summary',   '工作总结', 'https://cl.wuxi.gov.cn/zfxxgk/jhzj/index.shtml', ['总结'], 2),
 ('lygzw_summary',    '工作总结', 'http://lygzw.longyan.gov.cn/zwgk/jhzj/', ['总结'], 2),
 ('sqnyj_summary',    '工作总结', 'http://nyncj.shangqiu.gov.cn/zwgk/fdzdgknr/ghjh3sqsnyncj', ['总结'], 2),
 ('gzjt_summary',     '工作总结', 'http://jt.guizhou.gov.cn/zwgk/zdlyxxgk_5948535/ghjh_5948537/ndgzzj_5948539/', ['总结'], 2),
 ('lpssfj_summary',   '工作总结', 'http://sfj.gzlps.gov.cn/bmxxgk/zfxxgk_5712754/fdzdgknr/jhzj_5806310/', ['总结'], 2),
 ('lpstyjr_summary',  '工作总结', 'http://tyjrswj.gzlps.gov.cn/bmxxgk/zfxxgk/fdzdgknr/jhzj_5804106/', ['总结'], 2),
 ('lpsgxs_summary',   '工作总结', 'http://lpsgxs.gzlps.gov.cn/bmxxgk/zfxxgk/fdzdgknr/jhzj_5816386/', ['总结'], 2),
 ('fjhyyyj_summary',  '工作总结', 'http://hyyyj.fujian.gov.cn/xxgk/ghjh/', ['总结'], 2),
 ('fjnyct_summary',   '工作总结', 'http://nynct.fujian.gov.cn/xxgk/ghjh/', ['总结'], 3),
]
