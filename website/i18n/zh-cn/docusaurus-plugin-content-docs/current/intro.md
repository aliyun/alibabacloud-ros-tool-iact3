---
slug: /
sidebar_position: 1
title: 简介
---

# Iact3

Iact3 是用于阿里云
[资源编排服务 ROS](https://www.alibabacloud.com/product/ros) 模板和通过
ROS Transform 执行的 Terraform 模板的 Infrastructure as Code 测试工具。它
读取一份项目配置，将配置展开为多个测试用例和地域组合，创建资源栈，等待结果，
清理资源，并为每次运行生成报告。

在模板合并或发布前，可以用 Iact3 回答这些问题：

- 这个 ROS 或 Terraform 模板能否在目标地域部署成功？
- 不同参数组合是否都能创建可用的资源栈？
- 模板将创建哪些资源，需要哪些策略权限？
- 按当前参数创建资源的大致费用是多少？
- 资源栈输出和 hook 结果是否能形成可审计报告？

Iact3 的主要入口是 `iact3` 命令行。它可以在本地运行，也可以在 CI 或内置的
GitHub Action 中运行。

## 主要能力

| 能力 | 命令 | 作用 |
| --- | --- | --- |
| 部署测试 | `iact3 test run` | 为每个测试用例和地域创建 ROS 栈，等待终态，执行 hooks，并写入报告。 |
| 模板检查 | `iact3 validate`、`preview`、`cost`、`policy` | 调用 ROS API 校验模板、预览资源、询价、生成所需策略。 |
| 参数生成 | `iact3 test params` 或 `--generate-parameters` | 解析 `$[iact3-auto]` 伪参数，例如 VPC、VSwitch、安全组、名称、密码和 UUID。 |
| 基础资源 | `iact3 base create/list/delete` | 创建或删除用于测试账号的 VPC、安全组和每个可用区一个 VSwitch。 |
| 栈清理 | `iact3 list`、`delete`、`test clean` | 查找和删除带有 Iact3 标签的资源栈。 |
| CI 集成 | GitHub Action | 根据 workflow 输入校验模板或运行部署测试。 |

## 文档路径

先阅读[安装](./installation.md)，再按[快速开始](./quick-start.md)跑通第一
次测试。准备在模板仓库中使用时，再阅读[核心概念](./concepts.md)、
[配置参考](./configuration.md)和按任务组织的[使用](./usage.md)章节。
