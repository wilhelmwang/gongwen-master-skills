---
name: govdoc-speech
tags: [govdoc, 公文, 讲话稿/演讲稿]
display_name: "公文·讲话稿写作"
display_name_en: "govdoc-speech"
description_zh: "讲话稿写作（gongwen-master 子技能，遵循 master 路由流程）"
visibility: "public"
version: "2.0.0"
description: "当用户让我「写/起草/润色/修改/质检」讲话稿类公文（领导讲话/致辞/动员/表态发言）。触发词：讲话、致辞、动员、动员部署、表态发言、会议讲话。"
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

# 领导讲话写作

## 触发场景

- 动员部署类领导讲话；推进会、工作会、座谈会领导讲话代拟稿；分析领导风格、上级精神、工作思路后生成讲话。

## 不适用

- 普通个人座谈发言（->govdoc-reflection）；工作汇报（->govdoc-summary）。

## 文种类型

- 动员部署讲话、推进会讲话、座谈会讲话、任职讲话、总结讲话

## 公共规范（统一持有）

本模块的输入清单、输出形态，以及 GB/T 9704 格式规范、行文规则、15 种法定公文、
常见错误与规避、质量检查清单，统一持有在 `../shared-templates.md`（见该文件「文种模块公共规范」各节）。

**执行本模块工作流前，须先读取上述文件对应小节**，默认工作流为：
1. 明确任务 → 2. 收集信息 → 3. 按**本模块自己的** `references/formulas.md` 套用结构 → 4. 按上述文件质量检查


## 第三方组件与许可
本 Skill 聚合或引用了若干第三方开源组件，它们各自遵循其原始许可证（非本文件 Apache-2.0），商业化再分发时须一并保留其许可与声明。完整清单见仓库根目录 `THIRD_PARTY_NOTICES.md`。

## 风格升级提示（v7.1.3 两段式流水线）

成稿交付时附一行轻提示（**仅对讲话/动员/表态类显示**）：

> 需要更有个性的表达？可按文风风格深度优化（如耿彦波式/郑栅洁式），说「升级文风」或直接点名风格即可；画像中已有常用风格的会自动询问是否套用。

降频规则：用户首次使用升级后写入画像，此后提示每 3 次成稿出现一次；用户明言「不用提示」则停用。
