# OpenClaw FundAdvisor 邮件守卫

`email_sender.py` 是服务器 `smtp-sender` 技能的受控版本，只增加两项生产保护：

1. 拒绝主题或正文仅为 `test`、`测试` 等占位内容的邮件。
2. 对主题以 `FundAdvisor` 开头的日报，按“上海日期 + 收件人匿名哈希”原子认领发送权，同一收件人同一天最多发送一次。

普通 OpenClaw 邮件不使用 FundAdvisor 日报锁。SMTP 配置仍只保存在服务器原技能目录的 `smtp-config.json`，不得复制进仓库。

服务器匿名状态目录固定为：

```text
$HOME/.openclaw/state/fund-advisor-mail
```

目录权限应为 `0700`，单日状态文件权限应为 `0600`。状态文件不保存邮箱、主题、正文或持仓信息。

部署时先为服务器原 `email_sender.py` 创建权限 `0600` 的更新前快照，再上传本文件覆盖脚本；不得覆盖 `smtp-config.json`。上线验收只运行语法检查和合成 SMTP 测试，不向真实邮箱发送测试邮件。
