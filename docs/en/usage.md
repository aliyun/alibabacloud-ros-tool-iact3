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
The cli is self documenting by using `--help` or `-h`, the most common command is `iact3 test`.
 Before testing template, the configuration file needs to be set up correctly. See [configuration docs](./config.md) for more details

```
iact3 test -h
usage: iact3 [args] test [args] [subcommand] [args] 

Performs functional tests on IaC templates.

options:
  -h, --help  show this help message and exit

subcommands:
  clean - Manually clean up the stacks which were created by iact3
  list - List stacks which were created by iact3 for all regions
  params - Generate pseudo parameters
  run - tests whether IaC templates are able to successfully launch
```

```
iact3 test run -h
usage: iact3 [args] <command> [args] run [args] 

tests whether IaC templates are able to successfully launch

options:
  -h, --help            show this help message and exit
  -t TEMPLATE, --template TEMPLATE
                        path to a template
  -c CONFIG_FILE, --config-file CONFIG_FILE
                        path to a config file
  -o OUTPUT_DIRECTORY, --output-directory OUTPUT_DIRECTORY
                        path to an output directory
  -r REGIONS, --regions REGIONS
                        comma separated list of regions to test in
  --test-names TEST_NAMES
                        comma separated list of tests to run
  --no-delete           don't delete stacks after test is complete
  --project-path PROJECT_PATH
                        root path of the project relative to config file,
                        template file and output file
  --keep-failed         do not delete failed stacks
  --dont-wait-for-delete
                        exits immediately after calling delete stack
  -g, --generate-parameters
                        generate pseudo parameters
```

## Get Template Estimate Cost  
### Cli Command
The cli is self documenting by using `--help` or `-h`, the most common command is `iact3 cost`
```
iact3 cost -h
usage: iact3 [args] cost [args] 

Give the price of the templates.

options:
  -h, --help            show this help message and exit
  -t TEMPLATE, --template TEMPLATE
                        path to a template
  -c CONFIG_FILE, --config-file CONFIG_FILE
                        path to a config file
  -r REGIONS, --regions REGIONS
                        comma separated list of regions
```

## Validate Template
### Cli Command
The cli is self documenting by using `--help` or `-h`, the most common command is `iact3 validate`

```
iact3 validate -h
usage: iact3 [args] validate [args]

Validate the templates.

options:
  -h, --help            show this help message and exit
  -t TEMPLATE, --template TEMPLATE
                        path to a template
  -c CONFIG_FILE, --config-file CONFIG_FILE
                        path to a config file
```

## Preview Template Stack
### Cli Command
The cli is self documenting by using `--help` or `-h`, the most common command is `iact3 preview`

```
iact3 preview -h 
usage: iact3 [args] preview [args]

Preview resources of templates.

options:
  -h, --help            show this help message and exit
  -t TEMPLATE, --template TEMPLATE
                        path to a template
  -c CONFIG_FILE, --config-file CONFIG_FILE
                        path to a config file
  -r REGIONS, --regions REGIONS
                        comma separated list of regions

```

## Get Template Policy
### Cli Command
The cli is self documenting by using `--help` or `-h`, the most common command is `iact3 policy`

```
iact3.py policy -h                            
usage: iact3 [args] policy [args]

Get policies of the templates.

options:
  -h, --help            show this help message and exit
  -t TEMPLATE, --template TEMPLATE
                        path to a template
  -c CONFIG_FILE, --config-file CONFIG_FILE
                        path to a config file
```

