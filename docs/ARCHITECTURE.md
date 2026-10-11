# 架构说明

## 边界

本仓库只实现安全编排参考：它不上传文件、不访问第三方 API、不承载真实媒体、不保存密钥。

## 状态机

`PREVIEWED → PRE_DISPATCH → SUBMITTED → SUCCEEDED`

补充分支：

- `PREVIEWED → EXPIRED`：快照过期，必须重新预览；
- `PRE_DISPATCH → FAILED`：明确的不可重试 Provider 错误；
- `PRE_DISPATCH → UNKNOWN`：写入结果无法确认，禁止重新派发；
- `SUBMITTED/UNKNOWN → FAILED`：只读对账显示失败或 Read-back 不匹配。

状态转换写入 SQLite，且每个状态变化都追加审计记录。

## 数据模型

`ExecutionPlan` 包含稳定请求 ID、目标、Schema 版本、项目主键、Payload、Blast Radius 上限和 Snapshot TTL。计划内容序列化后计算 SHA-256 指纹；同一请求 ID 的不同指纹会被拒绝。

## 并发与恢复

SQLite 的 `plans` 是恢复事实源，不以页面缓存判断任务是否已经派发。Lease 表阻止两个 Worker 同时取得派发权。进程中断后，新 Engine 读取同一数据库并从 `SUBMITTED` 状态做只读 reconciliation。
