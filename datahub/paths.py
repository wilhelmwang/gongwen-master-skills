# -*- coding: utf-8 -*-
"""数据根解析器（v7.3.0 · 全包唯一路径事实源）

背景
----
2026-09-09 公文数据库族统一收归 `<数据根>/`，包内 `datahub/sqlite/` 转为占位快照。
但当时只有 `qiushi_engine.py` 与 `rebuild_fts.py` 跟上了变更，其余消费方（7 个管线脚本、
`bootstrap_data.py`、`gongwen_tool.py snapshot`、`verify_install.py`）
仍指向 0 字节空壳，导致地方检索失效、重建写进空壳、快照空白、自检误报降级。

本模块把"数据外置"变成显式、可配置、可降级的一等公民，替代散落各处的硬编码绝对路径。

解析顺序（先命中先用）
----------------------
  1. 环境变量 ``GONGWEN_DATA_ROOT``   —— 运维/多机部署的覆盖点
  2. ``assets.json`` 顶层 ``data_root`` —— 包内登记的策略默认值
  3. 内置默认（<数据根>）          —— 当前实际布局
  4. 回退包内 ``datahub/``              —— 真 standalone 分发形态（数据随包）

形态判定
--------
  A  外置数据根可用（数据在 DATA_ROOT）
  B  包内数据可用（数据随包，standalone 分发形态）
  C  降级（两处都没有 → 检索/数据引用关闭，纯文本写作能力仍可用）

用法
----
  >>> from paths import db_path, resolve_form, describe
  >>> db_path()            # 绝对路径
  >>> resolve_form()       # 'A' | 'B' | 'C'
  >>> print(describe())    # 人类可读的解析说明

命令行自检::

  python datahub/paths.py
"""
import json
import os

# ---------------------------------------------------------------- 包根探测

def _find_pkg_root():
    """向上找含 VERSION 的目录（目录改名 / 跨机部署自适应）"""
    p = os.path.dirname(os.path.abspath(__file__))
    while not os.path.exists(os.path.join(p, 'VERSION')) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    return p


PKG_ROOT = _find_pkg_root()
DATAHUB = os.path.join(PKG_ROOT, 'datahub')

#: 未配置任何覆盖时的内置默认数据根（当前实际布局）
#: 内置默认数据根（**便携约定，不得写构建者的机器路径**）。
#: 解析优先级：GONGWEN_DATA_ROOT → assets.json:data_root → 本默认 → 包内回退。
#: 2026-09-15 前这里写死的是构建者本机路径，随包分发会①泄漏布局②在使用者机器上必然失效；
#: 改为用户主目录约定后，未配置的使用者落到「形态 C（无数据，仅方法论）」——这正是对外包的预期形态。
DEFAULT_DATA_ROOT = os.path.join(os.path.expanduser('~'), 'gongwen-data')

#: 各资产候选路径。
#: 每项为 (外置根下的相对名, [包内候选相对路径...])
_ASSETS = {
    'db': ('gongwen_corpus.db',
           ['sqlite/gongwen_corpus.db', 'sqlite/qs_articles.db']),
    'index': ('qs_index.pkl',
              ['derived/qs_index.pkl']),
    'vectors': ('qs_vectors.npy',
                ['derived/qs_vectors.npy']),
    'vec_meta': ('qs_vectors.json',
                 ['derived/qs_vectors.json']),
    'statements': ('qs_statements.json',
                   ['derived/qs_statements.json']),
    # 论断库·去噪版（2026-09-24 新增）：与上游同构，仅剔除图片署名／截断片段／章节小标题。
    # 单列资产键而不替换上面的 'statements'：verify_install / bootstrap_data 按原名校验原文件，
    # 替换会让它们报「论断库缺失」。消费端取去噪版，取不到则回退原版。
    # 判据与产出见 002成果资产/56_公文数据库审计_GongwenDBAudit_v1.0.0/引用域去噪_v1.0.0/。
    'statements_denoised': ('_denoised/qs_statements.denoised.json',
                            ['derived/_denoised/qs_statements.denoised.json']),
    'jinyu': ('corpus_jinyu_full.md',
              ['derived/corpus_jinyu_full.md']),
    'content_hash': ('qs_content_hash.json',
                     ['derived/qs_content_hash.json']),
    # 范文池分层库（2026-09-15 新增）：L0 原始 / L1 治理 / L2 审核台账。
    # 单独登记是因为它在数据根下的 govdoc_samples/ 子目录，不在根治目录。
    'samples': ('govdoc_samples/gongwen_samples.db',
                ['derived/govdoc_samples/gongwen_samples.db']),
    # 政策文件库四库（2026-09-16 新增）：独立库、trigram FTS，供「政策原文 / 文号」**定向查询**。
    # 与主库分离是刻意的：主库用于**写作引证**（权威期刊 + 公报），政策文件是**依据出处**，
    # 两者混在一起会让引文的出处变成基层部门通知——与范文池不入检索同一条理由。
    # 所以这四库**不并入 hybrid3**，由 `datahub/scripts/zc/search_zhengce.py` 单独提供入口。
    'zhengce_zy': ('zhengce_zy.db', ['derived/zhengce_zy.db']),
    'zhengce_gw': ('zhengce_gw.db', ['derived/zhengce_gw.db']),
    'zhengce_bm': ('zhengce_bm.db', ['derived/zhengce_bm.db']),
    'zhengce_other': ('zhengce_other.db', ['derived/zhengce_other.db']),
}

_ENV_VAR = 'GONGWEN_DATA_ROOT'
_ENV_BGE = 'GONGWEN_BGE_MODEL'
_ASSETS_JSON = os.path.join(DATAHUB, 'assets.json')
_BGE_KEY = 'bge_model'


def _assets_field(field):
    """读 assets.json 顶层字段（读不到返回 None，不抛异常）"""
    try:
        with open(_ASSETS_JSON, encoding='utf-8') as f:
            return (json.load(f) or {}).get(field) or None
    except Exception:
        return None


def _assets_registered_root():
    """读 assets.json 顶层 data_root（读不到返回 None，不抛异常）"""
    return _assets_field('data_root')


def _resolve_data_root():
    """按四段优先序解析数据根，返回 (路径, 来源标签)"""
    env = os.environ.get(_ENV_VAR)
    if env:
        return os.path.normpath(env), f'env:{_ENV_VAR}'
    reg = _assets_registered_root()
    if reg:
        return os.path.normpath(reg), 'assets.json:data_root'
    return os.path.normpath(DEFAULT_DATA_ROOT), 'builtin-default'


DATA_ROOT, DATA_ROOT_SOURCE = _resolve_data_root()


# ---------------------------------------------------------------- 解析核心

def _pick(asset_key):
    """返回 (路径, 形态)；形态 'A' 外置可用 / 'B' 包内可用 / None 未找到"""
    ext_rel, pkg_cands = _ASSETS[asset_key]
    ext = os.path.join(DATA_ROOT, ext_rel)
    if os.path.exists(ext) and os.path.getsize(ext) > 0:
        return ext, 'A'
    for rel in pkg_cands:
        pkg = os.path.join(DATAHUB, rel.replace('/', os.sep))
        if os.path.exists(pkg) and os.path.getsize(pkg) > 0:
            return pkg, 'B'
    # 都没命中：返回外置预期路径（供报错提示用），形态 None
    return ext, None


def _path(asset_key):
    return _pick(asset_key)[0]


# ---------------------------------------------------------------- 对外接口

def db_path():
    """求是主库（gongwen_corpus.db）"""
    return _path('db')


def samples_db_path():
    """范文池分层库（gongwen_samples.db）。

    刻意不并入主库检索——主库用于写作引证，混入县区级范本会让引文出处变成基层文件。
    schema/DDL 门禁经本函数解析它，故注册表条目不需要 `path` 键（符合 path_policy）。
    """
    return _path('samples')


# ---------------------------------------------------------------- 政策文件库四库

#: 简称 → _ASSETS 键。**顺序即默认查询顺序：中央 → 国务院 → 部门 → 其他**——
#: 同一议题在四级都可能有文，上位文件效力更高，写作引据时应先看到它。
POLICY_LIBS = (('zy', 'zhengce_zy'), ('gw', 'zhengce_gw'),
               ('bm', 'zhengce_bm'), ('other', 'zhengce_other'))

#: 简称 → 中文名（输出与报错提示用）
POLICY_NAMES = {'zy': '中央文件', 'gw': '国务院文件',
                'bm': '部门文件', 'other': '其他文件'}


def policy_db_path(key):
    """政策文件库路径。key ∈ {'zy','gw','bm','other'}。

    库缺失时返回**预期路径**（不抛异常），调用方须自行判存在性——见 `policy_libs()`。
    这样"形态 C 无数据"与"某库没采到"都能走到自己的提示分支，而不是崩在路径上。
    """
    key = (key or '').strip().lower()
    for short, asset in POLICY_LIBS:
        if short == key:
            return _path(asset)
    raise ValueError(f'未知政策库 {key!r}，可选：{[s for s, _ in POLICY_LIBS]}')


def policy_libs():
    """四库在位情况：[(简称, 中文名, 路径, 形态)]，形态 None 表示该库缺失。"""
    out = []
    for short, asset in POLICY_LIBS:
        p, form = _pick(asset)
        out.append((short, POLICY_NAMES[short], p, form))
    return out


def index_path():
    """TF-IDF + BM25 索引（qs_index.pkl）"""
    return _path('index')


def vectors_path():
    """bge 向量矩阵（qs_vectors.npy）。是否启用由 bge_model() 决定，见 vector_status()"""
    return _path('vectors')


# ---------------------------------------------------------------- 向量路（bge 模型）

def bge_model():
    """bge 嵌入模型目录（向量检索与语义路由共同依赖）

    解析顺序：环境变量 ``GONGWEN_BGE_MODEL``（运维/多机覆盖）→ ``assets.json`` 顶层
    ``bge_model``（包内登记）→ ``None``（未配置 → 向量路降级为词面检索）。

    v7.5.0 变更：此前只有环境变量一条路，机器上模型明明在位却因"没人 export"而长期
    降级——实测检索指标 98%/0.937/gold 72% 是无向量路的成绩，开向量路为
    99%/0.974/gold 74.0%。改为配置项后向量路开箱即用，且不写死机器路径（仍在 config 层）。
    """
    env = os.environ.get(_ENV_BGE)
    if env:
        return env
    return _assets_field(_BGE_KEY)


def bge_model_status():
    """返回 (可用, 路径, 来源标签, 说明)。用于把"静默降级"变成显式状态。"""
    env = os.environ.get(_ENV_BGE)
    m = bge_model()
    src = f'env:{_ENV_BGE}' if env else f'assets.json:{_BGE_KEY}'
    if not m:
        return False, '', 'unset', f'未配置（设 {_ENV_BGE} 或 assets.json:{_BGE_KEY}）'
    if not os.path.isdir(m):
        return False, m, src, f'目录不存在: {m}'
    weights = [f for f in ('model.safetensors', 'pytorch_model.bin')
               if os.path.exists(os.path.join(m, f))]
    if not weights:
        return False, m, src, f'目录存在但无模型权重（缺 model.safetensors/pytorch_model.bin）: {m}'
    return True, m, src, '可用'


def vector_status():
    """向量路整体状态：(是否启用, 说明)。需「矩阵 + 元数据 + 模型」三者齐备。

    hybrid3 的三路 RRF 中，向量路是可降级项——但降级必须是**可见**的：
    verify_install 与 release 门禁头都会调用本函数如实报出当前是否启用。
    """
    vp, form = _pick('vectors')
    if form is None:
        return False, f'向量矩阵缺失（{vp}）；重建：python datahub/scripts/qs/embed_qiushi_vec.py'
    mp = _path('vec_meta')
    if not os.path.exists(mp):
        return False, f'向量元数据缺失（{mp}）；重建同上'
    ok, _m, src, why = bge_model_status()
    if not ok:
        return False, f'向量模型不可用（{src}: {why}）→ 已降级词面检索'
    try:
        n = json.load(open(mp, encoding='utf-8')).get('n')
    except Exception:
        n = None
    cnt = f'{n:,} 块' if isinstance(n, int) else '块数未知'
    return True, f'模型 {src} ｜ {cnt}'


def vectors_meta_path():
    """向量块元数据（qs_vectors.json）"""
    return _path('vec_meta')


def statements_path():
    """论断库（qs_statements.json）"""
    return _path('statements')


def statements_denoised_path():
    """论断库·去噪版（qs_statements.denoised.json）；缺失时**回退**原版路径。

    回退是刻意的：去噪版是可选增强件，未随包分发时不应让引用路由整体失效。
    调用方无需自判存在性——但若需知道实际拿到哪一版，比对返回值与 `statements_path()`。
    """
    p, form = _pick('statements_denoised')
    if form:
        return p
    return _path('statements')


def jinyu_path():
    """金句库全量（corpus_jinyu_full.md）"""
    return _path('jinyu')


def content_hash_path():
    """内容哈希边车（qs_content_hash.json）——URL→正文 sha256，供"URL 不变但内容已改"检测。

    为什么用边车而不加库列：加列要动 749.6MB 主库的 schema 三同步（registry + ddls + 实库），
    风险与收益不成比例。边车是纯新增文件，不进主库、可随时重建（freshness.py --hash-init）。
    """
    return _path('content_hash')


def resolve_form():
    """判定当前数据形态：'A' 外置 / 'B' 包内 / 'C' 降级

    以主库为准；主库缺失即视为降级（检索与数据引用不可用）。
    """
    _, form = _pick('db')
    if form == 'A':
        return 'A'
    if form == 'B':
        return 'B'
    return 'C'


def is_available():
    """检索/数据引用能力是否可用（主库在位）"""
    return resolve_form() in ('A', 'B')


def degradation_notice():
    """降级时的可操作提示（形态 C 才应展示）"""
    if is_available():
        return ''
    return (
        '数据主库缺失，已降级：公文写作/润色/质检/排版可用（纯文本能力），'
        f'求是检索与数据引用关闭。\n'
        f'  期望路径: {db_path()}\n'
        f'  修复方式: ①设置环境变量 {_ENV_VAR} 指向含 gongwen_corpus.db 的目录；'
        f'或 ②python bootstrap_data.py --from <数据目录>；'
        f'或 ③python bootstrap_data.py --crawl 自行抓取重建。'
    )


def describe():
    """人类可读的解析结果（自检与排障用）"""
    lines = [
        '=== 数据根解析（datahub/paths.py）===',
        f'  包根      : {PKG_ROOT}',
        f'  数据根    : {DATA_ROOT}',
        f'  来源      : {DATA_ROOT_SOURCE}',
        f'  形态      : {resolve_form()}'
        + {'A': '（外置数据根可用）', 'B': '（包内数据可用）', 'C': '（降级）'}[resolve_form()],
    ]
    for key, label in (('db', '主库'), ('index', '索引'), ('vectors', '向量'),
                       ('statements', '论断'), ('jinyu', '金句')):
        p, form = _pick(key)
        mark = {'A': 'A', 'B': 'B', None: '缺失'}[form]
        size = f'{os.path.getsize(p)/1024/1024:.1f}MB' if os.path.exists(p) else '-'
        lines.append(f'  {label:4s}[{mark:2s}] {p}  {size}')
    v_on, v_note = vector_status()
    lines.append(f'  向量路    : {"启用" if v_on else "关闭"} — {v_note}')
    return '\n'.join(lines)


if __name__ == '__main__':
    print(describe())
    notice = degradation_notice()
    if notice:
        print()
        print(notice)
