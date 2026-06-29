---
title: Configuration Reference
---

# Configuration Reference

Iact3 configuration is YAML. The default project file is `.iact3.yml`; the
default global file is `~/.iact3.yml`.

## Full shape

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

## Merge rules

Iact3 merges global config, project config, and CLI arguments. For most keys,
the more specific value wins.

For `parameters`, Iact3 merges maps so generic values can live in
`~/.iact3.yml`, while test cases override only the values they need.

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

The effective test receives all three parameters.

## `general`

| Field | Meaning |
| --- | --- |
| `auth` | Aliyun CLI profile name and config file location. |
| `regions` | Default region list. |
| `parameters` | Default template parameters. |
| `tags` | Default stack tags. |
| `oss_config` | OSS bucket used for report and hook output upload. |

## `project`

`project` inherits the same fields as `general` and adds:

| Field | Meaning |
| --- | --- |
| `name` | Project name used in stack tags and report names. |
| `role_name` | Role name field in the configuration model. Do not rely on it unless your current Iact3 version maps it to the ROS API path you use. |
| `template_config` | Template source. |
| `hooks` | Commands run before or after create/delete phases. |

## `tests`

Each key under `tests` is a test name. A test can override `regions`,
`parameters`, `tags`, `template_config`, and `hooks`.

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

| Field | Meaning |
| --- | --- |
| `template_location` | Local template file or directory. |
| `template_body` | Inline template body. |
| `template_url` | `oss://`, `http://`, `https://`, or `file://` template URL. |
| `template_id` | ROS template ID. |
| `template_version` | ROS template version. |
| `tf_version` | ROS Terraform Transform version. Defaults to `Aliyun::Terraform-v1.2`. |

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

When `oss_config` is present, Iact3 can upload hook output and reports to OSS.

## Hooks

Hooks can run before and after stack creation and deletion.

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

Supported `execute_time` values:

- `PreCreate`
- `PostCreate`
- `PreDelete`
- `PostDelete`

Supported runtime substitutions include stack name, stack region, and stack
outputs in the form `$[outputs.OutputName]`.

## Authentication config

```yaml
general:
  auth:
    name: default
    location: ~/.aliyun/config.json
```

If `auth` is omitted, Iact3 falls back to the default Aliyun CLI config path.
