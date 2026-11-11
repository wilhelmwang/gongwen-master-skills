#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精品审核·第一段：确定性预筛 + 摘要导出（无 LLM）

把池子里的正文压成「评审摘要」供子 agent 批量判定，先在本机做掉不需要 LLM 的部分：

  硬性剔除（不送审，直接标 reject）
    · 正文过短（按文种定阈值）
    · 网页残留过重（导航/页脚/版权/二维码等样板行占比超限）
    · 名单体（大量 2-4 字短行，如政协委员名单）
    · 目录页（标题含「目录」「汇编目录」「一览表」）
    · 正文与标题无关的串扰件

  评审摘要字段（每篇一行 JSON，约 600-900 字符）
    id / type / title / chars / paras / heads / boiler / outline / head_txt / tail_txt

**只读不写**：摘要逐行打到 stdout，由调用方重定向分批落盘，再交给子 agent。

用法
----
  python export_review.py --type 会议纪要 --limit 40 > batch_jiyao_1.jsonl
  python export_review.py --stats                 # 看各文种可送审量
"""
import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'corpus'))
import sweep_columns as sw

POOL = os.path.join(sw.OUT_DIR, 'collected.jsonl')

#: 送审最短篇幅（字符）。消息/纪要天然短，阈值低些。
MIN_CHARS = {'会议纪要': 400, '消息': 320, '调研报告': 700,
             '工作报告': 1500, '工作总结': 600}
DEFAULT_MIN = 500

#: 样板行特征（导航、页脚、版权、二维码、无障碍声明…）
BOILER_PAT = re.compile(
    r'版权|版权所有|ICP备|网站地图|主办单位|主办：|承办单位|承办：|技术支持|政府网站标识码|'
    r'公安备案|备案号|关注我们|扫一扫|微信|微博|手机版|无障碍|字体|打印|关闭窗口|'
    r'上一页|下一页|上一篇|下一篇|分享到|返回顶部|联系我们|网站声明|法律声明|'
    r'政务新媒体|新媒体矩阵|友情链接|索引号|索\s*引\s*号|发文机关|发文字号|'
    r'发文单位|发布机构|责任部门|联系方式|联系电话|'
    r'浏览次数|访问量|点击量|来源：本站|责任编辑|编辑：|成文日期|主题分类|'
    r'当前位置|您的位置|首页\s*>|长者专区|IPv6|个人中心|搜\s*索')

#: 会议纪要两个「摘要里看不全」的必备构件——单独抽布尔位，否则判不了体例合规
ATTEND_PAT = re.compile(r'出席|列席|参加(?:了)?(?:会议|此次)|与会|参会')
VOTE_PAT = re.compile(r'会议(?:原则)?(?:同意|通过|议定|决定)|经研究|研究决定|'
                      r'原则同意|审议通过|会议审议|表决|一致同意|会议听取了?并')

DIR_PAT = re.compile(r'目录$|目录（|汇编目录|一览表|名册|名单$|通讯录')
LIST_PAT = re.compile(r'名单|名录|一览表|名册|任免|表彰名单|委员名单')
URL_ONLY_PAT = re.compile(r'^\s*(https?://|www\.)\S+\s*$')
#: 政务 CMS 注入正文的元数据行：数字 ID、日期时间、栏目名、来源署名
META_PAT = re.compile(
    r'^\d{4,}$|^\d{4}[-/年]\d{1,2}[-/月]\d{1,2}.*\d{1,2}:\d{2}|^\d+/\d+/\d+\s+\d+:\d+|'
    r'^(综合报道|时政要闻|统计新闻|要闻动态|政务动态|工作动态|新闻中心|图片新闻|'
    r'媒体聚焦|通知公告|热点关注|部门动态|市县动态|视频新闻|专题报道|信息来源)$|'
    r'^(来源|作者|编辑|责任编辑|发布时间|更新时间|浏览次数|字体|打印|分享)\s*[:：]?\s*.*$|'
    r'^[A-Za-z0-9]{6,}$')
HEAD_PAT = re.compile(r'^\s*(?:[（(]?[一二三四五六七八九十]+[）)、.．]|\d+[、.．]\s*)(.{2,24})$')


def load_pool():
    recs = {}
    if not os.path.exists(POOL):
        return recs
    with open(POOL, 'rb') as f:
        for line in f:
            try:
                r = json.loads(line.decode('utf-8', 'replace'))
            except Exception:
                continue
            u = r.get('url')
            if u and u not in recs:
                recs[u] = r
    return recs


def lines_of(text):
    return [x.strip() for x in (text or '').split('\n') if x.strip()]


def drop_menu_runs(ls, run=8, maxlen=6):
    """丢掉「连续 run 行以上的无标点短行」——站群导航菜单块。

    实测：贵州人大系站点的正文容器里混进了整块站群导航
    （"个人中心 / 搜 索 / 贵州省人大网站群：/ 遵义 / 六盘水 / …" 连续两百余行），
    它让正常的调研稿被数成"220 行、其中 170 行是短行"，因而误判为名单体。
    正常公文的段落成句，不会出现连续 8 行以上、每行 ≤6 字且不含标点的块。
    """
    out, i, n = [], 0, len(ls)
    while i < n:
        j = i
        while j < n and len(ls[j]) <= maxlen and not re.search(r'[。，、；：？！,.;:?!]', ls[j]):
            j += 1
        if j - i >= run:
            i = j                      # 整块丢弃
            continue
        out.append(ls[i])
        i += 1
    return out


def cleaned_lines(rec):
    """去掉网页样板、CMS 元数据行与导航菜单块后的正文行，以及被丢掉的占比。

    这一步是必需的前置：政务 CMS 会把「标题重复 / 数字 ID / 日期 / 来源 / 栏目名」
    以及整块站群导航塞进正文容器，实测这类行能占到八成。不清掉就无法判断正文形态——
    之前两版名单体判据都是被这些噪声带偏的（先误杀 5,137 篇，再误杀 3,007 篇）。
    """
    ls = lines_of(rec.get('content') or '')
    title = re.sub(r'\s+', '', (rec.get('title') or ''))
    keep, drop = [], 0
    for x in ls:
        xr = re.sub(r'\s+', '', x)
        if (BOILER_PAT.search(x) or URL_ONLY_PAT.match(x) or META_PAT.match(x)
                or (title and xr and (xr == title or title.startswith(xr) and len(xr) >= 8))):
            drop += 1
            continue
        keep.append(x)
    kept = drop_menu_runs(keep)
    drop += len(keep) - len(kept)
    return kept, (drop / len(ls) if ls else 1.0)


def score_boiler(ls):
    """样板行占比——**只认真正的网页残留**，不能把「短行」当样板。

    踩过的坑：初版把 `len(x) <= 6` 也算样板，结果中文公文里满是小标题与短段落，
    7,831 篇里 5,137 篇被误判为 boiler（预筛通过率只剩 7%）。
    公文体的短行是正常形态，真正的样板是版权/备案/导航这类固定串。
    """
    if not ls:
        return 1.0
    bad = sum(1 for x in ls if BOILER_PAT.search(x) or URL_ONLY_PAT.match(x))
    return bad / len(ls)


def is_list_body(ls):
    """名单体判定：几乎不含句号（无成句段落），且短行占多数。

    单看「短行多」会误伤正常公文（"恩施市民宿产业高质量发展调研报告"就这么被误判过），
    加上「几乎没有句号」这条才分得开——名单是一行一个人名，没有句子。

    仍然只在**清洗后的行**上判定：未清洗时"国家统计局…解读CPI"这类正文也会
    因元数据行过多而被误判（实测 3,007 篇里有大量真文章）。
    """
    if len(ls) < 20:
        return False
    short = sum(1 for x in ls if 2 <= len(x) <= 4)
    dot = sum(1 for x in ls if '。' in x)
    return short / len(ls) > 0.45 and dot / len(ls) < 0.12


def outline_of(ls, limit=8):
    out = []
    for x in ls:
        if len(x) > 26:
            continue
        m = HEAD_PAT.match(x)
        if m:
            h = m.group(1).strip('。，,、；;：:')
            if 2 <= len(h) <= 22 and h not in out:
                out.append(h)
        if len(out) >= limit:
            break
    return out


def window_around(text, pat, before=90, after=170):
    """取关键词附近的一段原文。用于把「出席名单」「表决结论」这类
    位置不固定的构件从正文里捞出来——它们通常在文末或段落中部，
    固定切首尾窗口照不到（首轮评审 40 篇里有 2 个必备构件因此不可判）。"""
    m = pat.search(text)
    if not m:
        return ''
    a = max(0, m.start() - before)
    return text[a:m.end() + after].replace('\n', ' ')


def digest(rec):
    ls, meta = cleaned_lines(rec)
    raw = lines_of(rec.get('content') or '')
    body = '\n'.join(ls)
    flat = re.sub(r'\s+', '', body)
    t = (rec.get('title') or '').replace('\n', ' ').strip()
    host = ''
    m = re.match(r'https?://([^/]+)', rec.get('url') or '')
    if m:
        host = m.group(1)
    return {
        # id 用 sha256 派生，**不用内置 hash()**——后者按进程随机化，重跑就对不上，
        # 导致子 agent 的评审结果无法回溯（rev_out_jiyao_1/2 已因此成为死键）。
        # 同时输出 url，让绑定不依赖 id 本身。
        'id': (rec.get('key', '') + '#'
               + hashlib.sha256((rec.get('url') or '').encode('utf-8')).hexdigest()[:8]),
        'url': rec.get('url', ''),
        'type': rec.get('doc_type', ''),
        'title': t[:80],
        'chars': len(body),
        'chars_raw': rec.get('chars') or 0,
        'meta_ratio': round(meta, 3),
        'paras': len(ls),
        'heads': len(outline_of(ls)),
        # residue＝**原始文本**里样板行的占比。
        # 曾在清洗后的行上算它 → 清洗已把样板删掉，指标恒为 0（自己把自己废掉的写法）。
        'residue': round(score_boiler(raw), 3),
        # noise_lines＝被清洗掉的行数（元数据 + 样板 + 导航块）。
        # 锚点表按「残留几行」分档，只给比例无法对号入座——评审实测提出过这一点。
        # ⚠️ 它会低估：仍有少量导航行逃过清洗，故判档时还要**看 head_txt / tail_txt 窗口内实际可见的非正文行**。
        'noise_lines': len(raw) - len(ls),
        # 两个位置不固定的构件单独给布尔位与就近原文，避免"摘要看不到 = 判定不了"
        'has_attend': bool(ATTEND_PAT.search(flat)),
        'has_vote': bool(VOTE_PAT.search(flat)),
        'attend_txt': window_around(flat, ATTEND_PAT),
        'vote_txt': window_around(flat, VOTE_PAT),
        'src_host': host,
        'skel': skel_hash(ls),
        'outline': outline_of(ls),
        'head_txt': body[:300].replace('\n', ' '),
        'tail_txt': body[-300:].replace('\n', ' ') if len(body) > 360 else '',
    }


def skel_hash(ls):
    """骨架指纹：取小标题与段首字，用于批次内识别同模板近重复稿。
    首轮评审发现 40 篇全部来自同一站点同一模板，单篇判分会让精品池被同源稿占满。"""
    parts = outline_of(ls, limit=6) or [x[:12] for x in ls[:4]]
    h = hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()
    return h[:10]


def prescreen(rec):
    """返回 (是否送审, 剔除原因)。判定一律在**清洗后的正文**上做"""
    t = rec.get('title') or ''
    ls, _meta = cleaned_lines(rec)
    dt = rec.get('doc_type', '')
    th = MIN_CHARS.get(dt, DEFAULT_MIN)
    n = sum(len(x) for x in ls)
    if n < th:
        return False, 'too_short'
    if len(ls) < 3:
        return False, 'few_paras'
    if is_list_body(ls):
        return False, 'list_body'
    if DIR_PAT.search(t) and n < 2200:
        return False, 'dir_page'
    if score_boiler(ls) > 0.15:
        return False, 'boiler'
    return True, ''


def main():
    ap = argparse.ArgumentParser(description='精品审核·预筛与摘要导出（只读）')
    ap.add_argument('--type', default='', help='只导出某文种')
    ap.add_argument('--offset', type=int, default=0)
    ap.add_argument('--limit', type=int, default=40)
    ap.add_argument('--stats', action='store_true')
    ap.add_argument('--why', action='store_true', help='打印剔除原因分布')
    a = ap.parse_args()

    recs = load_pool()
    if not recs:
        print('池子读不到:', POOL, file=sys.stderr)
        return 2

    keep, drop = [], Counter()
    for r in recs.values():
        ok, why = prescreen(r)
        if ok:
            keep.append(r)
        else:
            drop[why] += 1

    if a.stats:
        by = Counter(r.get('doc_type') for r in keep)
        tot = Counter(r.get('doc_type') for r in recs.values())
        print(f'池子 {len(recs)} 篇 ｜ 预筛通过 {len(keep)} 篇 '
              f'（{len(keep)*100//max(len(recs),1)}%）')
        for t in ('会议纪要', '消息', '调研报告', '工作报告', '工作总结'):
            print(f'   {t:6s} {tot[t]:5d} → 送审 {by[t]:5d}')
        print('剔除原因分布:', dict(drop.most_common()))
        return 0

    if a.why:
        print(dict(drop.most_common()))
        return 0

    pool = [r for r in keep if (not a.type or r.get('doc_type') == a.type)]
    pool.sort(key=lambda r: (r.get('key') or '', r.get('url') or ''))
    page = pool[a.offset:a.offset + a.limit]
    for r in page:
        print(json.dumps(digest(r), ensure_ascii=False), flush=True)
    print(f'# 送审 {len(page)}/{len(pool)} 篇'
          f'{"（" + a.type + "）" if a.type else ""}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
