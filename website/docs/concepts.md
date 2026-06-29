---
title: Core Concepts
---

# Core Concepts

Iact3 turns a project configuration into concrete stack tests. Understanding
the configuration hierarchy and stack lifecycle makes the CLI predictable.

## Project root

Most commands assume the current directory is the project root. By default,
Iact3 looks for:

- A project configuration named `.iact3.yml`
- A template file ending with `.template.json`, `.template.yaml`, or
  `.template.yml`
- Terraform files under the template directory when no ROS template file is
  found

Use `--project-path` to run from another directory:

```bash
iact3 test run --project-path ./demo
```

## Configuration hierarchy

Iact3 reads two configuration files:

- Global config: `~/.iact3.yml`
- Project config: `<project-root>/.iact3.yml`

Each file can contain three sections:

- `general`: machine- or account-level defaults
- `project`: defaults for the current template project
- `tests`: named test cases

Iact3 merges them into a list of concrete test configurations. For most keys,
the more specific section wins: `tests` overrides `project`, and `project`
overrides `general`. The `parameters` map is merged in the opposite direction so
account-specific defaults can stay outside the repository while test cases only
override the values they need.

## Tests and regions

Every entry under `tests` is a named test case. A test case can define its own
regions and parameters, or inherit them from the `project` section.

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

The first test runs in `cn-hangzhou` and `cn-beijing`; the second test runs in
`cn-shanghai`.

## Template sources

`template_config` supports several template sources:

| Field | Use case |
| --- | --- |
| `template_location` | Local ROS template file, directory containing a `*.template.yml/json` file, or a Terraform directory. |
| `template_body` | Inline template body. |
| `template_url` | `oss://`, `http://`, `https://`, or `file://` template URL. |
| `template_id` and `template_version` | Existing ROS template by ID and version. |
| `tf_version` | ROS Terraform Transform version. Defaults to `Aliyun::Terraform-v1.2`. |

When `template_location` points to a directory with `.tf` files and no
`*.template.yml/json` file is found, Iact3 wraps the Terraform files in a ROS
template with `Transform: Aliyun::Terraform-v1.2`.

## Pseudo parameters

Use `$[iact3-auto]` when a value can be resolved from the current region or
generated locally.

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

Iact3 supports ROS `GetTemplateParameterConstraints` and name-based fallbacks
for common fields:

- VPC ID
- VSwitch ID, optionally matched with a `ZoneId` parameter
- Security group ID
- Resource names prefixed with `iact3-`
- Passwords
- UUIDs

Use `$[iact3-current-region]` when a template parameter needs the region that is
currently being tested.

## Stack lifecycle

`iact3 test run` creates one stack per resolved test and region. By default it:

1. Resolves parameters
2. Runs `PreCreate` hooks
3. Creates stacks
4. Waits for stack completion
5. Runs `PostCreate` hooks
6. Deletes stacks
7. Runs delete hooks and writes reports

Use `--no-delete` to keep all stacks, or `--keep-failed` to keep only failed
stacks for debugging.

## Stack tags

Iact3 tags stacks so they can be listed and cleaned later:

- `CreatedBy=iact3`
- `iact3-id`
- `iact3-project-name`
- `iact3-test-name`

The cleanup commands only target stacks with these tags unless a more specific
`--stack-id` is supplied.
