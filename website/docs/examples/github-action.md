---
title: GitHub Action
---

# GitHub Action

The repository includes a Docker-based GitHub Action for ROS template
repositories. It supports two modes: `validate` and `test`.

## Validate mode

```yaml
- name: Validate templates
  uses: aliyun/alibabacloud-ros-tool-iact3@master
  with:
    templates: "templates/vpc.yml templates/ecs.yml"
    access_key_id: ${{ secrets.ACCESS_KEY_ID }}
    access_key_secret: ${{ secrets.ACCESS_KEY_SECRET }}
    type: "validate"
```

Validate mode runs `iact3 validate -t <template>` for each YAML template.

## Test mode

```yaml
- name: Test templates
  uses: aliyun/alibabacloud-ros-tool-iact3@master
  with:
    templates: "templates/ecs.yml iact3-config/templates/ecs.iact3.yml"
    access_key_id: ${{ secrets.ACCESS_KEY_ID }}
    access_key_secret: ${{ secrets.ACCESS_KEY_SECRET }}
    type: "test"
```

Test mode looks for config files under `iact3-config/` that match template
paths. For `templates/ecs.yml`, the matching config path is
`iact3-config/templates/ecs.iact3.yml` or
`iact3-config/templates/ecs.iact3.yaml`.

## Config conventions

For test mode:

- The config file name must match the template file name.
- The config file suffix must be `.iact3.yml` or `.iact3.yaml`.
- The config path mirrors the template path under `iact3-config/`.
- If `template_config.template_location` is present, it should be relative to
  the repository root.

The action writes `status=success` when all templates pass. Otherwise it writes
`status=fail` and exits with a non-zero status.
