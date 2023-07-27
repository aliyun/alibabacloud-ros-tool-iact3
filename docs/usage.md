# 使用

Iact3 采用与 `git` 类似的 cli 命令结构，使用 `iact3 command [subcommand] --flag` 结构。 Iact3 也可以直接在项目的根目录运行。简单使用方式如下：

进入项目根目录并使用`command [subcommand]`命令，例如`test run`：
```bash
cd ./demo
iact3 test run
```

或在任意位置通过提供项目路径运行测试
```bash
iact3 test run --project-path ./demo
```

## 模版测试
测试项目中的模板和配置是否可以成功创建。
### 命令
```bash
iact3 test [subcommand] [options]
```
### 子命令
- `clean`: 清理 Iact3 创建的堆栈
- `list`: 列出 Iact3 为所有地域创建的堆栈
- `params`: 生成并展示模板伪参数
- `run`: 测试 IaC 模板是否能够成功创建

### 参数
支持如下可选项：
- `-t, --template`: 模板的路径
- `-c, --config-file`: 配置文件的路径
- `-o, --output-directory`:  输出目录的路径
- `-r, --regions`:  以逗号分隔的要测试的地域列表
- `--test-names`:  以逗号分隔的要运行的测试列表
- `--no-delete `:   测试完成后不删除堆栈
- `--project-path`:  带有模板和配置文件的项目根路径
- `--keep-failed`:  不删除失败的堆栈
- `--dont-wait-for-delete`:  调用删除堆栈后立即退出
- `-g, --generate-parameters`:  生成伪参数
- `-l, --log-format`:  以逗号分隔的测试日志格式列表（支持xml、json）

## 模版询价
查询用模板创建资源时需要支付的价格。
### 命令
```bash
iact3 cost [options]
```
### 参数
- `-t, --template`: 模板的路径
- `-c, --config-file`: 配置文件的路径
- `-r, --regions`:  以逗号分隔的要测试的地域列表

## 模板校验
校验模板的合法性。
### 命令
```bash
iact3 validate [options]
```
### 参数
- `-t, --template`: 模板的路径
- `-c, --config-file`: 配置文件的路径

## 模版预览
预览模板将要创建的资源栈信息，验证模板资源的准确性。
### 命令
```bash
iact3 preview [options]
```
### 参数
- `-t, --template`: 模板的路径
- `-c, --config-file`: 配置文件的路径
- `-r, --regions`:  以逗号分隔的要测试的地域列表

## 策略查询
查询模板所需的策略信息。
### 命令
```bash
iact3 policy [options]
```
### 参数
- `-t, --template`: 模板的路径
- `-c, --config-file`: 配置文件的路径

## 查看帮助信息
### 命令
```bash
iact3 -h 
iact3 command -h 
iact3 command subcommand -h
```