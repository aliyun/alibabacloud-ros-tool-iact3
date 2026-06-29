---
title: Installation
---

# Installation

Iact3 can be installed as a Python package, downloaded as a standalone binary,
or used through the Docker-based GitHub Action.

## Requirements

- Python 3.7 or later for the Python package.
- Python 3.9 or later when building the standalone binary with PyInstaller.
- Alibaba Cloud credentials with permission to call ROS and the services used by
  the template under test.

## Install from PyPI

```bash
pip install alibabacloud-ros-iact3
```

Verify that the console entry point is available:

```bash
iact3 --version
iact3 --help
```

## Use a standalone binary

Pre-built binaries are published on the project
[Releases](https://github.com/aliyun/alibabacloud-ros-tool-iact3/releases)
page for Linux amd64, macOS arm64, and Windows amd64.

Download the archive for your platform, unpack it, and run the `iact3` binary
directly. The binary includes the Python runtime and package dependencies.

## Build a standalone binary

```bash
python -m pip install --upgrade pip
pip install pyinstaller==6.11.1
pip install -r requirements.txt
python build.py
```

The generated binary is written to `dist/iact3` on Linux and macOS, or
`dist/iact3.exe` on Windows.

## Configure credentials

Iact3 uses Alibaba Cloud credentials from the same locations used by the
Alibaba Cloud SDK and Aliyun CLI. The supported sources are:

1. Aliyun CLI default configuration file: `~/.aliyun/config.json`
2. Environment variables: `ALIBABA_CLOUD_ACCESS_KEY_ID` and
   `ALIBABA_CLOUD_ACCESS_KEY_SECRET`
3. The ini file referenced by `ALIBABA_CLOUD_CREDENTIALS_FILE`
4. Alibaba Cloud SDK credential files:
   `~/.alibabacloud/credentials.ini` or `~/.aliyun/credentials.ini`

For project-specific CLI runs, pass `--profile` to select the Aliyun CLI
profile name:

```bash
iact3 --profile default test run
```

## Use the GitHub Action

The repository includes a Docker action. It is useful for ROS template
repositories that want to validate changed templates or run deployment tests
when a matching `.iact3` configuration exists.

```yaml
- name: Test templates
  uses: aliyun/alibabacloud-ros-tool-iact3@master
  with:
    templates: "templates/ecs.yml iact3-config/templates/ecs.iact3.yml"
    access_key_id: ${{ secrets.ACCESS_KEY_ID }}
    access_key_secret: ${{ secrets.ACCESS_KEY_SECRET }}
    type: "test"
```

See the [GitHub Action example](./examples/github-action.md) for details.
