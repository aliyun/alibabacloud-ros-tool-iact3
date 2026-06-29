---
title: Terraform Directory
---

# Terraform Directory

Iact3 can test a Terraform directory by wrapping `.tf` files in a ROS template
using ROS Terraform Transform.

## Directory

```text
terraform-demo/
  main.tf
  .iact3.yml
```

`main.tf`:

```hcl
variable "name" {
  type = string
}

resource "alicloud_vpc" "default" {
  vpc_name   = var.name
  cidr_block = "172.16.0.0/12"
}
```

## Config

`.iact3.yml`:

```yaml
project:
  name: terraform-demo
  regions:
    - cn-hangzhou
  template_config:
    template_location: .
    tf_version: Aliyun::Terraform-v1.2
tests:
  default:
    parameters:
      name: iact3-terraform-demo
```

When no `*.template.yml/json` file is found under `template_location`, Iact3
collects `.tf` files and creates a ROS template with a `Workspace` section.

## Run

```bash
iact3 test run --project-path terraform-demo
```

Use `--keep-failed` during development if you need to inspect a failed stack.
