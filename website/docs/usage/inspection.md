---
title: Template Inspection
---

# Template Inspection

Inspection commands call ROS APIs without running the full create-and-delete
test lifecycle.

## Validate a template

```bash
iact3 validate -t template.yml
```

When `-t` is omitted, Iact3 reads the template from `.iact3.yml` or searches the
project root for a `*.template.yml/json` file.

Use this command for fast syntax and ROS schema validation before running a
deployment test.

## Preview resources

```bash
iact3 preview -t template.yml -r cn-hangzhou
```

`preview` shows the resources ROS expects to create. It is useful for checking
resource types, dependencies, and parameter expansion before creating a stack.

## Query estimated cost

```bash
iact3 cost -t template.yml -r cn-hangzhou
```

`cost` asks ROS for a template estimate. The result depends on the resources and
regions supported by the ROS estimate API.

## Generate required policy

```bash
iact3 policy -t template.yml
```

`policy` generates policy information for the template. Use it when preparing a
least-privilege role for template testing.

## Options

| Command | Options |
| --- | --- |
| `validate` | `-t/--template`, `-c/--config-file`, `-r/--regions` |
| `preview` | `-t/--template`, `-c/--config-file`, `-r/--regions` |
| `cost` | `-t/--template`, `-c/--config-file`, `-r/--regions` |
| `policy` | `-t/--template`, `-c/--config-file`, `-r/--regions` |
