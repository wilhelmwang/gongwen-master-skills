# -*- coding: utf-8 -*-
"""datahub 统一访问层（v1.1 · 2026-09-11）
上层业务通过 DataHub 访问任意资产，不感知物理路径：
  dh.resolve('qs.articles') → 绝对路径
  dh.connect('hs.data') / dh.query(name, sql) / dh.read(name) / dh.search('qs.articles', q)

v1.1：与 datahub/paths.py 对齐——外置资产由 assets.json 的绝对路径登记承载，
外置不可用时消费方应经 paths 回退包内（形态 B）或显式降级（形态 C）。
"""
import json, os, sqlite3

DHUB = os.path.dirname(os.path.abspath(__file__))

class DataHub:
    def __init__(self, reg=None):
        reg = reg or os.path.join(DHUB, 'assets.json')
        raw = json.load(open(reg, encoding='utf-8'))
        self.data_root = raw.get('data_root')
        self._a = {a['name']: a for a in raw['assets']}

    def resolve(self, name):
        a = self._a[name]
        return os.path.join(DHUB, a['path']) if not os.path.isabs(a['path']) else a['path']

    def connect(self, name):
        a = self._a[name]
        if a['type'] != 'sqlite':
            raise TypeError(f"{name} 非 sqlite 资产")
        c = sqlite3.connect(self.resolve(name))
        if a.get('readonly'):
            c.execute('PRAGMA query_only = ON')
        return c

    def query(self, name, sql, params=()):
        c = self.connect(name)
        try:
            return c.execute(sql, params).fetchall()
        finally:
            c.close()

    def read(self, name):
        a, p = self._a[name], self.resolve(name)
        if a['type'] == 'dir':
            return p
        if a['format'] == 'json':
            return json.load(open(p, encoding='utf-8'))
        if a['format'] == 'md':
            return open(p, encoding='utf-8').read()
        if a['format'] == 'npy':
            import numpy as np
            return np.load(p, allow_pickle=False)
        if a['format'] == 'pickle':
            # 反序列化护栏：仅接受包内数据根下的产物（拒绝外部不可信 pickle）
            from paths import DATA_ROOT as _dr
            if os.path.commonpath([os.path.realpath(p), os.path.realpath(_dr)]) != os.path.realpath(_dr):
                raise ValueError(f'pickle 写点越界，已拒绝: {p}')
            import pickle
            return pickle.load(open(p, 'rb'))
        raise ValueError(a.get('format'))

    def search(self, name, query, **kw):
        import subprocess, sys
        a = self._a[name]
        eng = a['engine']
        if 'qiushi_engine' in eng:
            sys.path.insert(0, os.path.join(os.path.dirname(DHUB), 'datahub', 'scripts', 'qs'))
            from qiushi_engine import SemanticSearch
            return SemanticSearch().search(query, mode='hybrid3', **kw)
        raise NotImplementedError(eng)

    def rebuild(self, name):
        a = self._a[name]
        cmd = a.get('rebuild')
        if not cmd:
            raise KeyError(f'{name} 无 rebuild 命令')
        import subprocess
        return subprocess.run(cmd.split(' '), cwd=os.path.dirname(DHUB), capture_output=True,
                              text=True, encoding='utf-8', errors='replace')

if __name__ == '__main__':
    dh = DataHub()
    print('验证 assets:', len(dh._a), '项')
    print('data_root:', dh.data_root)
    n = dh.query('qs.articles', 'SELECT COUNT(*) FROM articles')[0][0]
    print('qs.articles:', n, '篇')
