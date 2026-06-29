---
title: 核心概念
---

# 核心概念

Iact3 会把一份项目配置转换为具体的资源栈测试。理解配置层级和栈生命周期后，
命令行为会更容易预期。

## 项目根目录

多数命令默认当前目录就是项目根目录。Iact3 默认查找：

- 名为 `.iact3.yml` 的项目配置
- 以 `.template.json`、`.template.yaml` 或 `.template.yml` 结尾的模板文件
- 如果找不到 ROS 模板文件，则查找模板目录下的 Terraform 文件

从其他目录运行时使用 `--project-path`：

```bash
iact3 test run --project-path ./demo
```

## 配置层级

Iact3 会读取两个配置文件：

- 全局配置：`~/.iact3.yml`
- 项目配置：`<project-root>/.iact3.yml`

每个文件都可以包含三层：

- `general`：机器或账号级默认值
- `project`：当前模板项目的默认值
- `tests`：命名测试用例

Iact3 会将它们合并为具体测试配置。多数键遵循“更具体优先”：`tests` 覆盖
`project`，`project` 覆盖 `general`。`parameters` 是例外，它会合并 map，
方便把账号相关默认值放在仓库外，而测试用例只覆盖需要变化的参数。

## 测试和地域

`tests` 下的每个键都是一个测试用例。测试用例可以定义自己的地域和参数，也可
以继承 `project` 中的配置。

```yaml
project:
  name: ecs-smoke
  regions:
    - cn-hangzhou
    - cn-beijing
tests:
  postpaid:
    parameters:
      InstanceChargeType: PostPaid
  prepaid:
    regions:
      - cn-shanghai
    parameters:
      InstanceChargeType: PrePaid
```

第一个测试会在 `cn-hangzhou` 和 `cn-beijing` 执行；第二个测试只在
`cn-shanghai` 执行。

## 模板来源

`template_config` 支持多种模板来源：

| 字段 | 用途 |
| --- | --- |
| `template_location` | 本地 ROS 模板文件、包含 `*.template.yml/json` 的目录，或 Terraform 目录。 |
| `template_body` | 内联模板内容。 |
| `template_url` | `oss://`、`http://`、`https://` 或 `file://` 模板 URL。 |
| `template_id` 和 `template_version` | 已存在的 ROS 模板 ID 和版本。 |
| `tf_version` | ROS Terraform Transform 版本，默认是 `Aliyun::Terraform-v1.2`。 |

当 `template_location` 指向目录，且目录中没有 `*.template.yml/json` 文件时，
Iact3 会收集 `.tf` 文件，并包装成带有 `Transform: Aliyun::Terraform-v1.2`
的 ROS 模板。

## 伪参数

当某个值可以从当前地域解析或本地生成时，可以使用 `$[iact3-auto]`。

```yaml
tests:
  default:
    parameters:
      VpcId: $[iact3-auto]
      VSwitchId: $[iact3-auto]
      SecurityGroupId: $[iact3-auto]
      InstanceName: $[iact3-auto]
      Password: $[iact3-auto]
```

Iact3 支持 ROS `GetTemplateParameterConstraints`，也支持常见字段名的回退解析：

- VPC ID
- VSwitch ID，可结合 `ZoneId` 参数匹配可用区
- 安全组 ID
- 以 `iact3-` 开头的资源名称
- 密码
- UUID

当模板参数需要当前测试地域时，可以使用 `$[iact3-current-region]`。

## 栈生命周期

`iact3 test run` 会为每个测试用例和地域创建一个栈。默认流程是：

1. 解析参数
2. 执行 `PreCreate` hooks
3. 创建资源栈
4. 等待栈完成
5. 执行 `PostCreate` hooks
6. 删除资源栈
7. 执行删除阶段 hooks 并写入报告

使用 `--no-delete` 保留所有栈，或使用 `--keep-failed` 仅保留失败栈用于排查。

## 栈标签

Iact3 会为创建的栈打标签，以便后续列出和清理：

- `CreatedBy=iact3`
- `iact3-id`
- `iact3-project-name`
- `iact3-test-name`

除非提供更具体的 `--stack-id`，清理命令只会处理带这些标签的栈。
