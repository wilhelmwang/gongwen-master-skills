#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
错别字检查系统
基于混淆集+编辑距离，支持中文拼写纠错
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


class SpellChecker:
    """错别字检查器"""
    
    def __init__(self):
        self.confusion_set = {}  # 混淆集
        self.custom_dict = {}    # 自定义词典
        self.whitelist = set()   # 白名单
        
        self._load_dictionaries()
    
    def _load_dictionaries(self):
        """加载词典"""
        # 内置常见混淆词
        builtin_confusion = {
            # 的/地/得 混用
            "的": {"地": ["的跑步", "的说话", "的唱歌"], "得": []},
            "地": {"的": ["慢慢地走", "静静地听"], "得": []},
            "得": {"的": ["跑得快", "做得好"], "地": []},
            
            # 常见错别字
            "在": {"再": ["在次", "在来"]},  # 应为"再次""再来"
            "再": {"在": ["再见", "再次"]},
            "做": {"作": ["做事", "做工"]},  # 特定语境
            "作": {"做": ["作业", "作文"]},
            "像": {"象": ["好像", "像貌"]},  # "像貌"应为"相貌"
            "象": {"像": ["大象", "气象"]},
            "己": {"已": ["自己", "己经"]},  # "己经"应为"已经"
            "已": {"己": ["已经", "已往"]},
            "他": {"她": ["他们", "他人"]},  # 特定语境
            "她": {"他": ["她们", "她人"]},
            "那": {"哪": ["那里", "那边"]},  # 特定语境
            "哪": {"那": ["哪里", "哪个"]},
            "做": {"作": ["做法", "做用"]},  # "做用"应为"作用"
            "作": {"做": ["作用", "作业"]},
            
            # 同音字错误
            "需": {"须": ["需要", "需求"]},
            "须": {"需": ["必须", "须知"]},
            "及": {"急": ["及时", "及格"]},
            "急": {"及": ["急忙", "急切"]},
            "以": {"已": ["以及", "以后"]},
            "已": {"以": ["已经", "早已"]},
            
            # 公文常见错误
            "截止": {"截至": ["截止目前"]},  # "截止目前"应为"截至目前"
            "截至": {"截止": ["截至日期"]},
            "制定": {"制订": ["制定计划"]},  # 语境不同
            "制订": {"制定": ["制订方案"]},
            "权利": {"权力": ["公民权利"]},
            "权力": {"权利": ["行政权力"]},
            "反应": {"反映": ["反应问题"]},  # "反应问题"应为"反映问题"
            "反映": {"反应": ["反映情况"]},
            "做": {"作": ["做工作"]},  # "做工作"应为"做工作"（可接受）
            "考察": {"考查": ["实地考察"]},
            "考查": {"考察": ["考查成绩"]},
        }
        
        # 加载内置混淆集
        for correct, confusions in builtin_confusion.items():
            self.confusion_set[correct] = confusions
        
        # 尝试加载外部混淆集
        self._load_external_confusion()
        
        print(f"[SPELL] 加载完成: {len(self.confusion_set)} 组混淆词")
    
    def _load_external_confusion(self):
        """加载外部混淆集"""
        # 加载pycorrector合并的混淆集
        ext_path = DICT_DIR / "merged" / "confusion_words_all.txt"
        if ext_path.exists():
            try:
                with open(ext_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        word = line.strip()
                        if word and not word.startswith('#') and len(word) >= 2:
                            # 简单添加到混淆集（实际应更复杂）
                            if word not in self.confusion_set:
                                self.confusion_set[word] = {}
                print(f"[SPELL] 加载合并混淆集: {ext_path}")
            except Exception as e:
                print(f"[SPELL] 加载合并混淆集失败: {e}")
        
        # 加载JSON格式混淆集
        json_path = DICT_DIR / "confusion_set.json"
        if json_path.exists():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.confusion_set.update(data)
                print(f"[SPELL] 加载JSON混淆集: {json_path}")
            except Exception as e:
                print(f"[SPELL] 加载JSON混淆集失败: {e}")
    
    def add_to_whitelist(self, words):
        """添加白名单"""
        if isinstance(words, list):
            self.whitelist.update(words)
        else:
            self.whitelist.add(words)
    
    def _calculate_similarity(self, s1, s2):
        """计算字符串相似度（编辑距离）"""
        if len(s1) == 0:
            return len(s2)
        if len(s2) == 0:
            return len(s1)
        
        matrix = [[0] * (len(s2) + 1) for _ in range(len(s1) + 1)]
        
        for i in range(len(s1) + 1):
            matrix[i][0] = i
        for j in range(len(s2) + 1):
            matrix[0][j] = j
        
        for i in range(1, len(s1) + 1):
            for j in range(1, len(s2) + 1):
                cost = 0 if s1[i-1] == s2[j-1] else 1
                matrix[i][j] = min(
                    matrix[i-1][j] + 1,
                    matrix[i][j-1] + 1,
                    matrix[i-1][j-1] + cost
                )
        
        max_len = max(len(s1), len(s2))
        return 1 - matrix[len(s1)][len(s2)] / max_len
    
    def check(self, text):
        """
        检查错别字
        
        参数：
            text: 待检查文本
        
        返回：
            {
                "found": True/False,
                "count": 2,
                "matches": [
                    {
                        "word": "己经",
                        "correct": "已经",
                        "start": 5,
                        "end": 7,
                        "confidence": 0.95
                    }
                ]
            }
        """
        matches = []
        
        # 按词检查
        words = self._tokenize(text)
        
        for word_info in words:
            word = word_info['word']
            start = word_info['start']
            end = word_info['end']
            
            # 跳过白名单
            if word in self.whitelist:
                continue
            
            # 检查混淆集
            for correct, confusions in self.confusion_set.items():
                for wrong, contexts in confusions.items():
                    if word == wrong:
                        # 简单上下文检查
                        context = text[max(0, start-2):min(len(text), end+2)]
                        confidence = 0.8  # 默认置信度
                        
                        matches.append({
                            'word': word,
                            'correct': correct,
                            'start': start,
                            'end': end,
                            'confidence': confidence,
                            'type': 'confusion'
                        })
        
        # 去重（按位置）
        seen_positions = set()
        unique_matches = []
        for match in matches:
            pos = (match['start'], match['end'])
            if pos not in seen_positions:
                seen_positions.add(pos)
                unique_matches.append(match)
        
        return {
            'found': len(unique_matches) > 0,
            'count': len(unique_matches),
            'matches': unique_matches
        }
    
    def _tokenize(self, text):
        """
        分词（简单实现）
        实际应使用jieba等分词工具
        """
        words = []
        i = 0
        
        while i < len(text):
            # 跳过空白和标点
            if text[i] in ' \t\n\r，。；：？！、""''（）【】《》':
                i += 1
                continue
            
            # 尝试匹配最长词
            max_len = min(4, len(text) - i)
            matched = False
            
            for length in range(max_len, 1, -1):
                word = text[i:i+length]
                if word in self.confusion_set or any(word in v for v in self.confusion_set.values()):
                    words.append({
                        'word': word,
                        'start': i,
                        'end': i + length
                    })
                    i += length
                    matched = True
                    break
            
            if not matched:
                # 单字也检查
                words.append({
                    'word': text[i],
                    'start': i,
                    'end': i + 1
                })
                i += 1
        
        return words
    
    def correct(self, text):
        """
        自动纠错
        
        参数：
            text: 待纠正文本
        
        返回：
            纠正后的文本
        """
        result = self.check(text)
        
        if not result['found']:
            return text
        
        # 从后往前替换
        corrected = list(text)
        for match in reversed(result['matches']):
            start = match['start']
            end = match['end']
            correct_word = match['correct']
            corrected[start:end] = list(correct_word)
        
        return ''.join(corrected)
    
    def get_stats(self):
        """获取统计"""
        return {
            'confusion_groups': len(self.confusion_set),
            'whitelist_size': len(self.whitelist),
            'last_update': datetime.now().isoformat()
        }


def check_spell(text):
    """快速检查接口"""
    checker = SpellChecker()
    return checker.check(text)


def correct_spell(text):
    """快速纠正接口"""
    checker = SpellChecker()
    return checker.correct(text)


if __name__ == '__main__':
    import sys
    checker = SpellChecker()
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == 'check':
            text = ' '.join(sys.argv[2:])
            result = checker.check(text)
            
            print(f"\n错别字检查: {text}")
            print("=" * 50)
            print(f"发现错别字: {result['count']} 个")
            
            if result['found']:
                print(f"\n详细信息:")
                for match in result['matches']:
                    print(f"  - {match['word']} → {match['correct']} (位置: {match['start']}-{match['end']}, 置信度: {match['confidence']:.0%})")
        
        elif cmd == 'correct':
            text = ' '.join(sys.argv[2:])
            corrected = checker.correct(text)
            print(f"纠正后: {corrected}")
        
        elif cmd == 'stats':
            stats = checker.get_stats()
            print(f"\n错别字词典统计:")
            print(f"  混淆组数: {stats['confusion_groups']}")
            print(f"  白名单大小: {stats['whitelist_size']}")
        
        else:
            print("用法:")
            print("  python spell_checker.py check <text>  # 检查错别字")
            print("  python spell_checker.py correct <text>  # 纠错")
            print("  python spell_checker.py stats  # 查看统计")
    
    else:
        # 测试
        test_texts = [
            "我己经完成了这项工作。",
            "截止目前，项目进展顺利。",
            "这个问题需要在次研究。",
            "大家的反映都很积极。",
        ]
        
        print("错别字检查测试:")
        print("=" * 50)
        for text in test_texts:
            result = checker.check(text)
            corrected = checker.correct(text)
            print(f"\n原文: {text}")
            print(f"纠正: {corrected}")
            if result['found']:
                for match in result['matches']:
                    print(f"  - {match['word']} → {match['correct']}")
