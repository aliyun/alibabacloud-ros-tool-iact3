---
title: Reports
---

# Reports

Iact3 writes reports under `iact3_outputs/` by default. Use
`-o/--output-directory` to choose another location.

```bash
iact3 test run -o ./reports
```

## Generated files

| File | Purpose |
| --- | --- |
| `index.html` | Human-readable report for the whole run. |
| `<project>-result.json` | Machine-readable run summary. |
| `<stack-name>-<region>.txt` | Per-stack text log. |
| `<stack-name>-<region>.json` | Optional per-stack JSON log when `--log-format json` is set. |
| `<stack-name>-<region>.xml` | Optional per-stack XML log when `--log-format xml` is set. |
| Hook result files | stdout or stderr captured from configured hooks. |

## JSON summary

The JSON summary is the best artifact for CI checks. It includes the project,
test, region, stack status, and final run result.

The bundled GitHub Action reads the JSON result and fails the workflow when the
run result is not `Success`.

## HTML report

Open `index.html` in a browser when debugging a local run:

```bash
open iact3_outputs/index.html
```

The HTML report links test results, stack events, outputs, and hook artifacts.

## Uploading report artifacts

Configure `oss_config` when hook output or report artifacts should be uploaded
to OSS:

```yaml
project:
  oss_config:
    bucket_name: my-report-bucket
    bucket_region: cn-hangzhou
    object_prefix: nightly
```

Use a dedicated bucket or prefix for CI runs so cleanup policies can be applied
independently from production artifacts.
