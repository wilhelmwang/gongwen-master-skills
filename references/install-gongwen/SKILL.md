---
name: install-gongwen
description: |
  公文大师安装器（skill 模块）。当用户要求「安装公文大师」「部署 gongwen」「装到豆包/WorkBuddy/Claude」「重装/升级技能包」「install gongwen」时使用。
  本 skill 让**任意 agent（豆包/WorkBuddy/Claude/其他）加载后自己完成安装**——agent 按本文档用自身文件操作能力执行，用户零命令行操作：
  探测目标技能根目录 → 定位包源（zip 或目录）→ 复制 23 个技能目录 → 复制数据层 datahub/（sqlite/derived/scripts）→ 复制工具脚本 → 校验 25 项 → 输出安装报告。
  目标已有旧版时先备份再替换（保留用户数据）。支持 --target 显式指定（脚本捷径）或纯工具执行。
version: "1.0.0"
copyright: "Gongwen Master Contributors © Apache-2.0"
---

# 公文大师安装器（install-gongwen v1.0.0 · skill 模块）

> **⚠️ v8.0.0 退役注记（2026-09-21）**：单技能化后安装已简化为**复制 `gongwen-master/` 一个目录**至目标技能根（数据层 datahub/ 已内置包内）。
> 本文保留作多平台部署参考：目标根探测表、旧版备份策略、校验清单仍然有效；
> 「复制 23 个技能目录 / 复制根工具文件」等步骤仅适用于 v7 存量多技能布局，v8 部署时跳过。
> 依赖检查（jieba/numpy/scikit-learn/rank-bm25）与 `verify_install.py` 冒烟仍建议执行。

> **一句话**：任何 agent 加载本 skill 后，用自己手中的文件工具完成公文大师的全部安装——**不要求用户跑任何命令**。

## 这是什么

把「安装公文大师」做成**技能化交付物（唯一安装通道）**：
- 任意 agent（豆包 / WorkBuddy / Claude / 其他）加载本 skill 即会安装
- 安装动作由 agent 用工具执行（复制/解压/校验），用户只负责说一句"帮我装公文大师"
- 自动识别目标环境（WorkBuddy / 豆包 / Claude / 通用），自动处理中文目录名与旧版升级

## agent 安装流程（按序执行，勿跳步）

### 第一步：确认包源

包源 = 含 `VERSION` 文件 + `gongwen-master/` 目录 + `datahub/` 数据层的完整包。按优先级确认：

| 来源 | 处理 |
|---|---|
| 用户给的 zip 路径 | 用工具解压到临时目录（**中文目录名必须用 Python zipfile 或 7-Zip，禁止 Git Bash unzip**——会乱码）|
| 用户给的目录路径 | 直接用 |
| 当前会话/目录 | 检查是否含 VERSION + gongwen-master |
| 找不到 | **问用户包在哪里**，不要猜 |

### 第二步：探测目标技能根目录

目标根 = 存放 `gongwen-skills/` 的父目录。按此顺序探测（取第一个存在的）：

```
1. 用户指定（"装到豆包/WorkBuddy/Claude"）→ 查下表对应路径
2. 环境变量 GONGWEN_SKILLS_DIR
3. WorkBuddy : ~/.workbuddy/skills/
4. 豆包 Windows : ~/Doubao/skills/     （豆包桌面版常见，注意首字母大写 D）
5. 豆包 CLI   : ~/.doubao/skills/
6. Claude    : ~/.claude/skills/
7. 通用      : ~/.skills/
```

探测结果向用户确认一次（"将安装到 X，对吗？"），再继续。

### 第三步：执行安装（agent 用工具完成）

目标目录 = `{根}/gongwen-skills/`。执行：

1. **旧版处理**：目标已存在 → 先把整个目标目录复制到 `{根}/backups/pre_install_版本_时间戳/`（备份），告知用户备份位置。**不要删除旧目录内容**——用"移入 .old_replace"或直接覆盖策略，避免误删用户数据（style-models 等单位文风模型必须保留）。
2. **复制 23 个技能目录**（清单见 `references/skills-list.md`）：把包源的每个技能目录复制到目标。目标同名目录存在时：先移动到 `{目标}/.old_replace/`（保留快照，不删除），再复制新目录。
2.5 **冒烟自检**：`python install.py --smoke`——安装后自动跑地方检索 + 求是检索 + 五项资产在位，输出"安装可用"结论。

3. **复制数据层**：`datahub/`（sqlite 3 库 / derived 派生资产 / scripts 引擎 / schema）整体复制到 `{目标}/datahub/`（backups 除外）。
4. **复制根工具文件**：VERSION、README.md、requirements.txt、verify_install.py、upgrade_check.py。
5. **清理旧版根残留**：目标根下的 `scripts/`、`config.json`、`dictionaries` 等新包不存在的旧版文件，移动到 `.old_replace/`（不删除）。
6. **依赖**：检查目标环境是否已装 jieba/numpy/scikit-learn/rank-bm25；缺则用包管理工具安装（`pip install -r requirements.txt`）。

### 第四步：校验（25 项）

运行 `{目标}/verify_install.py`（agent 用工具执行），逐项确认：

```
✅ 技能目录 23/23  ✅ shuji 子模块 9/9  ✅ datahub 数据层  ✅ 金句库 31,614 条
✅ qs_articles.db 5,761 篇  ✅ local 库  ✅ 依赖 4 项  ✅ 检索抽测命中
✅ 无硬编码路径  ✅ 无嵌套目录  ✅ 版本一致性(VERSION=master)
```

**向用户报告**（必须包含三要素）：
1. 安装位置（完整路径）
2. 安装版本（VERSION 内容）
3. 校验结果（25/25 全绿 = 可用；有 ❌ = 列出失败项 + 修复建议）
4. 若升级过：备份位置

## 常见场景速查

| 用户说 | agent 做什么 |
|---|---|
| "帮我装到豆包" | 目标 ~/Doubao/skills/，若已有 gongwen-skills 先备份 |
| "装到 WorkBuddy" | 目标 ~/.workbuddy/skills/ |
| "装到 Claude" | 目标 ~/.claude/skills/ |
| "升级到新版" | 目标已存在 → 备份 → 替换（升级流程同上）|
| "只有 zip" | 先用 Python zipfile 解压再装 |

## 脚本捷径（可选，agent 自行决定）

`scripts/install.py` 实现了上述全流程（探测/备份/干净替换/校验/报告），agent 可运行它一键完成，也可纯用文件工具逐步执行。**无论哪种方式，都不要求用户跑命令**——由 agent 代劳。

## 注意事项

- **中文目录名**：含 `datahub/` 与语料目录，解压禁用 Git Bash unzip（乱码），用 Python zipfile/7-Zip
- **素材库完整性**：安装后 qs_articles.db 应约 152MB、qs_index.pkl 约 197MB；过小说明复制不完整，需重试
- **不丢用户数据**：style-models（单位文风模型）等单位自定义内容在升级时必须保留；旧目录先备份/移入 .old_replace 再替换
- **不删除原则**：安装过程不删除任何东西——旧版文件移到备份或 .old_replace，用户数据永远保留

## 参考文件

- `references/skills-list.md` —— 23 技能目录完整清单
- `references/targets.md` —— 各环境技能根目录探测表
- `scripts/install.py` —— 一键安装脚本（可选捷径）
