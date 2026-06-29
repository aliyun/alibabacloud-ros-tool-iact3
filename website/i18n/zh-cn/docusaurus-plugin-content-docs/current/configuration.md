---
title: 配置参考
---

# 配置参考

Iact3 配置使用 YAML。默认项目配置文件是 `.iact3.yml`，默认全局配置文件是
`~/.iact3.yml`。

## 完整结构

```yaml
general:
  auth:
    name: default
    location: ~/.aliyun/config.json
  regions:
    - cn-hangzhou
  parameters:
    KeyPairName: my-key-pair
  tags:
    environment: test
  oss_config:
    bucket_name: my-report-bucket
    bucket_region: cn-hangzhou
    object_prefix: iact3-runs
project:
  name: ecs-smoke
  regions:
    - cn-hangzhou
    - cn-beijing
  template_config:
    template_location: ecs.template.yml
  parameters:
    InstanceChargeType: PostPaid
  tags:
    project: ecs-smoke
tests:
  small:
    regions:
      - cn-hangzhou
    parameters:
      InstanceType: ecs.g6.large
      VpcId: $[iact3-auto]
      VSwitchId: $[iact3-auto]
      SecurityGroupId: $[iact3-auto]
```

## 合并规则

Iact3 会合并全局配置、项目配置和命令行参数。多数键遵循更具体的值优先。

`parameters` 会合并 map，因此可以把通用值放在 `~/.iact3.yml`，测试用例只覆
盖需要变化的值。

```yaml
general:
  parameters:
    KeyPairName: account-key
project:
  parameters:
    InstanceChargeType: PostPaid
tests:
  default:
    parameters:
      InstanceType: ecs.g6.large
```

最终测试会同时获得这三个参数。

## `general`

| 字段 | 含义 |
| --- | --- |
| `auth` | Aliyun CLI profile 名称和配置文件位置。 |
| `regions` | 默认地域列表。 |
| `parameters` | 默认模板参数。 |
| `tags` | 默认资源栈标签。 |
| `oss_config` | 用于上传报告和 hook 输出的 OSS Bucket。 |

## `project`

`project` 继承 `general` 的字段，并增加：

| 字段 | 含义 |
| --- | --- |
| `name` | 项目名称，用于栈标签和报告命名。 |
| `role_name` | 配置模型中存在的角色名称字段。除非当前 Iact3 版本已在你使用的 ROS API 路径中映射该字段，否则不要依赖它。 |
| `template_config` | 模板来源。 |
| `hooks` | 在创建或删除前后运行的命令。 |

## `tests`

`tests` 下的每个键都是测试名称。测试可以覆盖 `regions`、`parameters`、
`tags`、`template_config` 和 `hooks`。

```yaml
tests:
  postpaid:
    parameters:
      InstanceChargeType: PostPaid
  prepaid:
    parameters:
      InstanceChargeType: PrePaid
```

## Template config

| 字段 | 含义 |
| --- | --- |
| `template_location` | 本地模板文件或目录。 |
| `template_body` | 内联模板内容。 |
| `template_url` | `oss://`、`http://`、`https://` 或 `file://` 模板 URL。 |
| `template_id` | ROS 模板 ID。 |
| `template_version` | ROS 模板版本。 |
| `tf_version` | ROS Terraform Transform 版本，默认 `Aliyun::Terraform-v1.2`。 |

## OSS config

```yaml
project:
  oss_config:
    bucket_name: my-report-bucket
    bucket_region: cn-hangzhou
    object_prefix: nightly
    callback_params:
      callback_url: https://example.com/callback
      callback_host: example.com
      callback_body: '{"run": "${object}"}'
      callback_body_type: application/json
```

配置 `oss_config` 后，Iact3 可以将 hook 输出和报告上传到 OSS。

## Hooks

Hooks 可以在资源栈创建和删除前后运行。

```yaml
tests:
  default:
    hooks:
      post-create:
        execute_time: PostCreate
        execute_command:
          - sh
          - scripts/check-endpoint.sh
          - --stack
          - $[stack.name]
          - --region
          - $[stack.region]
          - --endpoint
          - $[outputs.Endpoint]
```

支持的 `execute_time`：

- `PreCreate`
- `PostCreate`
- `PreDelete`
- `PostDelete`

运行时可以替换资源栈名称、资源栈地域，以及 `$[outputs.OutputName]` 形式的栈输
出。

## 认证配置

```yaml
general:
  auth:
    name: default
    location: ~/.aliyun/config.json
```

省略 `auth` 时，Iact3 会回退到默认 Aliyun CLI 配置路径。
