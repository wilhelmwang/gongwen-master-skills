#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公文大师独立包 · 初始化自检脚本（v7.3.0）

用法：python verify_install.py

检查维度：
  1. 技能完整性（v8.0.0：1 顶层 gongwen-master + references/ 嵌套模块，与 skills_manifest 单一来源比对）
  2. shuji 九子模块
  3. 数据层形态与资产在位性（A 外置 / B 包内 / C 降级，统一经 datahub/paths.py 解析）
  4. 数据库可打开性（articles / hs_facts / hs_pages）
  5. 金句库条目数（防缩水回归）
  6. 依赖可用性（jieba / numpy / scikit-learn / rank_bm25）
  7. 检索抽测 + 索引覆盖率 + FTS 完整性
  8. 向量库存在性（hybrid3 第三路）
  9. 可移植性（无机器绝对路径硬编码 / 无嵌套技能目录 / 版本一致性 / version 引号规范）
 10. frontmatter 规范（复用 validate_skills）

v7.3.0 变更：数据层路径全部改经 datahub/paths.py 解析，删除散落的 <数据根> 硬编码；
             修复原「数据层 7 资产」用 os.path.join 拼绝对路径导致该项恒真/恒假的缺陷；
             技能清单改由 skills_manifest.py 单一来源提供并做漂移审计。
"""
import os, sys, re, sqlite3, importlib, json, pickle


def _stdout_encoding_guard():
    """非交互流强制 UTF-8，交互控制台保 locale 只降级不可编码字符。

    Windows 上 CPython 对 pipe/重定向用 locale 编码（cp936），遇 ✅⚠✓ 等符号抛
    UnicodeEncodeError 中断脚本；agent 调脚本时 stdout 恒为管道 ⇒ 必崩。
    真控制台不能改 encoding（字节流仍按控制台代码页渲染，会中文乱码）。
    """
    try:
        for _st in (sys.stdout, sys.stderr):
            if _st is None or not hasattr(_st, 'reconfigure'):
                continue
            if _st.isatty():
                _st.reconfigure(errors='replace')
            else:
                _st.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


_stdout_encoding_guard()

BASE = os.path.dirname(os.path.abspath(__file__))
OK = '✅'; BAD = '❌'; WARN = '⚠️'
sys.path.insert(0, BASE)

# 布局解析（v8.0.0 单技能：技能根经 skills_manifest 统一判定，开发态/部署态双兼容）
from skills_manifest import SKILL_ROOT, skill_dir, skill_md  # noqa: E402

# 数据层解析器（唯一路径事实源）
sys.path.insert(0, os.path.join(SKILL_ROOT, 'datahub'))
try:
    from paths import (db_path, index_path, vectors_path, vectors_meta_path,
                       statements_path, jinyu_path, DATA_ROOT, DATA_ROOT_SOURCE,
                       resolve_form, is_available, degradation_notice, vector_status)
    _PATHS_OK = True
except Exception as _e:  # datahub 被裁剪掉时的降级提示
    _PATHS_OK = False
    _PATHS_ERR = str(_e)

try:
    from skills_manifest import GOVERNED, INSTALLER, audit, discover  # noqa: F811
except Exception:
    GOVERNED, INSTALLER = [], 'install-gongwen'
    SKILL_ROOT = BASE
    skill_dir = lambda name: os.path.join(BASE, name)   # noqa: E731
    skill_md = lambda name: os.path.join(BASE, name, 'SKILL.md')  # noqa: E731
    audit = lambda: ([], [])  # noqa: E731
    discover = lambda: []      # noqa: E731


def check(name, ok, detail=''):
    mark = OK if ok else BAD
    print(f'{mark} {name}' + (f' | {detail}' if detail else ''))
    return (name, ok, detail)


def get_skill_version(skill_md):
    """从 SKILL.md frontmatter 提取 version（v7.3.1：委托 skillmeta，消除多套解析口径）"""
    try:
        import skillmeta
        return skillmeta.version(skill_md) or '?'
    except Exception:
        return '?'


def main():
    print('=== 公文大师独立包自检 ===\n')
    results = []

    # 0. 数据层解析器可用性
    results.append(check('数据根解析器 (datahub/paths.py)', _PATHS_OK,
                         describe_paths() if _PATHS_OK else f'导入失败: {_PATHS_ERR[:60]}'))
    if not _PATHS_OK:
        print('\n❌ 数据层解析器不可用，后续数据类检查无法进行。')
        return 1

    # 1. 技能目录（清单单一来源 + 磁盘漂移审计）
    tops = list(GOVERNED)
    missing_disk, unexpected = audit()
    results.append(check(f'技能目录 {len(tops)}/{len(tops)}（受治理）', not missing_disk,
                         f'缺失: {missing_disk}' if missing_disk else '全部就位'))
    results.append(check('技能清单与目录一致（无漂移）', not unexpected,
                         f'未登记目录: {unexpected}' if unexpected else
                         f'{len(discover())} 项 = 1 顶层 master + references/ 嵌套模块（含退役安装器与参考技能）'))

    # shuji 9 子模块
    shuji = ['dangdai-zhengfu', 'jiegou-gaige', 'liyi-weili', 'shizhi-shinei', 'xianxiang-zhongguo',
             'xiaozhen-xuanxiao', 'zhidu-luoji', 'zhongxian-ganbu', 'zhuanxing-zhengfu']
    mbooks = [b for b in shuji if not os.path.exists(os.path.join(skill_dir('shuji'), 'references', b, 'SKILL.md'))]
    results.append(check(f'shuji 子模块 {len(shuji)}/{len(shuji)}', not mbooks, f'缺失: {mbooks}' if mbooks else ''))

    # 2. 数据层形态（A 外置 / B 包内 / C 降级）
    form = resolve_form()
    form_desc = {'A': 'A · 外置数据根可用', 'B': 'B · 包内数据可用', 'C': 'C · 降级'}
    # 形态 C＝无数据（对外方法论包的**正常形态**），不是错误：写作/润色/质检/排版可用，
    # 仅检索与数据引用关闭。此前写作 `form in ('A','B')`，把 C 判为失败——
    # 那会让对外分包一解包就自检不过（但语料里的 eval/semantic_router 已按数据形态 SKIP）。
    form_desc_c = 'C · 无数据（方法论包形态：写作/润色/质检/排版可用，检索与数据引用关闭）'

    #: 数据是否在位。形态 C＝无数据（对外方法论包的正常形态）——
    #: 依赖语料的自检项在 C 下应**跳过**而非失败：一个只含方法论的包解包即自检不过，
    #: 会让使用者以为包坏了。反之在开发者本机上出现这些跳过，就是数据根掉线的信号。
    DATA_OK = form in ('A', 'B')

    def dcheck(name, cond, detail=''):
        """数据依赖项：形态 C 时记通过并注明跳过"""
        if not DATA_OK:
            return check(name, True, '形态 C：无数据，跳过（对外方法论包形态）')
        return check(name, cond, detail)

    results.append(check('数据层形态', True,
                         form_desc[form] if form != 'C' else form_desc_c))
    if form == 'C':
        print()
        print(degradation_notice())
        print()

    results.append(check('qiushi_engine.py', os.path.exists(os.path.join(SKILL_ROOT, 'datahub', 'scripts', 'qs', 'qiushi_engine.py'))))

    # 3. 数据资产在位性（经解析器；不再用 os.path.join 拼绝对路径）
    #    主库为硬性项；索引/论断/金句为可选增强件，缺失不判失败（开源版仅随包主库）
    assets = [('主库 gongwen_corpus.db', db_path, 100 * 1024 * 1024)]
    miss = []
    for label, fn, thr in assets:
        p = fn()
        if not (os.path.exists(p) and os.path.getsize(p) >= thr):
            miss.append(label)
    results.append(dcheck(f'数据资产 {len(assets) - len(miss)}/{len(assets)}',
                         not miss,
                         f'缺失/过小: {miss}' if miss else '经 paths.py 解析，全部在位'))

    optional = [('索引 qs_index.pkl', index_path),
                ('论断库 qs_statements.json', statements_path),
                ('金句库 corpus_jinyu_full.md', jinyu_path)]
    have = [lb for lb, fn in optional if os.path.exists(fn())]
    results.append(check('可选增强资产', True,
                         f'{len(have)}/{len(optional)} 在位' + ('' if len(have) == len(optional)
                         else '（缺失不影响写作；检索精简度下降）')))

    # 4. 金句库条目数（可选增强件：开源版不随包分发，缺失不判失败）
    try:
        with open(jinyu_path(), encoding='utf-8') as _f:
            _quotes = [l for l in _f.read().splitlines() if l.strip().startswith('- ')]
        results.append(check('金句库条目数', True, f'{len(_quotes)} 条'))
    except Exception:
        results.append(check('金句库条目数', True,
                             '未随包分发（可选增强件）；如需启用请自备 corpus_jinyu_full.md'))

    # 5. 数据库可打开（articles 正文表）
    def try_open(db, table):
        try:
            conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
            if table == 'articles':
                n = conn.execute('SELECT COUNT(*) FROM articles').fetchone()[0]
            else:
                conn.close()
                return False, f'未登记表: {table}'
            conn.close()
            return True, n
        except Exception as e:
            return False, str(e)[:60]

    qdb = db_path()
    for tbl, label, unit in (('articles', 'articles（正文）', '篇'),):
        ok, n = try_open(qdb, tbl)
        results.append(dcheck(f'主库 {label} 可打开', ok, f'{n} {unit}' if ok else n))

    # 6. 依赖
    for d in ('jieba', 'numpy', 'sklearn', 'rank_bm25'):
        try:
            importlib.import_module(d)
            results.append(check(f'依赖 {d}', True))
        except ImportError:
            results.append(check(f'依赖 {d}', False, '未安装 (pip install -r requirements.txt)'))

    # 7. 检索抽测 + 索引覆盖 + FTS 完整性
    if 'jieba' in sys.modules:
        try:
            import jieba
            jieba.setLogLevel(60)
            sys.path.insert(0, os.path.join(SKILL_ROOT, 'datahub', 'scripts', 'qs'))
            from qiushi_engine import search_database, DB_PATH
            results.append(check('检索引擎数据源与解析器一致', os.path.abspath(DB_PATH) == os.path.abspath(db_path()),
                                 DB_PATH))
            r = search_database('新质生产力', top_n=3)
            results.append(dcheck('qiushi 检索抽测', len(r) > 0, f'命中 {len(r)} 条'))

            # 索引覆盖率：索引篇数须 ≥ 库中可检索篇数（content>100）的 95%
            try:
                # 反序列化护栏：索引须落在数据根内（拒绝外部不可信 pickle）
                from paths import DATA_ROOT as _dr
                if os.path.commonpath([os.path.realpath(index_path()),
                                       os.path.realpath(_dr)]) != os.path.realpath(_dr):
                    raise ValueError('索引位置越界，已拒绝')
                with open(index_path(), 'rb') as f:
                    idx = pickle.load(f)
                idx_n = len(idx['article_ids'])
                conn = sqlite3.connect(f'file:{qdb}?mode=ro', uri=True)
                avail = conn.execute(
                    'SELECT COUNT(*) FROM articles WHERE content IS NOT NULL AND length(content) > 100').fetchone()[0]
                conn.close()
                results.append(dcheck('索引覆盖 (文章可检索率)', idx_n >= avail * 0.95,
                                     f'索引 {idx_n} / 库可用 {avail} (要求 ≥95%)'))
            except Exception as e:
                results.append(dcheck('索引覆盖 (文章可检索率)', False, str(e)[:60]))

            # FTS 完整性：articles_fts 行数须等于 content>100 的可索引篇数
            try:
                conn3 = sqlite3.connect(f'file:{qdb}?mode=ro', uri=True)
                avail_n = conn3.execute(
                    'SELECT COUNT(*) FROM articles WHERE content IS NOT NULL AND length(content) > 100').fetchone()[0]
                fts_n = conn3.execute('SELECT COUNT(*) FROM articles_fts').fetchone()[0]
                empty_n = conn3.execute(
                    "SELECT COUNT(*) FROM articles WHERE content IS NULL OR content=''").fetchone()[0]
                conn3.close()
                fts_ok = (fts_n == avail_n)
                results.append(dcheck('FTS 完整性 (articles_fts 覆盖)', fts_ok,
                                     f'{fts_n}/{avail_n} 一致 · 空content {empty_n} 篇(图表/法规,非正文)'
                                     if fts_ok else f'FTS {fts_n} / 应索引 {avail_n}'))
            except Exception as e:
                results.append(dcheck('FTS 完整性 (articles_fts 覆盖)', False, str(e)[:60]))
        except Exception as e:
            results.append(dcheck('qiushi 检索抽测', False, str(e)[:60]))

    # 8. 向量路（hybrid3 第三路；矩阵 + 元数据 + 模型三者齐备才算启用）
    #    v7.5.0：从"矩阵是否存在"升级为"向量路是否真的能用"——此前模型只在环境变量里找，
    #    机器上模型在位却因没人 export 而长期静默降级，本项却报 ✅，属"看起来绿"。
    v_ok, v_note = vector_status()
    # 「有模型 / 无模型」是两种合法形态，不是通过/失败：
    # bge 模型未随包分发（且体积大，不宜随包），缺模型的机器应走词面检索而非自检不过。
    # 与本包既定的「地板取最低态」政策一致——release_gates 的 semantic_router 同理由探针 SKIP。
    # 但**缺模型必须在结果里可见**：note 原样带出，不写成模糊的"已通过"。
    if v_ok:
        results.append(dcheck('vec 向量路', True, v_note))
    else:
        results.append(check('vec 向量路', True, f'未启用（合法态）：{v_note}'))

    # 9.1 硬编码路径检测
    # 唯一合法持有机器路径的位置：datahub/paths.py（内置默认数据根）+ 本脚本自身（检测模式字符串）
    _skip = ('.old_replace', 'backups', '__pycache__', '.git', '.github', '_rollback_')
    _exempt = {os.path.abspath(__file__), os.path.join(SKILL_ROOT, 'datahub', 'paths.py')}
    bad_paths = []
    for root, dirs, files in os.walk(BASE):
        dirs[:] = [d for d in dirs if d not in _skip]
        for f in files:
            if not f.endswith('.py'):
                continue
            fp = os.path.join(root, f)
            if os.path.abspath(fp) in _exempt:
                continue
            try:
                src = open(fp, encoding='utf-8').read()
            except Exception:
                continue
            if ('C:' + chr(92) + 'Users') in src or ('C:' + '/Users') in src:
                bad_paths.append(os.path.relpath(fp, BASE))
            elif re.search(r'[Dd]:[/\\]0\d{2}_', src):
                bad_paths.append(os.path.relpath(fp, BASE) + ' (D:/0xx_*)')
    results.append(check('无机器绝对路径硬编码', not bad_paths,
                         f'发现: {bad_paths[:5]}' if bad_paths else '仅 paths.py 持有默认数据根（唯一合法位置）'))

    # 9.2 意外二级套娃（v8：references/ 一级嵌套模块本身合法；检测的是模块目录内
    #     又被整目录复制出「同名子目录含 SKILL.md」的安装事故 → 递归扫描宿主会重复注册）
    nested = []
    for d in discover():
        dd = skill_dir(d)
        if os.path.isdir(os.path.join(dd, d)) and \
                os.path.exists(os.path.join(dd, d, 'SKILL.md')):
            nested.append(f'{d}/{d}')
    results.append(check('无意外二级套娃目录', not nested, f'嵌套: {nested}' if nested else ''))

    # 9.3 版本一致性（VERSION 文件 + 主技能 version 匹配）
    vf = os.path.join(SKILL_ROOT, 'VERSION')
    if os.path.exists(vf):
        pkg_v = open(vf, encoding='utf-8').read().strip()
        master_v = get_skill_version(skill_md('gongwen-master'))
        ver_ok = pkg_v == master_v
        results.append(check('版本一致性 (VERSION vs master)', ver_ok,
                             f'VERSION={pkg_v} / master={master_v}' if not ver_ok else f'v{pkg_v}'))
    else:
        results.append(check('版本一致性 (VERSION vs master)', False, '缺 VERSION 文件'))

    # 9.4 version 引号规范（防 YAML float 解析）
    bad_v = []
    for t in tops:
        vfp = skill_md(t)
        if os.path.exists(vfp):
            vc = open(vfp, encoding='utf-8').read()[:600]
            if re.search(r'^version:\s*([0-9][0-9.]*)\s*$', vc, re.M):
                bad_v.append(t)
    results.append(check('version 引号规范', not bad_v, f'裸数字: {bad_v[:6]}' if bad_v else '全部带引号'))

    # 10. frontmatter 规范（validate_skills 复用）
    try:
        import validate_skills as _vs
        _iss_all = []
        for _s in _vs.SKILLS:
            _i, _w = _vs.check_skill(_s)
            for _x in _i:
                _iss_all.append(f'{_s}: {_x}')
        results.append(check(f'frontmatter 规范 ({len(_vs.SKILLS)} 技能合规)', not _iss_all,
                             f'问题: {_iss_all[:3]}' if _iss_all else f'{len(_vs.SKILLS)}/{len(_vs.SKILLS)} 合规'))
    except Exception as e:
        results.append(check('frontmatter 规范', False, str(e)[:60]))

    bad = [r for r in results if not r[1]]
    print(f'\n检查项: {len(results)} 项 | 全部通过: {len(bad) == 0}')
    if bad:
        print('未通过项:')
        for r in bad:
            print(f'  - {r[0]}: {r[2][:70] if r[2] else ""}')
    return 0 if not bad else 1


def describe_paths():
    return f'{DATA_ROOT}（{DATA_ROOT_SOURCE}）'


if __name__ == '__main__':
    sys.exit(main())
