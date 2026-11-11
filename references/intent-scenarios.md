# 公文意图场景映射表（v8.0.0）

> 用途：把用户的「口语化/场景化表达」映射到模块与流程，支撑 gongwen-master 的意图解析与流程引导。
> 原则：文科生怎么说话，就怎么映射；不要求用户说模块名。

## 一、场景 → 文种 + 配套模块链

| 用户常见说法（场景） | 文种模块 | 配套模块链（取数→写作→润色→质检→排版） |
|---|---|---|
| 给领导汇报 / 向上级汇报 / 报个情况 | govdoc-report | 数据(qiushi-db·地方底座) → report → polish → qc |
| 年底总结 / 半年总结 / 写个总结 | govdoc-summary | 数据(qiushi-db·地方底座) → summary → polish → qc |
| 开会要讲话 / 动员一下 / 表个态 | govdoc-speech | 政策(qiushi-db) → speech → polish → qc |
| 开会记录 / 会议纪要 | govdoc-minutes | minutes → qc |
| 通知大家 / 发个通知 / 放假安排 | govdoc-notice | notice → qc |
| 调研一下 / 写调研报告 | govdoc-research | 数据(qiushi-db·地方底座) + 政策(qiushi-db) → research → qc |
| 解读这个文件 / 政策解读 | govdoc-styles（文风四·乔木笔） | 政策(qiushi-db) → 解读 → qc |
| 写心得体会 / 学习感悟 | govdoc-reflection | 政策(qiushi-db) → reflection → polish |
| 表扬/批评/通报 | govdoc-circular | circular → qc |
| 请示/申请 | govdoc-request | request → qc |
| 批复/审批 | govdoc-approval | approval → qc |
| 发新闻/简报/信息 | govdoc-news / govdoc-brief | news/brief → qc |
| 制度/办法/规定 | govdoc-regulation | regulation → qc |
| 理论文章/政论 | govdoc-theory | 政策(qiushi-db) → theory → polish |
| 用XX风格写 / 像XX那样写 | shuji/{模块} 或 govdoc-styles/{文风N} | 风格模块 → polish → qc |
| 引用求是 / 找权威表述 | qiushi-db | 检索 → 引用 → 写作 |
| 引用地方数据 / 本地数据 | qiushi-db（地方底座） | 取数 → 写作 → 标注来源 |
| 润色 / 改改 / 改得正式点 | govdoc-polish | polish → qc |
| 质检 / 检查 / 校对 | govdoc-qc | qc（五段式报告） |
| 排版 / 导出Word / 公文格式 | govdoc-layout | layout（GB/T 9704） |
| 新手 / 不会写 / 不知道怎么写 | govdoc-onboarding | 5 问诊断 → 模板推荐 → 交接 |

## 二、口语化 → 文种速查（文科生常用词）

| 用户说 | 实际要 | 路由 |
|---|---|---|
| 汇报 / 述职 / 报材料 | 工作报告/述职报告 | govdoc-report |
| 总结 / 回顾 / 盘点 | 工作总结 | govdoc-summary |
| 讲话 / 发言 / 致辞 / 动员 | 领导讲话 | govdoc-speech |
| 纪要 / 记录 / 备忘录 | 会议纪要 | govdoc-minutes |
| 通知 / 告知 / 安排 | 通知 | govdoc-notice |
| 调研 / 考察 / 摸情况 | 调研报告 | govdoc-research |
| 解读 / 宣讲 / 吃透文件 | 政策解读 | govdoc-styles（文风四） |
| 心得 / 感悟 / 体会 | 心得体会 | govdoc-reflection |
| 表扬 / 批评 / 通报 | 通报 | govdoc-circular |
| 请示 / 申请 / 报批 | 请示 | govdoc-request |
| 批复 / 审批 / 答复 | 批复 | govdoc-approval |
| 制度 / 办法 / 规定 / 章程 | 规章制度 | govdoc-regulation |
| 新闻 / 消息 / 通稿 | 消息 | govdoc-news |
| 简报 / 信息 / 动态 | 信息简报 | govdoc-brief |
| 方案 / 计划 / 怎么干 | 工作方案 | govdoc-plan |
| 意见 / 想法 / 给建议 | 意见（先理需求→推荐文种） | govdoc-workflow / onboarding |
| 弄个材料 / 写点东西（不明确） | 不确定文种 | govdoc-onboarding |

## 三、多意图组合规则（重要）

- 「写工作汇报，引用地方 GDP」→ **数据优先**：先 qiushi-db（地方底座）取数 → 再 govdoc-report 写作（规则 C2）
- 「用账本体写财政分析」→ 风格优先：shuji/liyi-weili → 写作（规则 B）
- 「解读这个文件，引用求是」→ 引用优先：qiushi-db 检索 → govdoc-styles（文风四）解读（规则 C）
- 「写讲话 + 要数据 + 最后质检」→ 全链：qiushi-db（地方底座） → speech → qc（流程引导串联）

## 四、流程引导话术模板（master 写作完成后使用）

完成一次写作后，按需追加（不强推，用户拒绝即止）：

```
需要的话我可以继续：
1. 补数据/案例支撑（数据底座）
2. 润色语言（更正式/更生动）
3. 质检（政治/规范/逻辑/鲜活/去AI味 五维）
4. 排版成公文格式（GB/T 9704）
直接说序号或需求即可。
```
