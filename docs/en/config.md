
# Configuration files
There are 2 config files which can be used to set behaviors.

1. Global config file, located in `~/.iact3.yml`
2. Project config file, located in `<PROJECT_ROOT>/.iact3.yml`

Each configuration file supports three-tier configuration, which includes `general`, `project` and `tests`, and `tests` is required.

## general configuration item

- `auth` Aliyun authentication section.
```json
{
  "name": "default", 
  "location": "~/.aliyun/config.json"
}
```

- `oss_config` Oss bucket configuration, include BucketName, BucketRegion and etc.
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

- `parameters` Parameter key-values to pass to template.
```json
{
  "vpc_id": "",
  "vsw_id": ""
}
```

## project configuration item

- `name` Project Name
- `regions` List of aliyun regions.
- `parameters` Parameter key-values to pass to template.
- `tags` Tags
- `role_name` Role name
- `template_config` Template config
```json
{
  "template_location": "myTemplate/",
  "template_url": "oss://xxx",
  "template_body": "",
  "template_id": "",
  "template_version": ""
}
```

## tests configuration item

- `name` Project Name
- `regions` List of aliyun regions.
- `parameters` Parameter key-values to pass to template.
- `tags` Tags
- `role_name` Role name
- `template_config` Template config
```json
{
  "template_location": "myTemplate/",
  "template_url": "oss://xxx",
  "template_body": "",
  "template_id": "",
  "template_version": ""
}
```

# Precedence

Except the parameters section, more specific config with the same key takes precedence.

> The rationale behind having parameters function this way is so that values can be overridden at a system level outside a project, that is likely committed to source control. parameters that define account specific things like VPC details, Key Pairs, or secrets like API keys can be defined per host outside of source control. 

For example, consider this global config in `~/.iact3.yml`

```yaml
general:
  oss_config: 
    bucket_name: global-bucket
  parameters:
    KeyPair: my-global-ecs-key-pair
```

and this project config
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
Would result in this effective test configuration:

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

Notice that `bucket_name` and `regions` took the most specific value and `KeyPair` the most general.

# Pseudo Parameters

You can automatically get the available parameters through the `$[iact3-auto]` pseudo-parameter if the parameter is the following 2 cases
1. The resource attribute corresponding to the parameter supports the ROS [GetTemplateParameterConstraints](https://www.alibabacloud.com/help/en/resource-orchestration-service/latest/gettemplateparameterconstraints) interface.
2. Parameters whose name itself has a specific meaning. For example, `VpcId` means the id of virtual private cloud and `$[iact3-auto]` will automatically obtain a vpcId randomly in the current region of the current account. Currently supported are as follows:
   1. Satisfying the regularity `r"(\w*)vpc(_|)id(_|)(\d*)"` will automatically and randomly obtain the VpcId in the current region.
   2. Satisfying the regularity `r"(\w*)v(_|)switch(_|)id(_|)(\d*)"` will automatically and randomly obtain the VswitchId in the current region. If there is a parameter whose name satisfies the regularity `r"(\w*)zone(_|)id(_|)(\d*)"`, it will query the VswitchId of the corresponding availability zone
   3. Satisfying the regularity `r"(\w*)security(_|)group(_id|id)(_|)(\d*)"` will automatically and randomly obtain the SecurityGroupId in the current region.
   4. Satisfying the regularity `r"(\w*)name(_|)(\d*)"` will automatically generate a random string starting with `iact3-`.
   5. Satisfying the regularity `r"(\w*)password(_|)(\d*)"` will automatically generate a password.
   6. Satisfying the regularity `r"(\w*)uuid(_|)(\d*)"` will automatically generate an uuid.



















