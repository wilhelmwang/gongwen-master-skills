---
name: govdoc-feedback
tags: [govdoc, 公文, 反馈意见]
version: 1.0.0
description: |
  Use when a user gives clear negative feedback while using Chinese official-document writing skills, such as 不好用, 不对, 不像, 太差, 没帮助, 改得不行, 还是不满意, or complains that a 公文写作 skill failed. This skill does not interrupt the current task; it appends a concise Feishu feedback questionnaire link after the current answer is completed.
copyright: "Gongwen Master Contributors © Apache-2.0"
---

# 公文技能反馈收集

## 目标

当用户在使用公文写作相关 skill 时明确表达不满，先继续完成当前任务，再在答复末尾轻量弹出飞书反馈问卷链接。不要为了收集反馈打断写作、审稿、诊断或修改。

## 飞书问卷

- 问卷名称：公文技能用户反馈问卷
- 多维表：公文技能用户反馈表
- 数据表：用户反馈
- 表单视图 ID：`vewBhagV2H`
- 问卷链接：`https://wqlkazav5r7.feishu.cn/share/base/shrcnksfDYwzmDCwvVGVfO3BBOb`
- 访问权限：互联网上获得链接的人可填写，不限制每位用户提交次数。
- 主题字段：用于填写本次反馈主题或用户想概括的问题。
- 触发技能字段：单选下拉，包含当前公文技能库中的全部 skill；每个选项采用“技能名｜中文介绍”，并保留“其他”兜底项。
- 附件字段：支持上传问题截图或相关文件，字段名为“问题截图或附件”。

## 触发条件

只在明确负反馈时触发，例如：

- 不好用
- 不对
- 不像
- 太差
- 没帮助
- 改得不行
- 还是不满意
- 这个 skill 不行
- 这个公文工具不好使

不触发：

- 普通修改要求，如“再正式一点”“帮我压缩”“换个标题”。
- 正常追问，如“为什么这样改”“能不能再给一版”。
- 轻微偏好，如“差点意思”“还可以再润润”，除非用户明显表达不满。

## 弹出时机

必须先完成当前任务。只有在当前答复末尾追加反馈邀请。

固定话术：

```text
这次体验如果不顺手，可以点这里填一下反馈，方便我后面把公文写作技能调好：
https://wqlkazav5r7.feishu.cn/share/base/shrcnksfDYwzmDCwvVGVfO3BBOb
里面也可以上传截图或文件，方便说明具体问题。
```

## 使用边界

- 不自动记录用户抱怨内容。
- 不要求用户安装飞书客户端、`feishu-cli` 或配置 API 密钥。
- 不承诺已经写入飞书；只有用户点开链接并提交问卷后，反馈才进入飞书表。
- 如果用户继续追问当前任务，优先处理任务，不反复弹链接。

---

## 第三方组件与许可
本 Skill 聚合或引用了若干第三方开源组件，它们各自遵循其原始许可证（非本文件 Apache-2.0），商业化再分发时须一并保留其许可与声明。完整清单见仓库根目录 `THIRD_PARTY_NOTICES.md`。
