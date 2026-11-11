# -*- coding: utf-8 -*-
"""探测靶表（2026-09-13 · 从已验证站点的站群导航挖掘出的域名，非猜测）

来源：遵义（政府常务会议栏目页）与阿克陶（政务公开栏目页）的站群导航，
提取全部 .gov.cn 域名后过滤部委/备案链接所得。全部为**真实存在的门户**，
比拼音猜域名可靠得多。

用途：供 autoprobe_columns.py 做「域名 × 路径模板」探测。
"""

#: 全国省级政府门户（31，站群导航中出现）
PROVINCIAL = [
 'ah.gov.cn', 'beijing.gov.cn', 'cq.gov.cn', 'fujian.gov.cn', 'gansu.gov.cn',
 'gd.gov.cn', 'gxzf.gov.cn', 'guizhou.gov.cn', 'hainan.gov.cn', 'hebei.gov.cn',
 'henan.gov.cn', 'hlj.gov.cn', 'hubei.gov.cn', 'hunan.gov.cn', 'jiangsu.gov.cn',
 'jiangxi.gov.cn', 'jl.gov.cn', 'ln.gov.cn', 'nmg.gov.cn', 'nx.gov.cn',
 'qinghai.gov.cn', 'sc.gov.cn', 'sd.gov.cn', 'shaanxi.gov.cn', 'shanghai.gov.cn',
 'shanxi.gov.cn', 'tj.gov.cn', 'xinjiang.gov.cn', 'xizang.gov.cn', 'yn.gov.cn', 'zj.gov.cn',
]

#: 贵州地市州（9 + 省级已含）
GUIZHOU_CITY = ['anshun.gov.cn', 'bijie.gov.cn', 'guiyang.gov.cn', 'gzlps.gov.cn',
                'qdn.gov.cn', 'qiannan.gov.cn', 'qxn.gov.cn', 'suiyang.gov.cn',
                'trs.gov.cn', 'zunyi.gov.cn']

#: 贵州县区（遵义下辖 + 邻近，站群导航中出现）
GUIZHOU_COUNTY = ['gzchishui.gov.cn', 'gzdaozhen.gov.cn', 'gzfenggang.gov.cn',
                  'gztongzi.gov.cn', 'gzwuchuan.gov.cn', 'gzza.gov.cn', 'xinpu.gov.cn',
                  'zybz.gov.cn', 'zyhc.gov.cn', 'zyhhg.gov.cn', 'zgyq.gov.cn',
                  'xsx.gov.cn', 'rh.gov.cn', 'meitan.gov.cn']

#: 新疆地州/县市（16）
XINJIANG_CITY = ['aks.gov.cn', 'cj.gov.cn', 'hami.gov.cn', 'kashi.gov.cn', 'klmy.gov.cn',
                 'tlf.gov.cn', 'wlmq.gov.cn', 'xjahq.gov.cn', 'xjalt.gov.cn',
                 'xjboz.gov.cn', 'xjbz.gov.cn', 'xjht.gov.cn', 'xjkz.gov.cn',
                 'xjtc.gov.cn', 'xjwqx.gov.cn', 'xjyl.gov.cn']

#: 遵义市局子站（26）—— 部门站，瞄准「部门年度工作总结」
ZUNYI_DEPT = ['czj.zunyi.gov.cn', 'dsj.zunyi.gov.cn', 'fgw.zunyi.gov.cn',
              'ggzyjy.zunyi.gov.cn', 'gkj.zunyi.gov.cn', 'gzw.zunyi.gov.cn',
              'jtj.zunyi.gov.cn', 'jyj.zunyi.gov.cn', 'lyj.zunyi.gov.cn',
              'mzj.zunyi.gov.cn', 'nyj.zunyi.gov.cn', 'nyncj.zunyi.gov.cn',
              'rfb.zunyi.gov.cn', 'rsj.zunyi.gov.cn', 'scjgj.zunyi.gov.cn',
              'sfj.zunyi.gov.cn', 'sjj.zunyi.gov.cn', 'slj.zunyi.gov.cn',
              'swj.zunyi.gov.cn', 'tjj.zunyi.gov.cn', 'tyjrswj.zunyi.gov.cn',
              'tzzy.zunyi.gov.cn', 'wlj.zunyi.gov.cn', 'wsjkj.zunyi.gov.cn',
              'yjj.zunyi.gov.cn', 'ylbzj.zunyi.gov.cn', 'ymj.zunyi.gov.cn',
              'zfgjj.zunyi.gov.cn', 'zhxzzfj.zunyi.gov.cn', 'zjj.zunyi.gov.cn',
              'zrzyj.zunyi.gov.cn', 'zwfwglj.zunyi.gov.cn', 'zyepb.zunyi.gov.cn']

#: 新疆厅局子站（16）—— 部门站
XINJIANG_DEPT = ['czt.xinjiang.gov.cn', 'gat.xinjiang.gov.cn', 'gxt.xinjiang.gov.cn',
                 'jtyst.xinjiang.gov.cn', 'jyt.xinjiang.gov.cn', 'nynct.xinjiang.gov.cn',
                 'rst.xinjiang.gov.cn', 'scjgj.xinjiang.gov.cn', 'slt.xinjiang.gov.cn',
                 'sthjt.xinjiang.gov.cn', 'swt.xinjiang.gov.cn', 'tjj.xinjiang.gov.cn',
                 'wjw.xinjiang.gov.cn', 'wlt.xinjiang.gov.cn', 'yjgl.xinjiang.gov.cn',
                 'zjt.xinjiang.gov.cn', 'zrzyt.xinjiang.gov.cn']

#: 合并：门户类（政府工作报告用）与部门类（工作总结用）
PORTALS = PROVINCIAL + GUIZHOU_CITY + GUIZHOU_COUNTY + XINJIANG_CITY
DEPTS = ZUNYI_DEPT + XINJIANG_DEPT
ALL = sorted({d for d in (PORTALS + DEPTS)})
