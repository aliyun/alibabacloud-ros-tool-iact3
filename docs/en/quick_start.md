## Installation
### Requirements
Install Python 3.7 or above.

### Install CLI
Execute the following command to install:

```bash
pip install alibabacloud-ros-iact3
```

## Configuration

### Authentication

The iact3 is run on requires access to an Alibaba Cloud account, this can be done by any of the following mechanisms:

1. AliyunCli default configuration file (~/.aliyun/config.json)
2. Environment variables (ALIBABA_CLOUD_ACCESS_KEY_ID and ALIBABA_CLOUD_ACCESS_KEY_SECRET)
3. The ini configuration file defined by the environment variable ALIBABA_CLOUD_CREDENTIALS_FILE
4. Alibaba Cloud SDK Credentials default configuration file (~/.alibabacloud/credentials.ini or ~/.aliyun/credentials.ini)

### Configuration Files

To use iact3, you need to prepare a configuration file, an example of a configuration file:

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

The above configuration file is explained as follows:

- `project` Indicates the basic information of the project item, including:
  - `name` Used to specify the configuration name
  - `template_config` Template for specifying the role of the configuration file
  - `regions` It is used to specify the region for the configuration file, and supports specifying multiple regions in the form of a list
- `tests` Indicates the test case information, the configuration file contains `test-name-1` and `test-name-2` two test cases
  - `parameters` Used to specify the parameter values in the template


For more configuration-related content, please refer to the [Config](en/config.md) section

## Cli Command
Go to the directory where the configuration file is located and execute the CLI command.

*ps1: iact3 will search for the configuration file `.iact3.yml` in the current directory, or you can specify a configuration file in any location by `-c` or `--config`.*

*ps2: If there is no configuration template in the configuration file, iact3 will search for a file ending with `.template.[json|yaml|yml]` in the current directory as a template file.*

### Template Testing
Tests whether IaC templates are able to successfully launch.

```bash
iact3 test run
```

### Create Base Resources
Create the basic resources required for testing in a specified region, including a VPC instance, a security group, and a VSwitch instance for each availability zone in the current region.

```bash
iact3 base create 
```

### Get Template Estimate Cost

Give the price of the templates.

```bash
iact3 cost
```

### Validate Template
Validate the templates.

```bash
iact3 validate 
```

### Preview Template Stack
Preview the resource stack information to be created by the template, and verify the accuracy of the template resources.
```bash
iact3 preview [options]
```


### Get Template Policy
Get policies of the templates.

```bash
iact3 policy 
```

For more command-line related content, please refer to the [Usage](en/usage.md) section.