---
title: ROS Sleep Template
---

# ROS Sleep Template

This example uses `ALIYUN::ROS::Sleep` to test the Iact3 lifecycle without
creating paid cloud resources.

## Template

`sleep.template.yml`:

```yaml
ROSTemplateFormatVersion: '2015-09-01'
Parameters:
  Key1:
    Type: String
    Default: null
  Key2:
    Type: String
    Default: null
Resources:
  sleep:
    Type: ALIYUN::ROS::Sleep
    Properties:
      CreateDuration: 2
      DeleteDuration: 2
Outputs:
  Key1:
    Value:
      Ref: Key1
  Key2:
    Value:
      Ref: Key2
```

## Config

`.iact3.yml`:

```yaml
project:
  name: sleep-smoke
  regions:
    - cn-hangzhou
  template_config:
    template_location: sleep.template.yml
tests:
  default:
    parameters:
      Key1: hello
      Key2: iact3
```

## Run

```bash
iact3 test run
```

This is a good first smoke test because it exercises stack creation, output
collection, deletion, and report generation.
