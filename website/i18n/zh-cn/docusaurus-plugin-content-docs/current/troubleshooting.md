---
title: 排障
---

# 排障

## Iact3 找不到模板

如果配置中没有指定 `template_config`，Iact3 会在项目根目录查找以下后缀：

- `.template.json`
- `.template.yaml`
- `.template.yml`

如果仍未找到，它会继续查找 Terraform `.tf` 文件。模板位于其他位置时，传入
`-t` 或设置 `template_config.template_location`。

## 一次测试创建了太多栈

每个测试名称都会和每个解析后的地域相乘。检查 `general`、`project` 和每个
`tests` 条目中继承的 `regions`。

调试时使用 `--test-names` 和 `-r` 缩小范围：

```bash
iact3 test run --test-names default -r cn-hangzhou
```

## 失败栈在检查前被删除

运行时加上：

```bash
iact3 test run --keep-failed
```

只有在明确想保留所有栈时才使用 `--no-delete`。

## 清理命令没有找到栈

Iact3 清理依赖它添加到栈上的标签。如果标签被移除，或栈不是 Iact3 创建的，可
以在 ROS 控制台清理，或传入明确的栈 ID：

```bash
iact3 test clean -r cn-hangzhou --stack-id <stack-id>
```

## 凭证没有生效

检查当前 Aliyun CLI profile 和配置路径：

```bash
iact3 --profile default validate -t template.yml
```

如果使用环境变量，确认运行 Iact3 的 shell 或 CI job 中同时设置了
`ALIBABA_CLOUD_ACCESS_KEY_ID` 和 `ALIBABA_CLOUD_ACCESS_KEY_SECRET`。

## 伪参数没有解析

`$[iact3-auto]` 依赖 ROS 参数约束或字段名约定。如果参数名是自定义名称，请在
`parameters` 中直接提供明确值。

如果模板需要指定可用区中的 VSwitch，请同时包含 zone 参数。

## Hook 失败

Hook 的 stdout 或 stderr 会写到输出目录。报告显示 hook 失败时，使用相同参数在
Iact3 外单独运行该命令。

注意，栈输出只有在资源栈已经产生输出后，才能用于 post-create 和 pre-delete
阶段。
