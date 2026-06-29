<p align="center">
  <img src="website/static/img/iact3-logo.png" alt="Iact3 logo" width="96" height="96">
</p>

# Iact3

[![alibabacloud-ros-iact3](https://img.shields.io/pypi/v/alibabacloud-ros-iact3.svg)](https://pypi.python.org/pypi/alibabacloud-ros-iact3)
[![alibabacloud-ros-iact3](https://img.shields.io/pypi/pyversions/alibabacloud-ros-iact3.svg)](https://pypi.python.org/pypi/alibabacloud-ros-iact3)

Iact3 (IaC Template Testing Tool) is a CLI for testing
[Alibaba Cloud ROS(Resource Orchestration Service)](https://www.alibabacloud.com/help/resource-orchestration-service)
and [Terraform](https://developer.hashicorp.com/terraform) templates.

- Tests ROS and Terraform IaC templates before rollout.
- Runs templates with multiple test cases, parameters, and regions from a simple configuration file.
- Provides commands for validation, preview, cost estimation, policy inspection, stack cleanup, and pseudo-parameter generation.

## Requirements

- Python 3.7+

## Installation

```bash
pip install alibabacloud-ros-iact3
```

## Usage

Run template tests from the project root:

```bash
iact3 test run
```

Or pass an explicit project path:

```bash
iact3 test run --project-path ./demo
```

Common commands:

```bash
iact3 validate
iact3 preview
iact3 cost
iact3 policy
iact3 test params
```

## Building Standalone Binary

You can build iact3 as a standalone binary using PyInstaller, which requires no Python installation to run.

## Prerequisites

- Python 3.8+
- Build dependencies (`pip install ".[binary]"`)

## Build

```bash
python build.py
```

The binary will be generated at `dist/iact3` (or `dist/iact3.exe` on Windows).

## Pre-built Binaries

Pre-built binaries for Linux (amd64), macOS (arm64), and Windows (amd64) are available on the [Releases](https://github.com/aliyun/alibabacloud-ros-tool-iact3/releases) page. Download the appropriate binary for your platform and run it directly. (Apple Silicon only; Intel Mac users can install via `pip`.)

## Documentation

Fantastic documentation is available at:
[English](https://aliyun.github.io/alibabacloud-ros-tool-iact3/) |
[中文版](https://aliyun.github.io/alibabacloud-ros-tool-iact3/zh-cn/).
