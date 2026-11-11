# 24 技能目录清单（install-gongwen 引用）

> 安装/升级/校验共用的权威清单（与 install.py SKILLS 常量、verify_install.py tops、registry.json 一致）。
> v6.6.0 三轮合并 41→23 后于 v6.9.0 收敛本清单。

## 路由中枢（1）
gongwen-master

## 公文文种（18）
govdoc-circular / govdoc-duty / govdoc-experience / govdoc-layout / govdoc-letter
govdoc-minutes / govdoc-news / govdoc-notice / govdoc-plan / govdoc-polish
govdoc-reflection / govdoc-regulation / govdoc-report / govdoc-request / govdoc-research
govdoc-speech / govdoc-summary / govdoc-theory

## 风格族（3）
govdoc-styles（文风六风格 + 会诊入口，方法论 → references/）
shuji（书籍行文九风格入口，方法论 → references/ 九子模块）
article-review（文章审查：深度分析 + 事实核查两模式）

## 流程场景（1）
govdoc-workflow（跨部门公文流程编排：立项/预算/技评/财评场景卡）

## 数据中枢（1）
qiushi-db（求是 + 地方，实数据在 datahub/）

## 安装器（独立模块，不计入 23 技能）
install-gongwen

## 根工具文件（复制到目标根）
VERSION / README.md / requirements.txt / THIRD_PARTY_NOTICES.md / registry.json
verify_install.py / upgrade_check.py / rules_regression.py / validate_skills.py
gen_registry.py / bootstrap_data.py / gongwen_tool.py

## 数据层（复制到目标 datahub/）
datahub/（sqlite / derived / scripts / schema；backups 与 __pycache__ 除外）
