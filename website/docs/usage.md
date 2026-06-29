---
title: Usage
---

# Usage

The `iact3` CLI follows a `command subcommand --flag` style similar to `git`.
Run `iact3 --help` to list command families.

```text
iact3 [global options] <command> [command options] [subcommand] [subcommand options]
```

Global options:

| Option | Meaning |
| --- | --- |
| `-v`, `--version` | Print the installed version. |
| `-q`, `--quiet` | Reduce log output. |
| `-d`, `--debug` | Print debug output and tracebacks. |
| `--profile` | Select the Aliyun CLI profile. |
| `--log-prefix` | Prefix log output. |

## Task-oriented commands

- [Run deployment tests](./usage/test-run.md) with `iact3 test run`.
- [Inspect templates](./usage/inspection.md) with `validate`, `preview`, `cost`,
  and `policy`.
- [Create base resources](./usage/base-resources.md) with `iact3 base`.
- [List and clean stacks](./usage/stack-cleanup.md) with `list`, `delete`, and
  `test clean`.

## Command families

| Command | Purpose |
| --- | --- |
| `test` | Deployment tests, parameter generation, cleanup, and test stack listing. |
| `validate` | Validate a ROS template. |
| `preview` | Preview resources that a template would create. |
| `cost` | Query estimated template cost. |
| `policy` | Generate the policy required by a template. |
| `base` | Create, list, or delete reusable test base resources. |
| `list` | List stacks created by Iact3. |
| `delete` | Delete stacks created by Iact3. |
