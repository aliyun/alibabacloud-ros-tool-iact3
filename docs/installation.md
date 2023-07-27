# 安装
## 前置条件
安装Python 3.7 或以上版本

iact3 运行需要配置阿里云帐户，可以通过以下任一机制来完成：
1. 使用AliyunCli默认配置文件 (`~/.aliyun/config.json`)
2. 配置环境变量（`ALIBABA_CLOUD_ACCESS_KEY_ID` 和 `ALIBABA_CLOUD_ACCESS_KEY_SECRET`）
3. 使用环境变量`ALIBABA_CLOUD_CREDENTIALS_FILE`中定义的ini配置文件
4. 使用阿里云SDK凭证默认配置文件（`~/.alibabacloud/credentials.ini`或`~/.aliyun/credentials.ini`）

## 安装CLI
```bash
pip install alibabacloud-ros-iact3
```