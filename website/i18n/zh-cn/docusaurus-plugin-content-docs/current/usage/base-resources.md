---
title: 基础资源
---

# 基础资源

有些模板需要已有 VPC、安全组或 VSwitch。Iact3 可以在测试账号中创建一组简单
的可复用基础资源。

## 创建基础资源

```bash
iact3 base create -r cn-hangzhou
```

在每个选定地域中，Iact3 会创建：

- 一个名为 `iact3` 的 VPC
- 一个名为 `iact3` 的安全组
- 每个可用区一个名为 `iact3-<zone>` 的 VSwitch

这些资源通过一个带有 Iact3 基础资源标签的 ROS 栈创建。

## 列出基础资源

```bash
iact3 base list -r cn-hangzhou
```

## 删除基础资源

```bash
iact3 base delete -r cn-hangzhou
```

## 参数

| 参数 | 含义 |
| --- | --- |
| `-r`, `--regions` | 逗号分隔的地域。省略时 Iact3 会查询所有地域。 |
| `-c`, `--config-file` | 用于读取凭证的配置文件。 |
| `--project-path` | 用于解析配置文件的项目根目录。 |

## 与伪参数配合使用

基础资源存在后，测试用例可以使用 `$[iact3-auto]` 获取 VPC、VSwitch 和安全组：

```yaml
tests:
  default:
    parameters:
      VpcId: $[iact3-auto]
      VSwitchId: $[iact3-auto]
      SecurityGroupId: $[iact3-auto]
```
