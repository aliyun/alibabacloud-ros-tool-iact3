---
title: Base Resources
---

# Base Resources

Some templates need an existing VPC, security group, or VSwitch. Iact3 can
create a simple set of reusable base resources in test accounts.

## Create base resources

```bash
iact3 base create -r cn-hangzhou
```

For each selected region, Iact3 creates:

- One VPC named `iact3`
- One security group named `iact3`
- One VSwitch named `iact3-<zone>` for each availability zone

The resources are created through a ROS stack tagged as an Iact3 base resource.

## List base resources

```bash
iact3 base list -r cn-hangzhou
```

## Delete base resources

```bash
iact3 base delete -r cn-hangzhou
```

## Options

| Option | Meaning |
| --- | --- |
| `-r`, `--regions` | Comma-separated regions. If omitted, Iact3 queries all regions. |
| `-c`, `--config-file` | Config file used for credentials. |
| `--project-path` | Project root used to resolve the config file. |

## Using base resources with pseudo parameters

After base resources exist, test cases can use `$[iact3-auto]` for VPC,
VSwitch, and security group parameters:

```yaml
tests:
  default:
    parameters:
      VpcId: $[iact3-auto]
      VSwitchId: $[iact3-auto]
      SecurityGroupId: $[iact3-auto]
```
