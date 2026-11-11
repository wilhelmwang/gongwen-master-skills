#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
敏感词检测系统
基于DFA算法，支持多分类、通配符、模糊匹配
"""

import os
import json
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import sys


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


# 配置
BASE_DIR = Path(__file__).parent.parent
DICT_DIR = BASE_DIR / "dictionaries"
DICT_DIR.mkdir(parents=True, exist_ok=True)


class TrieNode:
    """Trie树节点"""
    
    def __init__(self):
        self.children = {}
        self.is_end = False
        self.word = None
        self.tag = None


class SensitiveChecker:
    """敏感词检测器"""
    
    def __init__(self):
        self.root = TrieNode()
        self.word_count = 0
        self.tag_stats = defaultdict(int)
        self._load_dictionaries()
    
    def _load_dictionaries(self):
        """加载词典"""
        # 内置基础词典
        builtin_words = {
            "政治敏感": [
                "台独", "港独", "藏独", "疆独",
                "法轮功", "六四", "天安门事件",
            ],
            "违法信息": [
                "赌博", "毒品", "枪支", "爆炸物",
            ],
            "不当表述": [
                "他妈的", "操你", "傻逼", "草泥马",
            ],
        }
        
        # 加载内置词典
        for tag, words in builtin_words.items():
            for word in words:
                self.add_word(word, tag)
        
        # 尝试加载外部词典
        self._load_external_dictionaries()
        
        # 加载Sensitive-lexicon词库
        self._load_sensitive_lexicon()
        
        print(f"[SENSITIVE] 加载完成: {self.word_count} 个敏感词")
    
    def _load_external_dictionaries(self):
        """加载外部词典"""
        # 尝试从合并词典加载（最大词库）
        ext_dict_path = DICT_DIR / "merged" / "sensitive_words_all.txt"
        if ext_dict_path.exists():
            try:
                with open(ext_dict_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        word = line.strip()
                        if word and not word.startswith('#') and len(word) >= 2:
                            self.add_word(word, "敏感词")
                print(f"[SENSITIVE] 加载合并词典: {ext_dict_path}")
            except Exception as e:
                print(f"[SENSITIVE] 加载合并词典失败: {e}")
    
    def _load_sensitive_lexicon(self):
        """加载Sensitive-lexicon词库"""
        lexicon_dir = DICT_DIR / "Sensitive-lexicon" / "Vocabulary"
        if not lexicon_dir.exists():
            return
        
        # 按文件类型加载
        tag_mapping = {
            "政治类型.txt": "政治敏感",
            "反动词库.txt": "政治敏感",
            "色情类型.txt": "色情",
            "色情词库.txt": "色情",
            "暴恐词库.txt": "暴恐",
            "涉枪涉爆.txt": "涉枪涉爆",
            "贪腐词库.txt": "贪腐",
            "民生词库.txt": "民生",
            "广告类型.txt": "广告",
            "COVID-19词库.txt": "疫情",
            "其他词库.txt": "其他",
        }
        
        loaded_count = 0
        for filename, tag in tag_mapping.items():
            filepath = lexicon_dir / filename
            if filepath.exists():
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        for line in f:
                            word = line.strip()
                            if word and not word.startswith('#') and len(word) >= 2:
                                self.add_word(word, tag)
                                loaded_count += 1
                except Exception as e:
                    print(f"[SENSITIVE] 加载 {filename} 失败: {e}")
        
        if loaded_count > 0:
            print(f"[SENSITIVE] 加载Sensitive-lexicon: {loaded_count} 条")
    
    def add_word(self, word, tag=None):
        """
        添加敏感词
        
        参数：
            word: 敏感词
            tag: 标签（如：政治敏感、违法信息等）
        """
        node = self.root
        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        
        if not node.is_end:
            self.word_count += 1
        
        node.is_end = True
        node.word = word
        node.tag = tag
        
        if tag:
            self.tag_stats[tag] += 1
    
    def check(self, text):
        """
        检测敏感词
        
        参数：
            text: 待检测文本
        
        返回：
            {
                "found": True/False,
                "count": 3,
                "matches": [
                    {
                        "word": "敏感词",
                        "tag": "政治敏感",
                        "start": 5,
                        "end": 8
                    }
                ],
                "by_tag": {"政治敏感": 2, "违法信息": 1}
            }
        """
        matches = []
        
        # 遍历文本
        i = 0
        while i < len(text):
            node = self.root
            j = i
            last_match = None
            
            while j < len(text) and text[j] in node.children:
                node = node.children[text[j]]
                j += 1
                
                if node.is_end:
                    last_match = {
                        'word': node.word,
                        'tag': node.tag,
                        'start': i,
                        'end': j
                    }
            
            if last_match:
                matches.append(last_match)
                i = last_match['end']
            else:
                i += 1
        
        # 统计
        by_tag = defaultdict(int)
        for match in matches:
            by_tag[match['tag']] += 1
        
        return {
            'found': len(matches) > 0,
            'count': len(matches),
            'matches': matches,
            'by_tag': dict(by_tag)
        }
    
    def replace(self, text, replacement='*'):
        """
        替换敏感词
        
        参数：
            text: 待替换文本
            replacement: 替换字符
        
        返回：
            替换后的文本
        """
        result = list(text)
        matches = self.check(text)['matches']
        
        # 从后往前替换，避免索引偏移
        for match in reversed(matches):
            start = match['start']
            end = match['end']
            word_len = end - start
            result[start:end] = [replacement] * word_len
        
        return ''.join(result)
    
    def get_stats(self):
        """获取统计信息"""
        return {
            'word_count': self.word_count,
            'tag_stats': dict(self.tag_stats),
            'last_update': datetime.now().isoformat()
        }


# 快速检测接口
def check_sensitive(text):
    """快速检测敏感词"""
    checker = SensitiveChecker()
    return checker.check(text)


def replace_sensitive(text, replacement='*'):
    """快速替换敏感词"""
    checker = SensitiveChecker()
    return checker.replace(text, replacement)


if __name__ == '__main__':
    import sys
    checker = SensitiveChecker()
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == 'check':
            text = ' '.join(sys.argv[2:])
            result = checker.check(text)
            
            print(f"\n敏感词检测: {text}")
            print("=" * 50)
            print(f"发现敏感词: {result['count']} 个")
            
            if result['found']:
                print(f"\n详细信息:")
                for match in result['matches']:
                    print(f"  - {match['word']} (标签: {match['tag']}, 位置: {match['start']}-{match['end']})")
                
                print(f"\n按标签统计:")
                for tag, count in result['by_tag'].items():
                    print(f"  {tag}: {count}")
        
        elif cmd == 'replace':
            text = ' '.join(sys.argv[2:])
            replaced = checker.replace(text)
            print(f"替换后: {replaced}")
        
        elif cmd == 'stats':
            stats = checker.get_stats()
            print(f"\n敏感词库统计:")
            print(f"  总词数: {stats['word_count']}")
            print(f"  按标签:")
            for tag, count in stats['tag_stats'].items():
                print(f"    {tag}: {count}")
        
        else:
            print("用法:")
            print("  python sensitive_checker.py check <text>  # 检测敏感词")
            print("  python sensitive_checker.py replace <text>  # 替换敏感词")
            print("  python sensitive_checker.py stats  # 查看统计")
    
    else:
        # 测试
        test_text = "这是一段测试文本，包含一些敏感词如台独和赌博。"
        result = checker.check(test_text)
        print(f"测试: {test_text}")
        print(f"结果: {result}")
