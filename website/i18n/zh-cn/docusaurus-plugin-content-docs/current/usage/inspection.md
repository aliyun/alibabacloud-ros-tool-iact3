---
title: 模板检查
---

# 模板检查

检查类命令会调用 ROS API，但不会运行完整的创建和删除测试生命周期。

## 校验模板

```bash
iact3 validate -t template.yml
```

省略 `-t` 时，Iact3 会从 `.iact3.yml` 读取模板，或在项目根目录查找
`*.template.yml/json` 文件。

在运行部署测试前，可以先用该命令快速校验语法和 ROS schema。

## 预览资源

```bash
iact3 preview -t template.yml -r cn-hangzhou
```

`preview` 会展示 ROS 预计创建的资源。它适合在创建栈前检查资源类型、依赖关系
和参数展开结果。

## 查询估算费用

```bash
iact3 cost -t template.yml -r cn-hangzhou
```

`cost` 会向 ROS 查询模板估价。结果取决于 ROS 估价 API 对具体资源和地域的支
持情况。

## 生成所需策略

```bash
iact3 policy -t template.yml
```

`policy` 会生成模板所需策略信息，适合在准备最小权限测试角色时使用。

## 参数

| 命令 | 参数 |
| --- | --- |
| `validate` | `-t/--template`、`-c/--config-file`、`-r/--regions` |
| `preview` | `-t/--template`、`-c/--config-file`、`-r/--regions` |
| `cost` | `-t/--template`、`-c/--config-file`、`-r/--regions` |
| `policy` | `-t/--template`、`-c/--config-file`、`-r/--regions` |
