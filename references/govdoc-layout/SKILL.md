---
name: govdoc-layout
tags: [govdoc, 公文, 公文格式排版]
display_name: "公文·公文排版流程"
display_name_en: "govdoc-layout"
description_zh: "公文排版流程（gongwen-master 子技能，遵循 master 路由流程）"
visibility: "public"
version: "2.2.0"
description: "当用户要求进行公文排版、格式调整、写作流程设计，或将公文成稿导出为 GB/T 9704 国标 Word（.docx）时使用我（v7.0 含一键导出）。触发词：排版、格式、公文格式、GB/T 9704、版式、流程设计、写作流程、流程图、导出、出 Word、转 docx、生成正式文件。"
compatibility: "Designed for WorkBuddy/Claude/豆包等 agent 技能平台（standalone 包）；引擎脚本需 Python 3.10+ 与 requirements.txt 依赖（jieba/numpy/scikit-learn/rank-bm25）；数据层 datahub/ 随包（详见 requires）"
requires:
  master: "gongwen-master（路由流程与六步法）"
  data: "可选引用 qiushi-db 数据中枢（经 gongwen-master 路由）"
  deps: "python-docx（导出模式，requirements.txt）"
permissions:
  fs_write: "导出模式写用户指定输出路径的 .docx"
  network: "无"
  secrets: "无"
copyright: "Gongwen Master Contributors © Apache-2.0"
---

# 公文排版工具

## 触发场景

- 公文排版、GB/T 9704 格式、A4 预览、DOCX/Word 导出、WPS/Word 格式检查。

## 不适用

- 不用于内容写作（先用 govdoc-* 写作技能，再用本技能排版）。

## 文种类型

- 公文排版、格式转换、DOCX 导出

## 公共规范（统一持有）

本模块的输入清单、输出形态，以及 GB/T 9704 格式规范、行文规则、15 种法定公文、
常见错误与规避、质量检查清单，统一持有在 `../shared-templates.md`（见该文件「文种模块公共规范」各节）。

**执行本模块工作流前，须先读取上述文件对应小节**，默认工作流为：
1. 明确任务 → 2. 收集信息 → 3. 按**本模块自己的** `references/formulas.md` 套用结构 → 4. 按上述文件质量检查

## 导出模式（v7.0 新增：成稿 → GB/T 9704 国标 .docx）

当用户说「导出」「出 Word」「转 docx」「生成正式文件」时，执行本模式。

**推荐引擎（v7.0 复刻版，全能力）**：`scripts/generate_docx.py`

```bash
# 结构化成稿（推荐，支持全部语义 section）：
python scripts/generate_docx.py <成稿.md> -o <输出.docx> --doc-type 通知
# 不盖印章版（电子版，落款右空 2 字）：--unsealed
# 隐藏页码：--hide-page-number ｜ 预览字体/版式方案：--show-font-plan
```

**成稿结构约定**（## 二级标题 = 语义 section，**必须遵守，否则标题前段落会被丢弃**）：

```
# 主标题                          → 小标宋二号居中（>20 字自动对称回行）
## 版头（可选）                   → 红色版头字（如「XX市人民政府文件」）
## 发文字号（可选）               → 居中 + 红色分隔线
## 主送单位                       → 顶格，全角冒号
## 正文 / ## 一、xxx（编号 section）→ 正文仿宋三号 28 磅、首行缩进 2 字
## 落款                           → 单位+日期，右缩进智能对齐（印章版右空4字/电子版 --unsealed 右空2字）
## 附注                           → （联系人…）左空 2 字
## 版记                           → 主送/抄送/印发，四号+分隔线，自动沉底（空间不足整体移下页）
```

**能力清单**（**全自研实现**，v7.1 起；版式设计参考 official-document-drafting，见 `THIRD_PARTY_NOTICES.md`）：语义 section 渲染（版头红字/份号/密级/发文字号红线/落款署名-日期对齐/版记沉底）、长标题对称回行、「一X是」句首强调、页码一字线（首页隐藏）、图片附件嵌入（png/jpg）、**文种→字体/版式方案自动绑定**（38 个文种可绑定；三套版式：官方标准 / 内部易读 `internal-readable` / 讲话易读 `speech-readable`，用 `--doc-type <文种>` 选择；`python scripts/generate_docx.py --list-doc-types` 可列出；绑定表在 `docgen_export/profiles/doc-types/*/meta.toml`，缺省回退代码内置默认）、零第三方依赖（纯标准库，不依赖 python-docx）。

> **文种绑定行为（v7.3.1 起）**：未知文种**不再静默回落**——会输出错误并返回退出码 2，避免"以为套用了专用版式、实际用的默认版式"。Python 3.10 环境若无 `tomllib` 且未装 `tomli`，将跳过 TOML 而使用代码内置绑定表（功能不受影响）。

## 特定格式档（v8.1.8 新增：信函 / 命令 / 横排表格）

GB/T 9704-2012 第 10 章与第 8 章的特定格式**不能套用普通公文首页**。本版把「页面几何」从「字体/行距」里拆出来，
另成一条独立的轴：

```bash
# 信函（天头 30mm + 170mm 红双线 + 首页无页码）
python scripts/generate_docx.py 信函.md -o out.docx --doc-type 信函 --org 示例市人民政府
# 命令（令）（机关标志上边缘距版心 20mm；--org 须为机关全称+「命令」或「令」）
python scripts/generate_docx.py 命令.md -o out.docx --doc-type 命令 --org 示例市人民政府令
# 横排表格（横向 A4 + 225mm 表宽；Markdown 管道表直接识别）
python scripts/generate_docx.py 报告.md -o out.docx --format horizontal-table
python scripts/generate_docx.py 报告.md -o out.docx --format default   # 显式回通用档
```

| 档 | 与通用档的差异 | 实现 |
|---|---|---|
| `letter` 信函 | 天头 **1701 twips = 30mm**（非 37mm）；机关标志下 4mm 处 **170mm 上粗下细红双线**；页脚放**距下页边 20mm 处的上细下粗红双线**且**不放页码** | 红线用**表格**实现（行高 `[20,170,14]` / `[14,170,20]`，表宽 `9638`，`w:shd w:fill="FF0000"`）——Word/WPS 稳定，体检器也能直接判填充色 |
| `command` 命令（令） | 机关标志段前距 **1134 twips = 20mm**（不画通用 35mm 锚点）；`--org` 必填且须以「命令」或「令」结尾 | `redheader_xml(text, before)`——值**真写进段落的 `w:spacing`** |
| `horizontal-table` 横排表格 | 页面 **16838×11906 + `<w:orient w:val="landscape"/>`**；表宽 **12756 = 225mm** | 新增 Markdown **管道表**识别与 `table_xml()`；此前解析器完全不支持表格 |

- **优先级**：显式 `--format` > 文种自动绑定（信函→`letter`、命令→`command`）> 通用档。
- **与 `--layout-variant` 正交**：那条轴只改行距/段距（`internal-readable` / `speech-readable`）；
  信函的行距与通知一样，但页边距、红线、页码规则全不同——**两件事分开成两条轴**。

### 版记改声明式沉底（v8.1.8）

版记不再靠 `pagin.end_matter_position()` 的**影子渲染估算**（按已消耗高度猜剩余空间），
改用 `<w:tblpPr ... w:tblpYSpec="bottom"/>` **浮动表**：Word 自己把它贴到版心底缘，放不下就整表移到下一页。
理由是前者三处会静默错位——估算偏差、字体替换引起换行变化、渲染器忽略段前距——而 XML 里看不出任何异常。
配套纪律：**浮动表已声明式贴底，单元格段落不能再带 `before`**（否则表格高度整体超出页面）。

### 体检器也认格式档（v8.1.8）

```bash
python scripts/inspect_govdoc.py 文件.docx --doc-type 信函
python scripts/inspect_govdoc.py 文件.docx --format horizontal-table
```

- 天头、版心的「应有值」随档变化（信函 30mm、横排为横向 A4）。**不给 `--doc-type`/`--format` 时按通用档判，
  对特定格式件会误报 FAIL——这是已知且必然的行为，不是体检测错了。**
- 信函档：版心高度**改报 SKIP**（10.1 只规定上边缘 30mm 与下页边 20mm 处双线，未重申 5.2.1 的 156×225）；
  新增「信函红双线页脚」与「信函首页无页码」两项。横排档：版心改判「版心尺寸(横排)」+ 新增「横排表宽」。
- 新增「**版记沉底锚定**」检查（检出 `w:tblpYSpec="bottom"`）。

**国标逐要素体检器（读侧 · v7.5.1 新增）**：`scripts/inspect_govdoc.py` —— **上传一份已有的 .docx → 逐要素体检**，
输出「应有 vs 实际」的偏差报告。与 docgen_export 的关系是**读写互逆**：阈值全部从 `rules.py` 同一常量派生，不另抄一份。

```bash
python scripts/inspect_govdoc.py 文件.docx              # 全项体检
python scripts/inspect_govdoc.py 文件.docx --ignore 页码 --json
python scripts/inspect_govdoc.py 文件.docx -v           # 显示 SKIP 项原因
```

覆盖 21 项：页面 A4 / 天头 37mm / 订口 28mm / 版心 156×225mm / 每面 22 行 / 每行 28 字 / 正文行距 28.95 磅固定值 /
首行缩进 2 字 / 正文字体仿宋·三号 / 标题二号 / 一级标题黑体不加粗 / 二级楷体 / 发文字号六角括号〔〕/
成文日期右空四字 / 署名右空二字 / 页码（宋体四号·一字线）/ 版记 / 份号密级位置。

- **五态输出（v8.1.7 起）**：PASS / WARN / FAIL / SKIP / **MANUAL**。MANUAL 是「**机器不可判、须现场核验**」的要素（印章位置、红头毫米级位置、
  版记线粗细、横排表格单双页表头朝向、双面套正、油墨色值、装订裁切、用纸技术指标），共 8 项。
  MANUAL **不计入 PASS，也不影响退出码**——它的存在只是为了让「本批次没验什么」在报告里可见。
  默认不显示，加 `--manual` 查看。把不可判定项默默略去、或降级成 SKIP 混进「不适用」里，读者会把「没验」读成「验过且通过」。
- **分级**：硬性条款（页面·版心·行距·字号·字体·发文字号括号）超容差即 **FAIL**；惯例差异（首行缩进·日期右空·页码·版记）为 **WARN**；不适用为 SKIP。**有 FAIL 则退出码 1**，可接入流水线。
- **只读**：绝不修改用户文件（正式公文改坏了比不体检危险）。扫件/加密件显式报"不可解析"，不静默通过。
- **只判要素存在性与规格，不判内容对错**；单位模板差异用 `--ignore` 关闭。
- 已知边界：印章位置、红头、版记分隔线**粗细**只能判存在性，无法判毫米级位置（OOXML 中缺稳定锚点）；
  用 `wp:anchor` 文本框定位的页码会报 SKIP 而非猜测。
- 实测（2026-09-11 往返验证）：写侧生成的合规件 **PASS 18 / WARN 1 / FAIL 0**；两份注入已知偏差的件分别报出
  3 项与 1 项 FAIL，退出码 1。

**轻量引擎（备选）**：`scripts/export_govdoc.py`——平铺 Markdown 也可直接导出（无需 ## 结构），自带标点全角归一化（GB/T 15834）与溯源附注（`> 溯源:` 行/`--sources` JSON），适合快速导出；版式能力不及主引擎（无版记沉底/图片/文种绑定）。

## 验证装具（v8.1.7 新增 · 验的是「纸面」不是「代码」）

上面两个引擎回答「生成器输出了什么」；下面两件回答「输出的东西到底对不对」。前者不会报错，后者才会。

- **反向注入回归** `scripts/test_govdoc_injection.py`：只跑正常件得到的是「通过」——但一个从不报错的体检器也会「通过」。
  做法是把已知偏差**主动注入**到一份已通过体检的件里，断言体检器必须检出它、且退出码必须变。
  当前三类：行距 `w:line` 579 → 640 / 正文 `eastAsia` 仿宋_GB2312 → 宋体 / 页边距 `w:top` 2098 → 1701。
  注入用 `ElementTree` 逐属性改而**不用字符串替换**（字符串替换会连带改到 footer 里的同名属性，把「注入了一项」变成「注入了三项」）。
- **批量视觉审计** `tests/visual_audit.py`：**20 个场景**（v8.1.8 起，含信函/命令/横排表/留白套打/隐藏标题等分支）批量生成 + 逐一执行体检 + 写 `manifest.tsv`。
  退出码 **3 与 0 是有意分开的**：`0` = 生成、体检、渲染量测全跑通；`3` = 生成与体检通过但**渲染量测未跑**（缺 soffice / PDF 后端）。
  「没有工具所以没验」与「验了通过」是两回事，把 3 并在 0 里等于把「未验」报成「通过」。
- **PDF 字形坐标量测** `tests/measure_layout_coords.py`：为什么必须量 PDF 而不能只查 XML——段前距、行距、锚点写在 XML 里
  只能证明生成器输了什么，**不能证明渲染器画到了哪里**；段前距失效、字体替换引起换行变化、渲染器忽略属性，这三类都不会让 XML 报错。
  口径：先按垂直重叠（±1.5pt）**合并视觉行**（Poppler / MuPDF 会把中文短语按字体切成相邻 word），再匹配短语；
  结果随打印**分辨率上限 0.5mm**，不要用它宣称 0.1mm 级符合性。PDF 后端优先 PyMuPDF，回退 `pdftotext -bbox-layout`，两者都无则退出码 3。

> **本机环境限制（2026-09-28 实测）**：本机**无 LibreOffice（soffice）也无 Word** ⇒ `visual_audit.py` 的渲染量测阶段
> 必然报「未验」并以退出码 **3** 结束。**PDF 解析侧可用**（PyMuPDF 已装、`pdftotext` 在 `/mingw64/bin`）。
> 要跑通端到端量测，需另装 LibreOffice + Poppler（或改用 Word 另存 PDF）。**本机当前不具备 DOCX → PDF 能力**——
> 看到退出码 3 是如实报告，不是失败。

## 参考件（本机实现的外部校准层）

- `references/gbt9704-audit-matrix.md`——GB/T 9704-2012 **逐条执行矩阵**（条款 1~11），每条四列「条款｜规则｜本机实现（带行号）｜本机证据 / 缺口」，
  附三态声明（机器可判 / 结构可判视觉仍需人工 / 机器不可判）与本机-外部实现差异表。要回答「第 6.3 条装订要求覆盖了吗」时看这份。
- `references/formal-checklist.md`——正式公文逐项核验表，含**印制装订验收值**（版心误差≤1mm / 双面套正≤2mm / 成品±2mm /
  两钉外订眼距上下边缘 70mm±4mm / 平订钉锯距书脊 3—5mm）与 **§0 本批次验了什么**。
  §0 的判据：如果填不出「本批次未验」的具体项目，说明本次核验范围没被界定，等于没验。
  填表纪律：**未实测的项留空并注明未验，不得写「符合」**。

**字体说明**：两引擎均只写字体名。正式件需本机装有方正小标宋/仿宋_GB2312/黑体/楷体_GB2312（版权自备）；无版权字体环境用 `--font-preset noto-cjk`（仅主引擎支持）切换开源字体。红头、印章、单位专用模板不在自动化范围，正式发文仍需本单位 Word 模板最后核定。

## 公共规范（续）

上述 GB/T 9704 格式规范、行文规则、15 种法定公文、常见错误与规避、质量检查清单，
同样见 `../shared-templates.md` 的「文种模块公共规范」各节。


## 第三方组件与许可
本 Skill 聚合或引用了若干第三方开源组件，它们各自遵循其原始许可证（非本文件 Apache-2.0），商业化再分发时须一并保留其许可与声明。完整清单见仓库根目录 `THIRD_PARTY_NOTICES.md`。

## 涵盖文种（v6.6.0 族级合并）

- 已并入技能：`govdoc-writing-base`（公文写作通用底座；原名 govdoc-workflow 与顶层同名技能冲突，已改名）
  完整方法论见 `references/govdoc-workflow/SKILL.md`
- 说明：格式流程族：公文格式排版（GB/T 9704）与写作流程设计。
- 触发词已并入本技能 desc，路由后按具体文种取用对应模板。
