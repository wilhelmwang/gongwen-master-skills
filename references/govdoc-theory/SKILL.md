---
name: govdoc-theory
tags: [govdoc, 公文, 理论文章]
display_name: "公文·理论文章写作"
display_name_en: "govdoc-theory"
description_zh: "理论文章写作（gongwen-master 子技能，遵循 master 路由流程）"
visibility: "public"
version: "2.0.0"
description: "当用户让我「写/起草/润色/修改/质检」理论类公文（理论文章/政论文/思想评论）。触发词：理论、政论、理论文章、政论文、思想评论。"
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

# 理论文章写作

## 触发场景

- 主流媒体理论文章选题；围绕政策精神提炼核心观点和分论点；按目标媒体文风生成、压缩、修改理论文章。

## 不适用

- 不用于心得体会（->govdoc-reflection）或领导讲话（->govdoc-speech）；不替代学术论文写作和引用核查。

## 文种类型

- 理论文章、政策解读、政论文、学术文章

## 公共规范（统一持有）

本模块的输入清单、输出形态，以及 GB/T 9704 格式规范、行文规则、15 种法定公文、
常见错误与规避、质量检查清单，统一持有在 `../shared-templates.md`（见该文件「文种模块公共规范」各节）。

**执行本模块工作流前，须先读取上述文件对应小节**，默认工作流为：
1. 明确任务 → 2. 收集信息 → 3. 按**本模块自己的** `references/formulas.md` 套用结构 → 4. 按上述文件质量检查


## 第三方组件与许可
本 Skill 聚合或引用了若干第三方开源组件，它们各自遵循其原始许可证（非本文件 Apache-2.0），商业化再分发时须一并保留其许可与声明。完整清单见仓库根目录 `THIRD_PARTY_NOTICES.md`。
