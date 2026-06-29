---
title: Terraform 目录
---

# Terraform 目录

Iact3 可以通过 ROS Terraform Transform 包装 `.tf` 文件，从而测试 Terraform
目录。

## 目录结构

```text
terraform-demo/
  main.tf
  .iact3.yml
```

`main.tf`：

```hcl
variable "name" {
  type = string
}

resource "alicloud_vpc" "default" {
  vpc_name   = var.name
  cidr_block = "172.16.0.0/12"
}
```

## 配置

`.iact3.yml`：

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

当 `template_location` 下找不到 `*.template.yml/json` 文件时，Iact3 会收集
`.tf` 文件并创建带有 `Workspace` 的 ROS 模板。

## 运行

```bash
iact3 test run --project-path terraform-demo
```

开发阶段可以加上 `--keep-failed`，便于检查失败栈。
