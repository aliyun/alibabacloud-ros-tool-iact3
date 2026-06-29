---
title: 部署测试
---

# 部署测试

`iact3 test run` 是核心命令。它会为每个配置后的测试用例和地域创建真实 ROS
栈，等待结果，执行 hooks，默认删除栈，并写入报告。

## 基本运行

```bash
iact3 test run
```

Iact3 会读取当前目录下的 `.iact3.yml`。如果配置中未指定 `template_config`，
它会在当前目录查找模板。

## 从其他目录运行

```bash
iact3 test run --project-path ./demo
```

`--project-path` 会改变配置文件、模板文件和输出目录的项目根目录。

## 指定配置和模板

```bash
iact3 test run \
  -t templates/ecs.template.yml \
  -c iact3-config/ecs.iact3.yml
```

## 限定地域或测试用例

```bash
iact3 test run -r cn-hangzhou,cn-beijing --test-names default,small
```

`-r` 会覆盖配置中的地域。`--test-names` 只运行 `tests` 中指定名称的用例。

## 控制删除行为

默认情况下，Iact3 会在测试结束后删除资源栈。

```bash
iact3 test run --no-delete
```

保留全部栈。

```bash
iact3 test run --keep-failed
```

删除成功栈，仅保留失败栈用于排查。

```bash
iact3 test run --dont-wait-for-delete
```

调用删除栈后立即退出，不等待删除完成。

## 只生成参数，不创建栈

```bash
iact3 test run --generate-parameters
```

该命令会解析伪参数并打印最终参数集合，不创建资源栈。

更短的命令是：

```bash
iact3 test params -c .iact3.yml -r cn-hangzhou
```

## 报告格式

```bash
iact3 test run --log-format json,xml
```

HTML 报告和 JSON 汇总总会生成。`--log-format` 会额外生成指定格式的每栈日志。

## 常用参数

| 参数 | 含义 |
| --- | --- |
| `-t`, `--template` | 模板文件或模板目录路径。 |
| `-c`, `--config-file` | Iact3 配置文件路径。 |
| `-o`, `--output-directory` | 输出目录，默认 `iact3_outputs`。 |
| `-r`, `--regions` | 逗号分隔的地域。 |
| `--test-names` | 逗号分隔的测试用例名称。 |
| `--project-path` | 项目根目录。 |
| `--no-delete` | 保留所有栈。 |
| `--keep-failed` | 保留失败栈。 |
| `--dont-wait-for-delete` | 不等待栈删除完成。 |
| `-g`, `--generate-parameters` | 打印解析后的参数，不运行测试。 |
| `-l`, `--log-format` | 额外日志格式，逗号分隔：`json`、`xml`。 |
