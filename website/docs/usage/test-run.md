---
title: Deployment Tests
---

# Deployment Tests

`iact3 test run` is the core command. It creates real ROS stacks for every
configured test and region, waits for the result, runs hooks, deletes stacks by
default, and writes reports.

## Basic run

```bash
iact3 test run
```

Iact3 reads `.iact3.yml` from the current directory and searches the same
directory for a template if `template_config` is not set.

## Run from another directory

```bash
iact3 test run --project-path ./demo
```

`--project-path` changes the project root used for the config file, template
file, and output directory.

## Use explicit config and template files

```bash
iact3 test run \
  -t templates/ecs.template.yml \
  -c iact3-config/ecs.iact3.yml
```

## Restrict regions or tests

```bash
iact3 test run -r cn-hangzhou,cn-beijing --test-names default,small
```

`-r` overrides configured regions. `--test-names` runs only the named entries
from the `tests` section.

## Control deletion

By default, Iact3 deletes stacks after the test run.

```bash
iact3 test run --no-delete
```

Keeps all stacks after the run.

```bash
iact3 test run --keep-failed
```

Deletes successful stacks but keeps failed stacks for debugging.

```bash
iact3 test run --dont-wait-for-delete
```

Calls delete stack and exits without waiting for deletion to complete.

## Generate parameters without creating stacks

```bash
iact3 test run --generate-parameters
```

This resolves pseudo parameters and prints the effective parameter set. It does
not create stacks.

The shorter command is:

```bash
iact3 test params -c .iact3.yml -r cn-hangzhou
```

## Report formats

```bash
iact3 test run --log-format json,xml
```

The HTML report and JSON summary are always generated. `--log-format` adds
per-stack logs in the requested formats.

## Common options

| Option | Meaning |
| --- | --- |
| `-t`, `--template` | Path to a template file or template directory. |
| `-c`, `--config-file` | Path to the Iact3 config file. |
| `-o`, `--output-directory` | Output directory. Defaults to `iact3_outputs`. |
| `-r`, `--regions` | Comma-separated regions. |
| `--test-names` | Comma-separated test names. |
| `--project-path` | Project root. |
| `--no-delete` | Keep all stacks. |
| `--keep-failed` | Keep failed stacks. |
| `--dont-wait-for-delete` | Do not wait for stack deletion. |
| `-g`, `--generate-parameters` | Print resolved parameters instead of testing. |
| `-l`, `--log-format` | Comma-separated extra log formats: `json`, `xml`. |
