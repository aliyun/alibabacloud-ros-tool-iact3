---
title: Troubleshooting
---

# Troubleshooting

## Iact3 cannot find a template

If the config does not specify `template_config`, Iact3 searches the project
root for files ending with:

- `.template.json`
- `.template.yaml`
- `.template.yml`

If none are found, it searches for Terraform `.tf` files. Pass `-t` or set
`template_config.template_location` when the template is elsewhere.

## A test creates too many stacks

Every test name is multiplied by every resolved region. Check inherited
`regions` values in `general`, `project`, and each `tests` entry.

Use `--test-names` and `-r` while debugging:

```bash
iact3 test run --test-names default -r cn-hangzhou
```

## Failed stacks were deleted before inspection

Run with:

```bash
iact3 test run --keep-failed
```

Use `--no-delete` only when you intentionally want to keep all stacks.

## Cleanup misses a stack

Iact3 cleanup relies on the tags it adds to stacks. If tags were removed or a
stack was not created by Iact3, use the ROS console or pass the explicit stack
ID:

```bash
iact3 test clean -r cn-hangzhou --stack-id <stack-id>
```

## Credentials are not picked up

Verify the selected Aliyun CLI profile and config path:

```bash
iact3 --profile default validate -t template.yml
```

If you use environment variables, ensure both
`ALIBABA_CLOUD_ACCESS_KEY_ID` and `ALIBABA_CLOUD_ACCESS_KEY_SECRET` are set in
the shell or CI job that runs Iact3.

## Pseudo parameters do not resolve

`$[iact3-auto]` depends on ROS parameter constraints or name-based conventions.
If a parameter has a custom name, provide an explicit value in `parameters`.

For VSwitch selection, include a zone parameter when the template needs a
VSwitch in a specific zone.

## A hook failed

Hook stdout or stderr is written under the output directory. Re-run the command
outside Iact3 with the same arguments when the report shows a hook failure.

Keep in mind that stack outputs are only available to post-create and
pre-delete phases after the stack has produced outputs.
