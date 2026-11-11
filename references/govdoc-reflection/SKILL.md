---
name: govdoc-reflection
tags: [govdoc, 公文, 心得体会/学习心得]
display_name: "公文·心得体会写作"
display_name_en: "govdoc-reflection"
description_zh: "心得体会写作（gongwen-master 子技能，遵循 master 路由流程）"
visibility: "public"
version: "2.0.0"
description: "当用户让我「写/起草/润色/修改/质检」心得体会类公文（学习心得/感想/体会文章）。触发词：心得、体会、感想、学习心得、观后感。"
compatibility: "Designed for WorkBuddy/Claude/豆包等 agent 技能平台（standalone 包）；引擎脚本需 Python 3.10+ 与 requirements.txt 依赖（jieba/numpy/scikit-learn/rank-bm25）；数据层 datahub/ 随包（详见 requires）"
requires:
  master: "gongwen-master（路由流程与六步法）"
  data: "可选引用 qiushi-db 数据中枢（经 gongwen-master 路由）"
permissions:
  fs_write: "无"
  network: "无"
  secrets: "无"
copyright: "Gongwen Master Contributors © Apache-2.0"
---

# 体会发言写作

## 触发场景

- 读书心得、培训体会、学习心得；青年干部座谈发言、交流发言；把个人收获与岗位工作结合成发言稿。

## 不适用

- 不用于领导讲话（->govdoc-speech）；不用于述职报告（->govdoc-report）或理论投稿文章（->govdoc-theory）。

## 文种类型

- 心得体会、读书心得、培训体会、座谈发言

## 公共规范（统一持有）

本模块的输入清单、输出形态，以及 GB/T 9704 格式规范、行文规则、15 种法定公文、
常见错误与规避、质量检查清单，统一持有在 `../shared-templates.md`（见该文件「文种模块公共规范」各节）。

**执行本模块工作流前，须先读取上述文件对应小节**，默认工作流为：
1. 明确任务 → 2. 收集信息 → 3. 按**本模块自己的** `references/formulas.md` 套用结构 → 4. 按上述文件质量检查


## 第三方组件与许可
本 Skill 聚合或引用了若干第三方开源组件，它们各自遵循其原始许可证（非本文件 Apache-2.0），商业化再分发时须一并保留其许可与声明。完整清单见仓库根目录 `THIRD_PARTY_NOTICES.md`。
