---
title: 栈列表和清理
---

# 栈列表和清理

Iact3 会为创建的栈打标签，后续可以据此列出和删除。测试中断、失败栈保留或使
用 `--no-delete` 后，清理命令会很有用。

## 列出 Iact3 栈

```bash
iact3 list -r cn-hangzhou,cn-beijing
```

省略 `-r` 时，Iact3 会查询当前账号可见的全部地域。

`iact3 test list` 也可以列出测试栈：

```bash
iact3 test list -r cn-hangzhou
```

## 删除 Iact3 栈

```bash
iact3 delete -r cn-hangzhou
```

该命令会删除带有 Iact3 系统标签的栈。

## 清理指定栈

```bash
iact3 test clean -r cn-hangzhou --stack-id <stack-id>
```

当只想删除一个已知栈，而不是扫描所有 Iact3 栈时，使用 `--stack-id`。

## 清理安全边界

Iact3 栈清理依赖这些标签：

- `CreatedBy=iact3`
- `iact3-id`
- `iact3-project-name`
- `iact3-test-name`

如果希望后续由 Iact3 清理某个栈，不要移除这些标签。
