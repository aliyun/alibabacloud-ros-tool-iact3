# Iact3 GitHub Action

Iact3 Action is a Github Action aming at testing the Alibaba Cloud [ROS](https://www.alibabacloud.com/help/zh/resource-orchestration-service) templates. This action is used in the Iact3-test Workflow of ros-templates repository. Its purpose is to use the [Iact3](https://github.com/aliyun/alibabacloud-ros-tool-iact3) tool to test whether the ROS templates in pull request can be successfully deployed.

The [ros-templates](https://github.com/aliyun/ros-templates) repository provides many examples and best practice resources of Alibaba Cloud ROS templates, including resource-level template examples, comprehensive template examples, best practices for complex scenarios, templates based on Transform syntax, Alibaba Cloud document templates, and Compute Nest's best templates.
## Usage
```yaml
- name: Test templates
  uses: aliyun/alibabacloud-ros-tool-iact3@master
  with:
    templates: "template1.xml template2.xml"
    access_key_id: ${{ secrets.ACCESS_KEY_ID }}
    access_key_secret: ${{ secrets.ACCESS_KEY_SECRET }}
    type: "test"
```
## Action Inputs
| 名称                | 描述                                                         |
|-------------------|------------------------------------------------------------|
| templates         | space separated paths of templates and configuration files |
| access_key_id     | key_id of Alibaba Cloud account                            |
| access_key_secret | key_secret of Alibaba Cloud account                        | 
| type              | test type [ validate \| test ]                             | 

## Action Output
* `status` - `success/fail` Indicates whether the testing templates had all passed the Iact3 Action.

## Action Testing Process
### Test Objects
When the input parameter `type` is `validate`, the test objects are all ROS templates in the input parameter `templates`.

When the input parameter `type` is `test`, the test objects are all ROS templates included in the input parameter `templates`, and the ROS templates corresponding to the configuration files included in `templates`. When the ROS template corresponding to a configuration file does not exist in the repository, the test for this configuration file and the corresponding template will be skipped.

### Config file
When the input parameter `type` is `test`, if there is a configuration file in the corresponding location of the tested template, the template will be deployed according to the configuration file in test. The configuration file corresponding to the template must meet the following conditions:
* The configuration file name must be same as template name, and the suffix must be `.iact3.[yml|yaml]`
* The location of the configuration file should be fixed at the same path as the template under `iact3-config/` directory (`name.[yml|yaml]` corresponds to `iact3-config/name.iact3.[yml,yaml]`)
* The `project` configuration item `name` in the configuration file needs to be `test-{template name}`
* The `template_config:template_location` may not be included in the configuration file. If it is included, the template path needs to use a relative path relative to the root directory of the ros-template repository.

### Test Method
When the input parameter `type` is `validate`, Iact3 Action use the `iact3 validate` command to verify the validity of the template.

When the input parameter `type` is `test`, Iact3 Action use the `iact3 test run` command to deploy and test the template with the configuration file, and use the `iact3 validate` command to verify the validity of other templates.
### Test Result
If all the templates pass the test, Iact3 Action will output `status=success` to the workflow and return the exit status code `0`, otherwise it will output `status=fail` and return exit status code `1`.