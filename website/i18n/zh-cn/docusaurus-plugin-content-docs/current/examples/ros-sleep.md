---
title: ROS Sleep 模板
---

# ROS Sleep 模板

该示例使用 `ALIYUN::ROS::Sleep` 测试 Iact3 生命周期，不创建付费云资源。

## 模板

`sleep.template.yml`：

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

## 配置

`.iact3.yml`：

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

## 运行

```bash
iact3 test run
```

这个示例适合第一次 smoke test，因为它会覆盖资源栈创建、输出收集、删除和报告
生成。
