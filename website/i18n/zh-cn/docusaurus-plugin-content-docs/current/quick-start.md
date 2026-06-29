---
title: 快速开始
---

# 快速开始

本指南使用一个很小的 ROS 模板跑通 Iact3，并展示报告位置。该命令会真实创建
ROS 资源栈，请使用测试账号和允许创建资源的地域。

## 1. 创建项目目录

```bash
mkdir iact3-demo
cd iact3-demo
```

## 2. 添加 ROS 模板

创建 `sleep.template.yml`：

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

## 3. 添加 Iact3 配置

创建 `.iact3.yml`：

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

## 4. 运行部署测试

```bash
iact3 test run
```

Iact3 会解析测试配置，在 `cn-hangzhou` 创建一个 ROS 栈，等待栈完成，默认删
除该栈，并将输出写入 `iact3_outputs/`。

## 5. 查看报告

打开 HTML 报告：

```bash
open iact3_outputs/index.html
```

输出目录中还会包含 JSON 汇总和每个栈的日志文件。如果需要额外的机器可读栈日
志，可以使用 `--log-format json,xml`：

```bash
iact3 test run --log-format json,xml
```

## 常用后续命令

不创建栈，只做模板校验：

```bash
iact3 validate -t sleep.template.yml
```

预览资源：

```bash
iact3 preview -t sleep.template.yml -r cn-hangzhou
```

不创建栈，只展示生成后的参数：

```bash
iact3 test params -t sleep.template.yml -c .iact3.yml -r cn-hangzhou
```

列出 Iact3 遗留的栈：

```bash
iact3 list -r cn-hangzhou
```
