#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公文 docx 导出 · 统一入口（govdoc-layout 自研引擎 v7.1）

自研实现（零第三方依赖，无第三方代码），GB/T 9704—2012 版式。
引擎模块：docgen_export/（mdparse 解析 / rules 版式 / render 渲染 / pagin 分页 / opc 打包 + engine 入口）。
版式设计参考 official-document-drafting（见 THIRD_PARTY_NOTICES.md）；v7.1 起为全自研重写，包内无第三方代码。
"""
import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from docgen_export import engine  # noqa: E402

if __name__ == "__main__":
    sys.exit(engine.main())
