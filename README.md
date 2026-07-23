<p align="center">
  <img src="website/static/img/iact3-logo.png" alt="Iact3 logo" width="96" height="96">
</p>

# Iact3

Iact3(IaC Template Testing Tool) is a tool that tests [Alibaba Cloud ROS(Resource Orchestration Service)](https://www.alibabacloud.com/help/resource-orchestration-service) templates and  [Terraform](https://developer.hashicorp.com/terraform). It deploys your template in multiple Alibaba Cloud Regions and generates a report for each region via a simple configuration file.

It provides both a **command-line interface (CLI)** and a **web-based UI** for an interactive experience.

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

### CLI Mode

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

See the [documentation](https://aliyun.github.io/alibabacloud-ros-tool-iact3/#/en) for full CLI usage.

### Web UI Mode

Start the built-in web server for a browser-based interface:

```bash
iact3 server start
```

Then open your browser at [http://localhost:8088](http://localhost:8088).

The Web UI provides:
- **Workspace** — edit templates and config files, run analysis (validate, preview, cost, policy) and full tests in one page
- **Dashboard** — monitor test runs, browse analysis history, and manage projects
- **Reports** — view and download generated output files
- **Settings** — configure credentials and default values

Optional parameters:
- `--host` — bind address (default: `127.0.0.1`; use `0.0.0.0` for remote access)
- `--port` — port number (default: `8088`)
- `--token` — bearer token for API authentication (recommended when binding to non-local address)

Example:
```bash
iact3 server start --host 127.0.0.1 --port 9000
```

## Building Standalone Binary

You can build iact3 as a standalone binary using PyInstaller, which requires no Python installation to run.

### Prerequisites

- Python 3.8+
- Build dependencies (`pip install ".[binary]"`)

### Build

```bash
python build.py
```

The binary will be generated at `dist/iact3` (or `dist/iact3.exe` on Windows).

### Pre-built Binaries

Pre-built binaries for Linux (amd64), macOS (arm64), and Windows (amd64) are available on the [Releases](https://github.com/aliyun/alibabacloud-ros-tool-iact3/releases) page. Download the appropriate binary for your platform and run it directly. (Apple Silicon only; Intel Mac users can install via `pip`.)

## Documentation

Fantastic documentation is available at:
[English](https://aliyun.github.io/alibabacloud-ros-tool-iact3/) |
[中文版](https://aliyun.github.io/alibabacloud-ros-tool-iact3/zh-cn/).
