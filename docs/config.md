# 配置文件

Iact3 可以使用两种配置文件进行测试：
1. 全局配置文件`~/.iact3.yml`
2. 项目配置文件 `<PROJECT_ROOT>/.iact3.yml`

每种配置文件支持三层配置项：`general`,`project`,`tests`。其中，`tests`配置项是必须的。

## general 配置项
`general`配置中可以包含：
- `auth` 阿里云认证配置
   ```json
    {
        "name": "default", 
        "location": "~/.aliyun/config.json"
    }
    ```

-  `oss_config` Oss Bucket配置，包括BucketName、BucketRegion等
   ```json
    {
        "bucket_name": "",
        "bucket_region": "",
        "object_prefix": "",
        "callback_params": {
            "callback_url": "",
            "callback_host": "",
            "callback_body": "",
            "callback_body_type": "",
            "callback_var_params": ""
        }
     }
     ```
-  `parameters` 要传递给模板的参数键值
    ```json
    {
        "vpc_id": "",
        "vsw_id": ""
    }
   ```
## project 配置项
`project` 配置项中可以包含：
- `name`: 项目名称
- `regions`: 阿里云地域列表
- `parameters`: 要传递给模板的参数键值
- `tags`: 标签
- `role_name`: 角色名称
- `template_config`: 模板配置信息
    ```json
    {
        "template_location": "myTemplate/",
        "template_url": "oss://xxx",
        "template_body": "",
        "template_id": "",
        "template_version": ""
    }
    ```

## tests 配置项
`tests` 配置项中可以包含：
- `name`: 项目名称
- `regions`: 阿里云地域列表
- `parameters`: 要传递给模板的参数键值
- `tags`: 标签
- `role_name`: 角色名称
- `template_config`: 模板配置信息
    ```json
    {
        "template_location": "myTemplate/",
        "template_url": "oss://xxx",
        "template_body": "",
        "template_id": "",
        "template_version": ""
    }
    ```

## 优先级
除`parameters`里的配置外，具有相同键的更具体的配置优先。
> 这种参数处理方式的原理在于，可以在项目之外的系统级别上对值进行覆盖，这样就可以避免将这些参数添加到源代码项目中。像 VPC 详细信息、密钥对或 API 密钥等账户特定的参数可以在每个主机上定义，从而避免将其添加到源代码控制中。

例如，当全局配置文件`~/.iact3.yml` 内容如下：
```yaml
general:
  oss_config: 
    bucket_name: global-bucket
  parameters:
    KeyPair: my-global-ecs-key-pair
```
项目配置文件如下：
```yaml
project:
  name: my-project
  regions:
    - cn-hangzhou
  oss_config:
    bucket_name: project-bucket
tests:
  default:
    template_config:
      template_url: "oss://xxx"
    regions:
      - cn-beijing
    parameters:
      KeyPair: my-test-ecs-key-pair
```
最终Iact3测试使用的配置如下所示：
```yaml
tests:
  default:
    template_config:
      template_url: "oss://xxx"
    regions:
      - cn-beijing
    oss_config:
      bucket_name: project-bucket
    parameters:
      KeyPair: my-test-ecs-key-pair
```
可以注意到，`backet_name`和`regions`取了更具体配置中的值，而`KeyPair`取了更通用配置中的值。

## 伪参数
如果参数是以下2种情况时，可以通过`$[iact3-auto]`伪参数自动获取可用参数.
1. 参数对应的资源属性支持ROS [GetTemplateParameterConstraints](https://www.alibabacloud.com/help/en/resource-orchestration-service/latest/api-ros-2019-09-10-gettemplateparameterconstraints) 接口。
2. 名称具有特定含义的参数。 例如，`VpcId`表示虚拟私有云的id，`$[iact3-auto]`会自动在当前账户的当前地域随机获取一个vpcId。 目前支持的有此类参数有：
   1. 名称满足正则`r"(\w*)vpc(_|)id(_|)(\d*)"`的参数，会自动随机获取当前区域的VpcId。
   2. 名称满足正则`r"(\w*)v(_|)switch(_|)id(_|)(\d*)"`的参数，会自动随机获取当前区域的VswitchId。 如果同时有参数名称满足正则`r"(\w*)zone(_|)id(_|)(\d*)"`，则会查询对应可用区的VswitchId。
   3. 名称满足正则`r"(\w*)security(_|)group(_id|id)(_|)(\d*)"`的参数，会自动随机获取当前区域的SecurityGroupId。
   4. 名称满足正则`r"(\w*)name(_|)(\d*)"`的参数，会自动生成一个以`iact3-`开头的随机字符串。
   5. 名称满足正则`r"(\w*)password(_|)(\d*)"`的参数，会自动生成密码。
   6. 名称满足正则`r"(\w*)uuid(_|)(\d*)"`的参数，会自动生成一个uuid。