---
title: Stack Listing and Cleanup
---

# Stack Listing and Cleanup

Iact3 tags stacks it creates so they can be listed and deleted later. Cleanup
commands are useful after interrupted tests, failed stacks, or runs that used
`--no-delete`.

## List Iact3 stacks

```bash
iact3 list -r cn-hangzhou,cn-beijing
```

Without `-r`, Iact3 queries all regions visible to the configured account.

`iact3 test list` is an alias for listing test stacks:

```bash
iact3 test list -r cn-hangzhou
```

## Delete Iact3 stacks

```bash
iact3 delete -r cn-hangzhou
```

This deletes stacks tagged with the Iact3 system tags.

## Clean a specific stack

```bash
iact3 test clean -r cn-hangzhou --stack-id <stack-id>
```

Use `--stack-id` when you want to delete one known stack instead of scanning for
all Iact3 stacks.

## Cleanup safety

Iact3 stack cleanup relies on tags:

- `CreatedBy=iact3`
- `iact3-id`
- `iact3-project-name`
- `iact3-test-name`

Do not remove these tags from stacks that you expect Iact3 to clean later.
