import os

def _find_root():
    """包根探测：向上找含 VERSION 的目录（目录改名/跨机部署自适应）"""
    import os
    p = os.path.dirname(os.path.abspath(__file__))
    while not os.path.exists(os.path.join(p, 'VERSION')) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    return p

_DATA_ROOT = os.path.join(_find_root(), 'datahub')
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""增量向量嵌入 v1.0（P0-3，2026-09-02）
对比 qiushi.db 与 vec/chunks.json 差集 → 仅嵌入新增文章 → 追加 npy/meta
环境：default venv（sentence-transformers）；模型路径可用环境变量 GONGWEN_BGE_MODEL 覆盖
"""
import sqlite3, os, json, sys, time
import numpy as np

# 数据路径：统一经 datahub/paths.py 解析（v7.3.0 单一事实源）
sys.path.insert(0, _DATA_ROOT)
from paths import db_path, vectors_path, vectors_meta_path
DB = db_path()
# 向量产物落点与检索侧消费端同名（qs_vectors.*），修复"重建写入 article_vectors.npy、
# 引擎却读 qs_vectors.npy"的断链（v7.3.0 对齐）。
VEC_NPY = vectors_path()
VEC_META = vectors_meta_path()
# v6.8.1（P0-2）：去除开发机硬编码路径，统一经环境变量 GONGWEN_BGE_MODEL 指定
MODEL = os.environ.get('GONGWEN_BGE_MODEL', '')
CHUNK, MAX_CHUNKS = 380, 6

def main():
    if not MODEL or not os.path.isdir(MODEL):
        print('[gongwen] 未设置 GONGWEN_BGE_MODEL 环境变量（指向 bge-small-zh-v1.5 模型目录），无法增量嵌入。')
        print('[gongwen] 请设置后重试，例如：set GONGWEN_BGE_MODEL=D:/models/bge-small-zh-v1.5')
        sys.exit(2)
    meta = json.load(open(VEC_META, encoding='utf-8'))['meta']
    done_ids = {m[0] for m in meta}
    conn = sqlite3.connect(DB)
    rows = conn.execute('SELECT id, title, content FROM articles WHERE content IS NOT NULL AND length(content) > 100').fetchall()
    conn.close()
    todo = [(a, t, ct) for a, t, ct in rows if a not in done_ids]
    print(f'库内 {len(rows)} 篇 / 已嵌入 {len(done_ids)} 篇 / 待增量 {len(todo)} 篇')
    if not todo:
        print('无增量，退出'); return

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL); model.max_seq_length = 512
    chunks, meta_new = [], []
    for aid, title, content in todo:
        content = content.replace('\u3000', ' ').replace('\n', ' ')
        sents = [s for s in content.replace('。', '。\n').split('\n') if s.strip()]
        cur, n = '', 0
        for s in sents:
            if len(cur) + len(s) > CHUNK and cur:
                chunks.append((title or f'a{aid}') + '。' + cur); meta_new.append((aid, n)); n += 1; cur = ''
            cur += s
            if n >= MAX_CHUNKS: break
        if cur and n < MAX_CHUNKS:
            chunks.append((title or f'a{aid}') + '。' + cur); meta_new.append((aid, n))
    print(f'增量块数: {len(chunks)}')
    V = np.load(VEC_NPY)
    vecs = []
    t0 = time.time()
    for i in range(0, len(chunks), 64):
        e = model.encode(chunks[i:i+64], normalize_embeddings=True)
        vecs.append(e.astype('float32'))
    Vnew = np.vstack(vecs)
    V2 = np.vstack([V, Vnew])
    np.save(VEC_NPY, V2)
    meta_all = meta + [list(m) for m in meta_new]
    from pathlib import Path as _P
    _P(VEC_META).write_text(json.dumps({'meta': meta_all, 'dim': int(V2.shape[1]),
                                        'n': len(meta_all)}), encoding='utf-8')
    print(f'增量完成: {V2.shape} / {time.time()-t0:.0f}s → 已追加保存')

if __name__ == '__main__':
    main()
