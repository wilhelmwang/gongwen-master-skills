# -*- coding: utf-8 -*-
"""LLM 客户端（rerank / judge / 生成共用）

凭据只读环境变量：`GONGWEN_LLM_KEY` 或 `OPENCODE_GO_API_KEY`（后者缺省回退）。
端点可覆盖：`GONGWEN_LLM_ENDPOINT`（如指向本地网关 `http://127.0.0.1:35555/v1/chat/completions`）。

v7.3.1 变更（把写死的配置全部环境变量化）
  · `MODEL` 原写死 `'mimo-v2.5'` 且**不可覆盖** —— 而本包自己的 assets.json 就记录了
    mimo「判别一致率 1/3、四维区分度失效」，属自相矛盾。现改为
    `GONGWEN_MODEL` 可覆盖，默认回落到 judge 同款强模型。
  · `LOCAL_MODEL` 原写死本地网关模型组名，现 `GONGWEN_LOCAL_MODEL` 可覆盖。
  · UA 伪装原硬编码，现 `GONGWEN_LLM_UA` 可覆盖（默认保留伪装：部分端点会拦
    Python-urllib 的 UA 返回 403）。
  · 超时可覆盖：`GONGWEN_LLM_TIMEOUT`。
"""
import json
import os
import urllib.request

#: 端点/凭据/模型/UA/超时 —— 全部可经环境变量覆盖
ENDPOINT = os.environ.get('GONGWEN_LLM_ENDPOINT', 'https://opencode.ai/zen/go/v1/chat/completions')
JUDGE_MODEL = os.environ.get('GONGWEN_JUDGE_MODEL', 'deepseek-v4-pro')
#: 通用（生成/重排）模型：默认与 judge 同款强模型（原先默认 mimo-v2.5，但其区分度已被实测否定）
MODEL = os.environ.get('GONGWEN_MODEL', JUDGE_MODEL)
LOCAL_MODEL = os.environ.get('GONGWEN_LOCAL_MODEL', 'deepseek-v4-flash-litellm')
UA = os.environ.get('GONGWEN_LLM_UA', 'curl/8.5.0')
#: v7.4.1：默认超时 60s → 180s。
#: 原因（子 agent 实测）：默认 judge 模型 deepseek-v4-pro 单次四维评分耗时 **62.0s**，
#: 超过原默认 60s —— 即"默认配置下 judge 必然超时失败"，属配置性缺陷而非模型问题。
#: 长文本评审更慢，故取 180s 留足余量；仍可用 GONGWEN_LLM_TIMEOUT 覆盖。
DEFAULT_TIMEOUT = float(os.environ.get('GONGWEN_LLM_TIMEOUT', '180'))


def load_key():
    """读取凭据（只从环境变量；不落盘、不写入日志）"""
    return os.environ.get('GONGWEN_LLM_KEY') or os.environ.get('OPENCODE_GO_API_KEY')


def chat(system, user, timeout=None, model=None):
    key = load_key()
    if not key:
        raise RuntimeError('缺少凭据环境变量（GONGWEN_LLM_KEY 或 OPENCODE_GO_API_KEY）')
    local = '127.0.0.1' in ENDPOINT or 'localhost' in ENDPOINT
    model = model or (LOCAL_MODEL if local else MODEL)
    body = json.dumps({
        'model': model, 'messages': [
            {'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
        'temperature': 0.1,
    }).encode('utf-8')
    from ipaddress import ip_address
    from urllib.parse import urlparse as _up
    _u = _up(ENDPOINT)
    if _u.scheme not in ('http', 'https'):
        raise ValueError(f'LLM 端点协议非法: {ENDPOINT[:60]}')
    _h = (_u.hostname or '').lower()
    if _h in ('', 'localhost') or _h.endswith('.local'):
        raise ValueError(f'LLM 端点指向本机/内网: {_h}')
    if not _h.isascii():
        raise ValueError(f'LLM 端点主机名非法: {_h}')
    _digits = _h.replace('.', '')
    if _digits.isdigit():
        _ip = ip_address(_h)
        if _ip.is_private or _ip.is_loopback or _ip.is_link_local or _ip.is_reserved:
            raise ValueError(f'LLM 端点指向保留地址: {_h}')
    req = urllib.request.Request(ENDPOINT, data=body, headers={
        'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
        'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout or DEFAULT_TIMEOUT) as r:
        data = json.loads(r.read().decode('utf-8'))
    return data['choices'][0]['message']['content']
