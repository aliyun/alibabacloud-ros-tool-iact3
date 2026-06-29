---
title: GitHub Action
---

# GitHub Action

仓库内置了一个面向 ROS 模板仓库的 Docker GitHub Action。它支持 `validate`
和 `test` 两种模式。

## Validate 模式

```yaml
- name: Validate templates
  uses: aliyun/alibabacloud-ros-tool-iact3@master
  with:
    templates: "templates/vpc.yml templates/ecs.yml"
    access_key_id: ${{ secrets.ACCESS_KEY_ID }}
    access_key_secret: ${{ secrets.ACCESS_KEY_SECRET }}
    type: "validate"
```

Validate 模式会对每个 YAML 模板运行 `iact3 validate -t <template>`。

## Test 模式

```yaml
- name: Test templates
  uses: aliyun/alibabacloud-ros-tool-iact3@master
  with:
    templates: "templates/ecs.yml iact3-config/templates/ecs.iact3.yml"
    access_key_id: ${{ secrets.ACCESS_KEY_ID }}
    access_key_secret: ${{ secrets.ACCESS_KEY_SECRET }}
    type: "test"
```

Test 模式会在 `iact3-config/` 下查找和模板路径匹配的配置。对于
`templates/ecs.yml`，匹配配置是 `iact3-config/templates/ecs.iact3.yml` 或
`iact3-config/templates/ecs.iact3.yaml`。

## 配置约定

Test 模式下：

- 配置文件名必须和模板文件名一致。
- 配置文件后缀必须是 `.iact3.yml` 或 `.iact3.yaml`。
- 配置路径需要在 `iact3-config/` 下镜像模板路径。
- 如果配置中存在 `template_config.template_location`，应使用相对仓库根目录的路径。

所有模板通过时，Action 写入 `status=success`。否则写入 `status=fail` 并以
非零状态退出。
