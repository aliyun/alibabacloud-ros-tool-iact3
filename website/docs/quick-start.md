---
title: Quick Start
---

# Quick Start

This guide runs a small ROS template through Iact3 and shows where the report is
written. The command creates real ROS stacks, so use a test account and regions
where the resources are allowed.

## 1. Create a project directory

```bash
mkdir iact3-demo
cd iact3-demo
```

## 2. Add a ROS template

Create `sleep.template.yml`:

```yaml
ROSTemplateFormatVersion: '2015-09-01'
Parameters:
  Message:
    Type: String
    Default: hello-iact3
Resources:
  Wait:
    Type: ALIYUN::ROS::Sleep
    Properties:
      CreateDuration: 2
      DeleteDuration: 2
Outputs:
  Message:
    Value:
      Ref: Message
```

## 3. Add an Iact3 configuration

Create `.iact3.yml`:

```yaml
project:
  name: iact3-demo
  regions:
    - cn-hangzhou
  template_config:
    template_location: sleep.template.yml
tests:
  default:
    parameters:
      Message: hello-from-iact3
```

## 4. Run a deployment test

```bash
iact3 test run
```

Iact3 resolves the configured test, creates one ROS stack in `cn-hangzhou`,
waits for the stack to finish, deletes the stack by default, and writes output
under `iact3_outputs/`.

## 5. Inspect the report

Open the HTML report:

```bash
open iact3_outputs/index.html
```

The output directory also contains a JSON summary and per-stack log files.
Use `--log-format json,xml` if you need additional machine-readable stack logs:

```bash
iact3 test run --log-format json,xml
```

## Useful next commands

Validate without creating a stack:

```bash
iact3 validate -t sleep.template.yml
```

Preview resources:

```bash
iact3 preview -t sleep.template.yml -r cn-hangzhou
```

Show generated parameters without creating stacks:

```bash
iact3 test params -t sleep.template.yml -c .iact3.yml -r cn-hangzhou
```

List stacks that Iact3 left behind:

```bash
iact3 list -r cn-hangzhou
```
