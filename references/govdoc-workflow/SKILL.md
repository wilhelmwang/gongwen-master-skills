---
name: govdoc-workflow
tags: [govdoc, 公文, 流程场景, 项目立项, 预算]
display_name: "公文·流程场景编排"
display_name_en: "govdoc-workflow"
description_zh: "跨部门公文流程编排（项目立项/预算申请等场景），按节点产出全套公文"
visibility: "public"
version: "1.3.0"
description: "当用户的请求涉及跨部门公文流程时使用我：如「A部门要申请预算做项目，第一步做什么、要写哪些公文」「项目要报发改委立项/数据局技评/财政局财评」「政府投资项目/信息化项目怎么走流程」「立项请示、可研报批、预算申请这套材料」。触发词：流程、立项、报批、预算申请、财评、技评、发改委、办理流程、全套材料、走程序。输出：按流程节点列清单 + 每个节点的公文文种与起草要点，并可调用对应 govdoc 技能逐件起草。"
compatibility: "Designed for WorkBuddy/Claude/豆包等 agent 技能平台（standalone 包）；数据引用依赖 qiushi-db（经 gongwen-master 路由）；版本 v7.1"
requires:
  master: "gongwen-master（路由与六步法）"
  data: "qiushi-db 数据中枢（地方 org_chart 机构名录用于节点单位实名引用）"
  subskills: "govdoc-request(请示/批复)、govdoc-report(报告)、govdoc-plan(方案)、govdoc-letter(函)、govdoc-minutes(纪要)、govdoc-notice(通知)"
permissions:
  fs_write: "无"
  network: "无"
  secrets: "无"
copyright: "Gongwen Master Contributors © Apache-2.0"
---

# 公文流程场景编排（govdoc-workflow v1.0.0）

> **定位**：把「一件事从起步到办成」拆成流程节点，告诉你**每个节点该找谁、写什么公文、要点是什么**，并可联动对应 govdoc 技能逐件起草。
> 这不是新文种技能，而是**面向场景的编排层**——文种起草能力复用现有 govdoc-* 技能。

## 一句话心智模型

```
场景（如：A 部门申请预算建项目）
  └─ 节点序列（每步：找谁 → 交什么 → 公文文种）
       └─ 每个节点 = 1~2 件公文（调用对应 govdoc-* 起草）
```

## 使用方式

1. 用户说场景（"我要申请预算做个系统"）→ 按 `references/scenarios/` 匹配最接近的场景卡；
2. 输出**流程节点清单**：每节点含【责任单位 → 前置条件 → 公文文种 → 起草要点】；
3. 用户确认后，逐节点调对应 govdoc-* 技能起草（如"第一步的请示"→ govdoc-request）；
4. 数据引用（项目单位全称、机构名）走 qiushi-db 地方 org_chart（保证"地方数据局"这类实名准确）。

## 核心场景（v1.2 收录 12 个，见 references/scenarios/）

| 场景卡 | 覆盖流程 | 文书数 |
|---|---|---|
| `project-approval.md` | 政府投资项目：预算申请 → 发改立项 → 技评 → 财评 → 批复 → 实施变更 | 9 件 |
| `it-project.md` | 政务信息化项目专项流程（数据局技评前置） | 7 件 |
| `procurement.md` | 政府采购：预算 → 需求计划 → 方式报批 → 组织采购 → 合同验收支付 | 8 件 |
| `personnel.md` | 干部选拔任用：动议 → 推荐 → 考察 → 讨论决定 → 报批公示 → 任职归档 | 10 件 |
| `suggestion-reply.md` | 人大建议/政协提案办理：交办 → 方案 → 协同 → 答复函 → 跟踪 | 7 件 |
| `normative-doc.md` | 规范性文件：立项 → 起草 → 征求意见 → 合法性审核 → 审议 → 公布备案 | 8 件 |
| `emergency-report.md` | 突发事件报送：电话首报 → 书面首报 → 续报 → 终报（分级时限表） | 3 件 |
| `supervision.md` | 督查督办：立项 → 交办 → 承办 → 催办督查 → 反馈销号（含银川 135 简化版） | 6 件 |
| `petition.md` | 信访事项：受理登记 → 分类甄别 → 调查核实 → 答复意见 → 复查复核（60 日铁律） | 5 件 |
| `info-disclosure.md` | 信息公开申请答复：受理 → 补正征询 → 答复 → 救济告知（20 个工作日铁律） | 3 件 |
| `reconsideration.md` | 行政复议应诉：复议答复 4 节点（10 个工作日举证）+ 应诉 3 节点 | 3 件 |
| `tendering.md` | 工程招投标：核准 → 公告文件 → 开评标 → 公示通知书 → 合同备案 → 履约投诉 | 8 件 |

## 部门定制场景（v1.3 新增：职责 → 场景生成）

基于 org_duties（机构职责表）可为**每个部门**生成定制场景卡：
- 生成规则：`references/duty-to-scenario.md`（职权动词→角色判断→四类场景映射）
- 已生成：`references/scenarios/departments/地方数据局-scenarios.md`（样例）
- 批量补录职责：`datahub/scripts/hs/hs_duties_ingest.py --scan / --url`（编办官网职责专栏 + 部门预算公开页双轨）
- 用户点名部门（如「给财政局生成场景」）→ 按 d2s 规则生成 → 存 departments/ → 门禁回归

## 法规依据层

`references/regulations.md` 汇总各流程节点的法规依据（政府投资条例 712 号令、各地政府投资项目管理办法、政务信息化项目管理办法），供起草时引用文件名与核心条款。

## 边界

- 各地规定差异较大（金额阈值/审批主体/简化条件），本技能给出**通用骨架 + 可替换参数**（金额档位、节点单位名），用户应按本地最新文件校正；
- 地方本地机构实名通过 org_chart 保证（如"地方数据局"），其他城市需用户自填；
- 不替代审批部门的实质性审查，只解决「该写什么公文、怎么写」。
