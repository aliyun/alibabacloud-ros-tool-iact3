---
slug: /
sidebar_position: 1
title: Introduction
---

# Iact3

Iact3 is an Infrastructure as Code template testing tool for Alibaba Cloud
[Resource Orchestration Service (ROS)](https://www.alibabacloud.com/product/ros)
and Terraform templates that are executed through ROS Transform. It reads a
small project configuration, expands it into test cases across one or more
regions, creates stacks, waits for the results, cleans up resources, and writes
a report for every run.

Use Iact3 when you need to answer these questions before a template is merged
or published:

- Can this ROS or Terraform template be deployed in the target regions?
- Do different parameter sets produce deployable stacks?
- Which resources would the stack create, and what policy permissions does it
  require?
- What is the estimated cost of the configured resources?
- Which stack outputs and hook results should be captured in an auditable
  report?

The main user interface is the `iact3` CLI. It is designed to run locally, in
CI, or from the bundled GitHub Action for ROS template repositories.

## Main capabilities

| Capability | Command family | What it does |
| --- | --- | --- |
| Deployment test | `iact3 test run` | Creates ROS stacks for each configured test and region, waits for terminal state, runs hooks, and writes reports. |
| Template inspection | `iact3 validate`, `preview`, `cost`, `policy` | Calls ROS APIs to validate templates, preview resources, query estimates, and generate required policies. |
| Parameter generation | `iact3 test params` or `--generate-parameters` | Resolves `$[iact3-auto]` pseudo parameters such as VPC, VSwitch, SecurityGroup, names, passwords, and UUIDs. |
| Base resources | `iact3 base create/list/delete` | Creates or removes a VPC, security group, and one VSwitch per availability zone for test accounts. |
| Stack cleanup | `iact3 list`, `delete`, `test clean` | Finds and deletes stacks tagged as created by Iact3. |
| CI integration | GitHub Action | Validates templates and runs configured deployment tests from workflow inputs. |

## Documentation map

Start with [Installation](./installation.md), then follow the
[Quick Start](./quick-start.md). When you are ready to use Iact3 in a template
repository, read [Core Concepts](./concepts.md), [Configuration Reference](./configuration.md),
and the task-oriented [Usage](./usage.md) section.
