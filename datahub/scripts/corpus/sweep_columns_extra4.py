# -*- coding: utf-8 -*-
"""第五批栏目配置：政府工作报告专项（2026-09-13 站群探测命中，15 个）

来源：`autoprobe_columns.py` 对 228 个真实域名（`probe_targets.py`，从站群导航挖出）
做「域名 × 路径模板」探测的命中结果。**贵州系县级门户整批命中同一路径 `/zwgk/zfgzbg/`**，
验证了"站群挖域名 + 同族路径复用"这条自给通道。

字段：(key, doc_type, 列表URL, 标题过滤词, 翻页深度)
"""

EXTRA4 = [
 # ---- 省级 / 省聚合 ----
 ('sc_henan_report',  '工作报告', 'https://www.henan.gov.cn/zwgk/zfgzbg/', ['工作报告'], 25),
 ('sc_guizhou_report','工作报告', 'https://www.guizhou.gov.cn/zwgk/zfgzbg/', ['工作报告'], 20),
 ('sc_shaanxi_report','工作报告', 'https://www.shaanxi.gov.cn/zfxxgk/zfgzbg/', ['工作报告'], 12),
 ('sc_hainan_report', '工作报告', 'https://www.hainan.gov.cn/zwgk/zfgzbg/', ['工作报告'], 14),
 # ---- 市级 ----
 ('sc_nanchong_report','工作报告', 'https://www.nanchong.gov.cn/zwgk/zfgzbg/', ['工作报告'], 12),
 ('sc_zunyi_report2', '工作报告', 'https://www.zunyi.gov.cn/zwgk/zfgzbg/', ['工作报告'], 12),
 ('sc_xingtai_report','工作报告', 'https://www.xingtai.gov.cn/zwgk/zfgzbg/', ['工作报告'], 12),
 ('sc_bijie_report',  '工作报告', 'https://www.bijie.gov.cn/zwgk/zfgzbg/', ['工作报告'], 12),
 ('sc_cj_report',     '工作报告', 'https://www.cj.gov.cn/zfgzbg/', ['工作报告'], 12),
 # ---- 县级（贵州系整批）----
 ('sc_xsx_report',    '工作报告', 'https://www.xsx.gov.cn/zwgk/zfgzbg/', ['工作报告'], 12),
 ('sc_rh_report',     '工作报告', 'https://www.rh.gov.cn/zwgk/zfgzbg/', ['工作报告'], 12),
 ('sc_zyhhg_report',  '工作报告', 'https://www.zyhhg.gov.cn/zwgk/zfgzbg/', ['工作报告'], 12),
 ('sc_suiyang_report','工作报告', 'https://www.suiyang.gov.cn/zwgk/zfgzbg/', ['工作报告'], 12),
 ('sc_fenggang_report','工作报告', 'https://www.gzfenggang.gov.cn/zwgk/zfgzbg/', ['工作报告'], 12),
 ('sc_meitan_report', '工作报告', 'https://www.meitan.gov.cn/zwgk/zfgzbg/', ['工作报告'], 12),
]
