---
title: 使用
---

# 使用

`iact3` 命令行采用类似 `git` 的 `command subcommand --flag` 风格。使用
`iact3 --help` 可以查看命令族。

```text
iact3 [global options] <command> [command options] [subcommand] [subcommand options]
```

全局参数：

| 参数 | 含义 |
| --- | --- |
| `-v`, `--version` | 输出已安装版本。 |
| `-q`, `--quiet` | 减少日志输出。 |
| `-d`, `--debug` | 输出 debug 日志和 traceback。 |
| `--profile` | 选择 Aliyun CLI profile。 |
| `--log-prefix` | 为日志输出添加前缀。 |

## 按任务使用

- 使用 `iact3 test run` [运行部署测试](./usage/test-run.md)。
- 使用 `validate`、`preview`、`cost`、`policy` [检查模板](./usage/inspection.md)。
- 使用 `iact3 base` [创建基础资源](./usage/base-resources.md)。
- 使用 `list`、`delete` 和 `test clean` [列出和清理栈](./usage/stack-cleanup.md)。

## 命令族

| 命令 | 用途 |
| --- | --- |
| `test` | 部署测试、参数生成、清理和测试栈列表。 |
| `validate` | 校验 ROS 模板。 |
| `preview` | 预览模板将创建的资源。 |
| `cost` | 查询模板估算费用。 |
| `policy` | 生成模板所需策略。 |
| `base` | 创建、列出或删除可复用测试基础资源。 |
| `list` | 列出 Iact3 创建的栈。 |
| `delete` | 删除 Iact3 创建的栈。 |
