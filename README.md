# IaC Template Testing Tool

Iact3(IaC Template Testing Tool) is a tool that tests [Alibaba Cloud ROS(Resource Orchestration Service)](https://www.alibabacloud.com/help/resource-orchestration-service) templates and  [Terraform](https://developer.hashicorp.com/terraform). It deploys your template in multiple Alibaba Cloud Regions and generates a report for each region via a simple configuration file.  

# Requirements
Python 3.10+

# Installation

`pip install alibabacloud-ros-iact3`

# Document

Fantastic documentation is available at:
[English](https://aliyun.github.io/alibabacloud-ros-tool-iact3/#/en) |
[中文版](https://aliyun.github.io/alibabacloud-ros-tool-iact3).

# Building Standalone Binary

You can build iact3 as a standalone binary using PyInstaller, which requires no Python installation to run.

## Prerequisites

- Python 3.10+
- PyInstaller (`pip install pyinstaller==6.11.1`)
- Project dependencies (`pip install -r requirements.txt`)

## Build

```bash
python build.py
```

The binary will be generated at `dist/iact3` (or `dist/iact3.exe` on Windows).

## Pre-built Binaries

Pre-built binaries for Linux (amd64), macOS (arm64), and Windows (amd64) are available on the [Releases](https://github.com/aliyun/alibabacloud-ros-tool-iact3/releases) page. Download the appropriate binary for your platform and run it directly. (Apple Silicon only; Intel Mac users can install via `pip`.)
