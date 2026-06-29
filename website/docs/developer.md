---
title: Developer Notes
---

# Developer Notes

This page is for maintainers changing Iact3 itself.

## Run tests

The project uses Python `unittest`.

```bash
python -m unittest
```

Run a focused test module:

```bash
python -m unittest tests.test_fast_help_consistency
```

## Build a binary

```bash
python -m pip install --upgrade pip
pip install ".[binary]"
python build.py
```

The build writes the binary and archive under `dist/`.

## Documentation site

The documentation site lives under `website/`.

```bash
cd website
npm ci
npm test
npm run typecheck
npm run build
```

The site uses Docusaurus with the same stack as
`alibabacloud-ros-tool-transformer`: Docusaurus 3.10.1, React 19, TypeScript,
npm, and the `zh-cn` locale.

## Release binary workflow

The `Build Binary` workflow runs on published releases and manual dispatch. It
builds Linux, macOS, and Windows binaries, smoke-tests `--version`, uploads
artifacts, and attaches archives to the release.
