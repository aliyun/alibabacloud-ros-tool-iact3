## 安装
### 前置条件
安装Python 3.7 或以上版本

### 安装CLI
执行以下命令进行安装：

```bash
pip install alibabacloud-ros-iact3
```

## 配置

### 身份验证

使用 iact3 需要配置阿里云账号，可以通过任一一种方式配置:

1. 使用 AliyunCli 默认配置文件 (`~/.aliyun/config.json`)
2. 配置环境变量（`ALIBABA_CLOUD_ACCESS_KEY_ID` 和 `ALIBABA_CLOUD_ACCESS_KEY_SECRET`）
3. 使用环境变量`ALIBABA_CLOUD_CREDENTIALS_FILE`中定义的ini配置文件
4. 使用阿里云SDK凭证默认配置文件（`~/.alibabacloud/credentials.ini`或`~/.aliyun/credentials.ini`）


### 配置文件

使用 iact3 需要准备配置文件，配置文件示例：

```yaml
project:
  name: my-first-test
  template_config: 
    template_location: ~/ecs.yaml
  regions:
  - cn-hangzhou
  - cn-beijing
tests:
  test-name-1:
    parameters:
      InstanceType: ecs.g6e.large
  test-name-2:
    parameters:
      InstanceType: ecs.c6.large
```

上述配置文件解释如下：

- `project` 表示项目的基本信息，包括:
  - `name` 用于指定配置名称
  - `template_config` 用于指定配置文件作用的模板
  - `regions` 用于指定配置文件作用的地域，支持以列表形式指定多个地域
- `tests` 表示测试用例信息，该配置文件包含了`test-name-1`和`test-name-2`两个测试用例
  - `parameters` 用于指定模板中参数值


更多配置相关的内容请参考[配置](config.md)部分内容。

## 开始使用
进入到配置文件所在目录，执行 CLI 命令。

*注 1：iact3会在当前目录下查找`.iact3.yml`的配置文件，也可以通过`-c`或`--config`指定任意位置的配置文件。*

*注 2：如果配置文件中没有配置模板，iact3会在当前目录查找以`.template.[json|yaml|yml]`结尾的文件作为模板文件。*

### 模板测试
测试 IaC 模板是否能够成功创建。

```bash
iact3 test run 
```

### 创建基础资源
在指定地域创建测试所需要的基础资源，包括一个VPC实例、一个安全组和当前地域所有可用区各一个VSwitch实例。

```bash
iact3 base create 
```

### 模版询价

查询用模板创建资源时需要支付的价格。

```bash
iact3 cost 
```

### 模板校验
校验模板的合法性。

```bash
iact3 validate 
```

### 模版预览
预览模板将要创建的资源栈信息，验证模板资源的准确性。
```bash
iact3 preview
```


### 策略查询
查询模板所需的策略信息。

```bash
iact3 policy 
```

更多命令行相关的内容请参考[使用](usage.md)部分内容。
