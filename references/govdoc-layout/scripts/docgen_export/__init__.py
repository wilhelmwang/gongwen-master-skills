# -*- coding: utf-8 -*-
"""公文 docx 导出引擎（govdoc-layout 自研实现 v7.1）

本包为全新独立实现，不包含第三方代码（原 MIT 参考实现已移出为 docgen_export_mit_ref/）。
设计目标：以 GB/T 9704—2012 为规范依据，从「结构化公文 Markdown」直接产出
符合党政机关公文版式的 .docx（OPC/WordprocessingML），零第三方依赖。

外部接口（与既有用法保持兼容）：
  generate_docx.py <成稿.md> [-o 输出.docx] [--doc-type 文种] [--unsealed]
      [--hide-page-number] [--show-font-plan] [--list-doc-types]
  成稿结构约定：# 标题 / ## 语义 section（版头/份号/密级/发文字号/主送单位/
      正文/编号标题/落款/附注/版记/附件）

分层（每层只依赖下层）：
  mdparse —— Markdown 解析、标题对称回行、段落类型启发
  rules   —— GB/T 9704 常量与文种-版式方案绑定（TOML）
  render  —— 语义 section → 段落规格列表（纯数据，不碰 XML）
  pagin   —— 段落行数/高度估算、版记沉底判定
  opc     —— WordprocessingML 文本化 + zip 打包，原子落盘
"""
__all__ = ["mdparse", "rules", "render", "pagin", "opc"]
