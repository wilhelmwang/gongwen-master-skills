# -*- coding: utf-8 -*-
"""datahub 公共工具（v7.1 · 批次3 抽取）

从事务最佳范本（rebuild_fts.py 的分批提交）提炼通用函数，供 ingest/爬虫复用。

用法：
    from common import batched_write
    with db_writer('hs.db') as cur:
        for rows in batched(records, 200):
            cur.executemany('INSERT ...', rows)   # 每 200 行自动 commit
"""
from __future__ import annotations

import contextlib
import sqlite3
import time


@contextlib.contextmanager
def db_writer(db_path: str, timeout: float = 10.0, batch_size: int = 200,
              retries: int = 3):
    """受控写连接：显式事务 + 分批提交 + 锁重试 + 失败回滚。

    - 开启 BEGIN，每 batch_size 行 commit 一次（避免单巨事务锁库/malformed）；
    - 遇 database locked 按指数退避重试；
    - 异常时 rollback 当前批并抛出。
    """
    con = sqlite3.connect(db_path, timeout=timeout)
    con.execute("BEGIN")
    cur = con.cursor()
    pending = 0
    try:
        yield cur
        con.commit()
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower() and retries > 0:
            time.sleep(0.5 * (2 ** (retries - 3)))
            con.rollback()
            raise
        con.rollback()
        raise
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def batched(iterable, size: int):
    """切片生成器。"""
    buf = []
    for item in iterable:
        buf.append(item)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf
