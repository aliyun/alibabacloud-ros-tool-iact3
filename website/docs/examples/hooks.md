---
title: Hooks
---

# Hooks

Hooks let a test run external commands around stack creation and deletion. They
are useful for endpoint checks, Compute Nest validation, or collecting
additional diagnostics.

## Config

```yaml
project:
  name: hook-demo
  regions:
    - cn-hangzhou
tests:
  default:
    parameters:
      public_api: https://example.com
    hooks:
      post-create:
        execute_time: PostCreate
        execute_command:
          - sh
          - scripts/check-api.sh
          - --stack
          - $[stack.name]
          - --region
          - $[stack.region]
          - --target
          - public_api:$[outputs.public_api]
```

## Runtime values

Iact3 replaces these values before executing the command:

| Placeholder | Meaning |
| --- | --- |
| `$[stack.name]` | ROS stack name. |
| `$[stack.region]` | Stack region. |
| `$[outputs.Name]` | ROS stack output named `Name`. |

## Hook results

Iact3 captures stdout or stderr into a hook result file under the report
directory. If `oss_config` is configured, hook results can also be uploaded to
OSS.

## Failure handling

A hook that writes stderr is recorded as failed. Keep hook commands small and
deterministic so the deployment result and hook result are easy to interpret.
