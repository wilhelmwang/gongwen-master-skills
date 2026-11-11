# 各环境技能根目录探测表（install-gongwen 引用）

> 目标根 = 存放 `gongwen-skills/` 的父目录。按优先级探测，取第一个存在的。

| 优先级 | 环境 | 路径 | 说明 |
|---|---|---|---|
| 1 | 用户指定 | 用户说"装到 X" | 按用户意图映射到下表路径 |
| 2 | 环境变量 | `$GONGWEN_SKILLS_DIR` | 显式指定时优先 |
| 3 | WorkBuddy | `~/.workbuddy/skills/` | Windows: `<用户目录>\<用户>\.workbuddy\skills\` |
| 4 | 豆包（Windows 桌面版）| `~/Doubao/skills/` | 注意首字母大写 D，常见于桌面版 |
| 5 | 豆包（CLI）| `~/.doubao/skills/` | 小写点目录 |
| 6 | Claude | `~/.claude/skills/` | Claude Code 技能 |
| 7 | 通用 | `~/.skills/` | 兜底 |

## Windows 实际路径速查（本机实测 2026-09-01）

| 环境 | 实测路径 |
|---|---|
| WorkBuddy | `<用户目录>\.workbuddy\skills\` |
| 豆包桌面版 | `<用户目录>\Doubao\skills\`（首字母大写）|
| 豆包 CLI | `<用户目录>\.doubao\skills\`（可能不存在）|

## 探测方法（agent 执行）

1. 对每个候选路径，检查是否存在（目录）
2. 取**第一个存在**的作为目标根；全部不存在则默认 WorkBuddy
3. 探测结果**必须向用户回显确认**后再安装

## 已安装判断

目标根下 `gongwen-skills/` 存在 = 已安装过：
- 有 `VERSION` 文件 → 读版本号，判断新旧
- 无 `VERSION`（v5 时代）→ 视为旧版，升级安装（先备份）
