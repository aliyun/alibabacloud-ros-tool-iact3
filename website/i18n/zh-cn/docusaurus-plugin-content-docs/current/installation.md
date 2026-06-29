---
title: 安装
---

# 安装

Iact3 可以作为 Python 包安装，也可以下载 standalone binary，或通过基于
Docker 的 GitHub Action 使用。

## 前置条件

- Python 包安装需要 Python 3.7 或更高版本。
- 使用 PyInstaller 构建 standalone binary 需要 Python 3.9 或更高版本。
- 需要具备调用 ROS 和模板中相关云服务的阿里云凭证。

## 从 PyPI 安装

```bash
pip install alibabacloud-ros-iact3
```

验证命令入口可用：

```bash
iact3 --version
iact3 --help
```

## 使用 standalone binary

项目的 [Releases](https://github.com/aliyun/alibabacloud-ros-tool-iact3/releases)
页面提供 Linux amd64、macOS arm64 和 Windows amd64 的预构建二进制文件。

下载对应平台的压缩包，解压后直接运行 `iact3`。二进制文件已包含 Python 运行
时和依赖。

## 构建 standalone binary

```bash
python -m pip install --upgrade pip
pip install pyinstaller==6.11.1
pip install -r requirements.txt
python build.py
```

Linux 和 macOS 下产物位于 `dist/iact3`，Windows 下为 `dist/iact3.exe`。

## 配置凭证

Iact3 使用 Alibaba Cloud SDK 和 Aliyun CLI 常见的凭证来源：

1. Aliyun CLI 默认配置文件：`~/.aliyun/config.json`
2. 环境变量：`ALIBABA_CLOUD_ACCESS_KEY_ID` 和
   `ALIBABA_CLOUD_ACCESS_KEY_SECRET`
3. `ALIBABA_CLOUD_CREDENTIALS_FILE` 指向的 ini 文件
4. Alibaba Cloud SDK 凭证文件：
   `~/.alibabacloud/credentials.ini` 或 `~/.aliyun/credentials.ini`

如果需要选择 Aliyun CLI profile，可以传入 `--profile`：

```bash
iact3 --profile default test run
```

## 使用 GitHub Action

仓库内置了一个 Docker Action。它适合 ROS 模板仓库在 CI 中校验变更模板，或
在存在匹配 `.iact3` 配置时运行部署测试。

```yaml
- name: Test templates
  uses: aliyun/alibabacloud-ros-tool-iact3@master
  with:
    templates: "templates/ecs.yml iact3-config/templates/ecs.iact3.yml"
    access_key_id: ${{ secrets.ACCESS_KEY_ID }}
    access_key_secret: ${{ secrets.ACCESS_KEY_SECRET }}
    type: "test"
```

详细流程见 [GitHub Action 示例](./examples/github-action.md)。
