# -*- coding: utf-8 -*-
"""写前快照 + 轮转（「数据库四铁律④」的唯一实现处）

为什么需要轮转
--------------
快照本身是对的：改库前留一份可回退的副本。但**没有轮转的快照等于磁盘泄漏**——
范文池库约 1.4 GB，`build_samples_db.py` 与 `dedup_samples.py` 每跑一次各留一份，
实测一天内攒到 4 份 5.8 GB，是真实数据的 4 倍。故策略统一为「保留最近 N 份」。

三条容易写错的地方（都是实际撞过的）
------------------------------------
1. 只把**主库文件**（不带 `-wal`/`-shm`）计入份数；边车文件随同名的快照一起清。
2. SQLite 的 `-wal`/`-shm` **不随主库一起消失**：主库删了它们就是 0 字节孤儿
   （实测每次轮转都留 2 个垃圾文件），必须显式删。
3. `shutil.copy2` 会**保留源文件的 mtime**，所以快照文件的 mtime 是旧库最后写入的时间，
   不是快照时刻。排序判新旧要看**文件名里的时间戳**——故这里用文件名排序
   （`bak_YYYYmmdd_HHMMSS` 字典序 == 时间序）。
"""
import datetime
import glob
import os
import shutil


def _same(a, b):
    """路径是否指向同一文件（**先归一化再比**，不比字符串）

    必要性：调用方传进来的 db_path 可能是混合分隔符（正斜杠 + 反斜杠），
    `glob` 返回的却是全反斜杠形式；直接 `a != b` 会把同一个文件判成两个。
    """
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def take(db_path, keep=1, label=''):
    """写前快照，并按 keep 轮转旧快照（keep<0 表示不轮转，尽量别用）

    返回快照文件路径；源库不存在时返回 None。
    """
    if not os.path.exists(db_path):
        return None
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = f'{db_path}.bak_{ts}'
    shutil.copy2(db_path, bak)
    mib = os.path.getsize(bak) / 1048576
    print(f'写前快照: {os.path.basename(bak)}（{mib:.0f} MB）{label}')
    if keep < 0:
        return bak
    olds = sorted(g for g in glob.glob(db_path + '.bak_*')
                  if os.path.isfile(g) and not _same(g, bak)
                  and not g.endswith(('-wal', '-shm')))
    # ⚠️ 这条切片有两个必须**同时**成立的细节（2026-09-17 实测踩全，一度把新旧两份全删）：
    #   ① 新份必须**不在** `olds` 里 —— 靠 `_same` 归一化比较保证（`db_path` 可能是混合
    #      分隔符，字符串比较判不出"这就是新份"，新份会被算进待删列表 → 删光）。
    #   ② `+ 1` 必须有 —— 语义是"**总数**保留 keep 份"。只写 `- keep` 时，因为新份不在 olds 里，
    #      结果是"留 keep 份旧的 + 1 份新的"= keep+1 份（实测 keep=1 剩 2 份 2 GB）。
    # 判据：`_same` 管"新份不入选"，`+1` 管"总数等于 keep"，缺一个就错。
    for g in olds[:max(0, len(olds) - keep + 1)]:
        side = 0
        for suf in ('-wal', '-shm'):
            if os.path.exists(g + suf):
                try:
                    side += os.path.getsize(g + suf)
                    os.remove(g + suf)
                except OSError:
                    pass
        try:
            freed = os.path.getsize(g) / 1048576
            os.remove(g)
            print(f'  轮转删除旧快照: {os.path.basename(g)}'
                  f'（回收 {freed:.0f} MB 主库 + {side / 1024:.0f} KB 边车）')
        except OSError as e:
            print(f'  轮转删除失败（忽略）: {os.path.basename(g)} — {e}')
    return bak
