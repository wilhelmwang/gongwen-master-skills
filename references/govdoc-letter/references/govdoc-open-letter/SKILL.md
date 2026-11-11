---
name: govdoc-open-letter
tags: [govdoc, 公文, 公开信]
version: 2.0.0
description: "Use when the user asks to draft, revise, structure, or review Chinese official 公开信. Trigger keywords: 致市民/群众的公开信；倡议书、呼吁书；感谢信、慰问信；回应社会关切的公开信。常用触发：公开信、致全体、致市民、倡议书、回应关切。"
copyright: "Gongwen Master Contributors © Apache-2.0"
---

# 公开信写作

## 触发场景

- 致市民/群众的公开信；倡议书、呼吁书；感谢信、慰问信；回应社会关切的公开信。

## 不适用

- 内部通知（→govdoc-notice）；普通信函（->govdoc-letter）。

## 文种类型

- 公开信、倡议书、呼吁书、感谢信

## 公共规范（统一持有）

本模块的输入清单、输出形态，以及 GB/T 9704 格式规范、行文规则、15 种法定公文、
常见错误与规避、质量检查清单，统一持有在 `../../../shared-templates.md`（见该文件「文种模块公共规范」各节）。

**执行本模块工作流前，须先读取上述文件对应小节**，默认工作流为：
1. 明确任务 → 2. 收集信息 → 3. 按**本模块自己的** `references/formulas.md` 套用结构 → 4. 按上述文件质量检查


## 第三方组件与许可
本 Skill 聚合或引用了若干第三方开源组件，它们各自遵循其原始许可证（非本文件 Apache-2.0），商业化再分发时须一并保留其许可与声明。完整清单见仓库根目录 `THIRD_PARTY_NOTICES.md`。
