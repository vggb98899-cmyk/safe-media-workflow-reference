# 测试说明

运行：

```powershell
pytest -q
```

测试使用 `tmp_path` 创建隔离 SQLite 文件和 `MockProvider`；不需要 API Key，不访问网络，也不会读取任何真实素材。

覆盖项：

- 成功提交与 Read-back；
- 重复调用幂等；
- 缺失/重复主键；
- Target 不一致与不支持 Schema；
- 不可变计划冲突与 Snapshot 过期；
- Blast Radius；
- 瞬态只读查询有限重试；
- 不可重试错误；
- UNKNOWN 后禁止重复写；
- Read-back 不一致；
- 崩溃后恢复；
- Worker Lease 竞争；
- API Health。
