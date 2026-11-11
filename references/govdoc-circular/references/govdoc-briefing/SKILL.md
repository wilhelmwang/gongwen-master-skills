---
name: govdoc-briefing
tags: [govdoc, 公文, 简报/专报/内参]
version: 2.0.0
description: "Use when the user asks to draft, revise, structure, or review Chinese official 简报. Trigger keywords: 日常工作简报、专题信息简报、会议情况简报、重大事项专报。常用触发：专报、内参、要情、情况专报。"
copyright: "Gongwen Master Contributors © Apache-2.0"
---

# 简报写作

## 触发场景

- 日常工作简报、专题信息简报、会议情况简报、重大事项专报。

## 不适用

- 领导讲话（→govdoc-speech）；普通工作信息（->govdoc-brief）。

## 文种类型

- 工作简报、专题简报、信息专报

## 公共规范（统一持有）

本模块的输入清单、输出形态，以及 GB/T 9704 格式规范、行文规则、15 种法定公文、
常见错误与规避、质量检查清单，统一持有在 `../../../shared-templates.md`（见该文件「文种模块公共规范」各节）。

**执行本模块工作流前，须先读取上述文件对应小节**，默认工作流为：
1. 明确任务 → 2. 收集信息 → 3. 按**本模块自己的** `references/formulas.md` 套用结构 → 4. 按上述文件质量检查


## 第三方组件与许可
本 Skill 聚合或引用了若干第三方开源组件，它们各自遵循其原始许可证（非本文件 Apache-2.0），商业化再分发时须一并保留其许可与声明。完整清单见仓库根目录 `THIRD_PARTY_NOTICES.md`。
