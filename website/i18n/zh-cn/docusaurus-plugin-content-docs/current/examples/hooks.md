---
title: Hooks
---

# Hooks

Hooks 可以在资源栈创建和删除前后运行外部命令。它适合做 endpoint 检查、计算
巢校验或收集额外诊断信息。

## 配置

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

## 运行时值

Iact3 会在执行命令前替换这些值：

| 占位符 | 含义 |
| --- | --- |
| `$[stack.name]` | ROS 资源栈名称。 |
| `$[stack.region]` | 资源栈地域。 |
| `$[outputs.Name]` | 名为 `Name` 的 ROS 栈输出。 |

## Hook 结果

Iact3 会将 stdout 或 stderr 捕获到报告目录下的 hook 结果文件中。如果配置了
`oss_config`，hook 结果也可以上传到 OSS。

## 失败处理

写入 stderr 的 hook 会被记录为失败。建议让 hook 命令保持小而确定，这样部署结
果和 hook 结果更容易判断。
