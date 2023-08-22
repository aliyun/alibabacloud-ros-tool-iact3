# Usage

Iact3 adopts a similar cli command structure to `git` with a `iact3 command subcommand --flag` style. The cli is also designed to be the simplest if run from the root of a project. Let's have a look at equivalent command to run a test:

cd into the project root and type test run
```shell
cd ./demo
iact3 test run
```

or run it from anywhere by providing the path to the project root
```shell
iact3 test run --project-path ./demo
```

## Template Test
### Cli Command
```bash
iact3 test [subcommand] [options]
```
The cli is self documenting by using `--help` or `-h`, the most common command is `iact3 test`.
 Before testing template, the configuration file needs to be set up correctly. See [configuration docs](./config.md) for more details

### Subcommands

- `clean`: Manually clean up the stacks which were created by iact3.
- `list`: List stacks which were created by iact3 for all regions.
- `params`: Generate pseudo parameters.
- `run`: Tests whether IaC templates are able to successfully launch.

### Options
- `-t, --template`: path to a template
- `-c, --config-file`: path to a config file
- `-o, --output-directory`:  path to an output directory
- `-r, --regions`:  comma separated list of regions to test in
- `--test-names`:  comma separated list of tests to run
- `--no-delete `:   don't delete stacks after test is complete
- `--project-path`:  root path of the project relative to config file, template file and output file
- `--keep-failed`:  do not delete failed stacks
- `--dont-wait-for-delete`:  exits immediately after calling delete stack
- `-g, --generate-parameters`:  generate pseudo parameters
- `-l, --log-format`:  comma separated list of log format (xml,json)


## Get Template Estimate Cost  
### Cli Command
```bash
iact3 cost [options]
```
The cli is self documenting by using `--help` or `-h`, the most common command is `iact3 cost`

### Options
- `-t, --template`: path to a template
- `-c, --config-file`: path to a config file
- `-r, --regions`:  comma separated list of regions

## Validate Template
### Cli Command
```bash
iact3 validate [options]
```
The cli is self documenting by using `--help` or `-h`, the most common command is `iact3 validate`

### Options
- `-t, --template`: path to a template
- `-c, --config-file`: path to a config file

## Preview Template Stack
### Cli Command
```bash
iact3 preview [options]
```
The cli is self documenting by using `--help` or `-h`, the most common command is `iact3 preview`

### Options
- `-t, --template`: path to a template
- `-c, --config-file`: path to a config file
- `-r, --regions`:  comma separated list of regions

## Get Template Policy
### Cli Command
```bash
iact3 policy [options]
```
The cli is self documenting by using `--help` or `-h`, the most common command is `iact3 policy`

### Options
- `-t, --template`: path to a template
- `-c, --config-file`: path to a config file


