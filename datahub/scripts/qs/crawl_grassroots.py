# -*- coding: utf-8 -*-
"""乡镇总结/经验材料公开源采集器 v1.0（2026-09-03）
用法：python crawl_grassroots.py <url1> [url2 ...]  # 抓正文存库
  或  python crawl_grassroots.py --list <列表页url>  # 解析链接列表批量抓
合规：仅抓政府门户公开页面；每页间隔 1.5s；robots 尊重（site:gov.cn 公开信息）
"""
import json, os, re, sys, time, urllib.request, html as htmllib
from urllib.parse import urljoin

# v6.8.1（P0-2）：硬编码改包根相对定位
BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 'datahub', 'derived', 'corpus', 'grassroots')
MANIFEST = os.path.join(BASE, 'manifest.json')

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36', 'Accept-Encoding': 'identity', 'Accept-Language': 'zh-CN,zh;q=0.9'}

def _safe_url(url):
    """外发请求护栏：仅 http/https 公网地址（防 file:/内网/loopback SSRF）"""
    import ipaddress
    from urllib.parse import urlparse
    u = urlparse(url)
    if u.scheme not in ('http', 'https'):
        raise ValueError(f'非 http(s) 地址已拒绝: {url[:60]}')
    host = (u.hostname or '').lower()
    bad = not host or host == 'localhost' or host.endswith('.local')
    if not bad:
        try:
            ip = ipaddress.ip_address(host)
            bad = ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
        except ValueError:
            bad = False
    if bad:
        raise ValueError(f'内网/保留地址已拒绝: {host or url[:60]}')
    return url


def fetch(url, tries=2):
    _safe_url(url)
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
            for enc in ('utf-8', 'gb18030'):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode('utf-8', 'ignore')
        except Exception as e:
            if i == tries - 1:
                return None
            time.sleep(2)

def extract_title(c):
    m = re.search(r'<title>(.*?)</title>', c, re.S)
    return htmllib.unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip()[:60] if m else 'untitled'

def extract_body(c):
    # 中国政务站常见正文容器
    m = re.search(r'<div[^>]*(?:class|id)="[^"]{0,60}(?:TRS_Editor|zoom|article|content|detail|zw|xxgk_content|conTxt|mainText|news_content)[^"]{0,60}"[^>]*>(.*?)</div>', c, re.S)
    seg = m.group(1) if m else c
    seg = re.sub(r'<script.*?</script>', '', seg, flags=re.S)
    seg = re.sub(r'<style.*?</style>', '', seg, flags=re.S)
    seg = re.sub(r'<[^>]+>', '', seg)
    seg = htmllib.unescape(seg)
    seg = re.sub(r'\s+', ' ', seg).strip()
    return seg

def gen_name(title, idx):
    clean = re.sub(r'[\\/:*?"<>|\s]+', '_', title)[:40]
    return f'{idx:04d}_{clean}.txt'

def main():
    os.makedirs(BASE, exist_ok=True)
    manifest = json.load(open(MANIFEST, encoding='utf-8')) if os.path.exists(MANIFEST) else {'items': []}
    done = {x['url'] for x in manifest['items']}
    urls = sys.argv[1:]
    if '--list' in urls:
        li = urls[urls.index('--list') + 1]
        c = fetch(li)
        if c:
            urls = [urljoin(li, u) for u in re.findall(r'href="([^"]+\.htm[l]?[^"]*)"', c)]
            urls = [u for u in urls if not u.endswith(('.css', '.js', '.png', '.jpg'))][:60]
            print(f'列表解析: {len(urls)} 链接')
        else:
            print('列表页拉取失败')
            return
    idx = len(manifest['items'])
    for u in urls:
        if u in done:
            continue
        c = fetch(u)
        if not c:
            print(f'  ✗ 拉取失败: {u[:70]}')
            continue
        body = extract_body(c)
        if len(body) < 800:
            print(f'  - 正文过短({len(body)}): {u[:66]}')
            continue
        title = extract_title(c)
        name = gen_name(f'{title}_{time.strftime("%Y%m%d")}', idx)
        if os.path.basename(name) != name or '..' in name:
            raise ValueError(f'非法文件名已拒绝: {name[:60]}')
        from pathlib import Path as _P
        _P(os.path.join(BASE, name)).write_text(f'{title}\n来源: {u}\n\n{body}', encoding='utf-8')
        manifest['items'].append({'url': u, 'file': name, 'title': title, 'len': len(body), 'ts': time.strftime('%Y-%m-%d')})
        idx += 1
        print(f'  ✓ [{idx}] {title[:36]} ({len(body)}字)')
        time.sleep(1.5)
    from pathlib import Path as _P
    _P(MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'采集完成: 累计 {len(manifest["items"])} 篇 → {BASE}')

if __name__ == '__main__':
    main()