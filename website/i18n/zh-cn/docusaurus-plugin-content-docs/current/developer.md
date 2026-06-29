---
title: 开发者说明
---

# 开发者说明

本页面面向维护 Iact3 本身的开发者。

## 运行测试

项目使用 Python `unittest`。

```bash
python -m unittest
```

运行指定测试模块：

```bash
python -m unittest tests.test_fast_help_consistency
```

## 构建二进制文件

```bash
python -m pip install --upgrade pip
pip install ".[binary]"
python build.py
```

构建产物会写入 `dist/`。

## 文档站

文档站位于 `website/`。

```bash
cd website
npm ci
npm test
npm run typecheck
npm run build
```

文档站使用和 `alibabacloud-ros-tool-transformer` 相同的技术栈：Docusaurus
3.10.1、React 19、TypeScript、npm 和 `zh-cn` locale。

## Release binary workflow

`Build Binary` workflow 在发布 release 或手动触发时运行。它会构建 Linux、
macOS 和 Windows 二进制文件，smoke test `--version`，上传 artifacts，并把
压缩包附加到 release。
