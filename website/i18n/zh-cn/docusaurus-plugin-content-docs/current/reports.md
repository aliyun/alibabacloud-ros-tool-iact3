---
title: 报告
---

# 报告

Iact3 默认将报告写入 `iact3_outputs/`。可以用 `-o/--output-directory` 指定
其他目录。

```bash
iact3 test run -o ./reports
```

## 生成文件

| 文件 | 作用 |
| --- | --- |
| `index.html` | 整次运行的人类可读报告。 |
| `<project>-result.json` | 机器可读运行汇总。 |
| `<stack-name>-<region>.txt` | 每个资源栈的文本日志。 |
| `<stack-name>-<region>.json` | 设置 `--log-format json` 时生成的每栈 JSON 日志。 |
| `<stack-name>-<region>.xml` | 设置 `--log-format xml` 时生成的每栈 XML 日志。 |
| Hook 结果文件 | 配置的 hooks 输出的 stdout 或 stderr。 |

## JSON 汇总

JSON 汇总是 CI 中最适合消费的产物。它包含项目、测试、地域、栈状态和最终运行
结果。

内置 GitHub Action 会读取 JSON 结果，当运行结果不是 `Success` 时让 workflow
失败。

## HTML 报告

本地调试时打开 `index.html`：

```bash
open iact3_outputs/index.html
```

HTML 报告会关联测试结果、栈事件、输出和 hook 产物。

## 上传报告产物

如果需要把 hook 输出或报告产物上传到 OSS，可以配置 `oss_config`：

```yaml
project:
  oss_config:
    bucket_name: my-report-bucket
    bucket_region: cn-hangzhou
    object_prefix: nightly
```

CI 场景建议使用独立 Bucket 或独立 prefix，便于和生产产物分开设置清理策略。
