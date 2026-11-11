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
"""求是语料向量化 v1.0（A-向量语义检索，2026-09-01）
5,568 篇正文切块 → bge-small-zh 嵌入 → qs_vectors.npy + qs_vectors.json（经 datahub/paths.py 定位）
环境：default venv（sentence-transformers 5.7.0），模型本地离线
"""
import sqlite3, os, json, sys, time
import numpy as np

# 数据路径：统一经 datahub/paths.py 解析（v7.3.0 单一事实源）
sys.path.insert(0, _DATA_ROOT)
from paths import db_path, vectors_path, vectors_meta_path
DB = db_path()
# 向量产物落点：与检索侧 _lazy_load_vec() 消费的 qs_vectors.* 同名同址。
# 此前写 article_vectors.npy / chunks.json，而引擎读 qs_vectors.npy / qs_vectors.json，
# 重建产物检索侧永远读不到 —— v7.3.0 对齐生产端与消费端命名。
VEC_OUT = vectors_path()
META_OUT = vectors_meta_path()
# v6.8.1（P0-2）：去除开发机硬编码路径，统一经环境变量 GONGWEN_BGE_MODEL 指定
MODEL = os.environ.get('GONGWEN_BGE_MODEL', '')
CHUNK = 380  # 字符/块
MAX_CHUNKS = 6  # 每篇最多块数

def main():
    if not MODEL or not os.path.isdir(MODEL):
        print('[gongwen] 未设置 GONGWEN_BGE_MODEL 环境变量（指向 bge-small-zh-v1.5 模型目录），无法生成向量。')
        print('[gongwen] 请设置后重试，例如：set GONGWEN_BGE_MODEL=D:/models/bge-small-zh-v1.5')
        sys.exit(2)
    os.makedirs(os.path.dirname(VEC_OUT), exist_ok=True)
    conn = sqlite3.connect(DB)
    rows = conn.execute('SELECT id, title, content FROM articles WHERE content IS NOT NULL AND length(content) > 100').fetchall()
    conn.close()
    print(f'待嵌入文章: {len(rows)}')

    from sentence_transformers import SentenceTransformer
    t0 = time.time()
    model = SentenceTransformer(MODEL)
    model.max_seq_length = 512
    print(f'模型加载完成 {time.time()-t0:.0f}s')

    chunks, meta = [], []
    for aid, title, content in rows:
        content = content.replace('\u3000', ' ').replace('\n', ' ')
        # 粗切块：按 CHUNK 字符切，保留完整句感（按句号附近切）
        sents = [s for s in content.replace('。', '。\n').split('\n') if s.strip()]
        cur = ''
        n = 0
        for s in sents:
            if len(cur) + len(s) > CHUNK and cur:
                chunks.append((title or f'a{aid}') + '。' + cur)
                meta.append((aid, n))
                n += 1
                cur = ''
            cur += s
            if n >= MAX_CHUNKS:
                break
        if cur and n < MAX_CHUNKS:
            chunks.append((title or f'a{aid}') + '。' + cur)
            meta.append((aid, n))
    print(f'总块数: {len(chunks)}')

    B = 64
    vecs = []
    for i in range(0, len(chunks), B):
        batch = chunks[i:i+B]
        e = model.encode(batch, normalize_embeddings=True, show_progress_bar=False)
        vecs.append(e.astype('float32'))
        if (i // B) % 20 == 0:
            print(f'  嵌入 {i+B}/{len(chunks)} ({time.time()-t0:.0f}s)', flush=True)
    V = np.vstack(vecs)
    np.save(VEC_OUT, V)
    from pathlib import Path as _P
    _P(META_OUT).write_text(json.dumps({'meta': [list(m) for m in meta],
                                        'dim': int(V.shape[1]), 'n': len(chunks)}), encoding='utf-8')
    print(f'完成: {V.shape} / {os.path.getsize(VEC_OUT)/1024/1024:.0f}MB → {VEC_OUT} / {time.time()-t0:.0f}s')

if __name__ == '__main__':
    main()
