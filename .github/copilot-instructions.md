## 快速目标

为 AI 编码代理提供可执行、仓库内可验证的上下文和示例，帮助代理快速完成相关改动：调试 GLaDOS 签到逻辑、修改邮箱验证码提取或调整 config 写回逻辑。

## 一句话架构概览

这是一个以模块 `modules/glados` 为核心的签到脚本集合：
- `modules/glados/glados.py` — 核心客户端实现（GladosClient），负责登录（cookies/token/邮箱验证码）、刷新状态、签到与批量通知。
- `modules/glados/mailbox_client.py` — IMAP 邮箱助手：通过 IMAP 拉取邮件并提取 6 位验证码（支持 163/126/qq/gmail）。
- `modules/glados/config.py` — 基于 ruamel.yaml 的配置读取/写回工具（保留引号/尽量保持原排版）。
- `common/logger.py`、`common/notify.py` — 全局日志与通知桥接（在青龙环境优先路由到 sendNotify/notify）。
- 任务入口：`modules/glados/main.py` / `tasks/task_glados.py`（两种路径风格，注意传入的 config 路径）。

## 关键约定与样例

- 配置对象：使用 `Config(path)`，通过 `cfg.glados` 与 `cfg.email` 访问。示例：

  - GladosClient 的构造： `client = GladosClient("config.yaml")` 或在任务中 `GladosClient("glados/config.yaml")`。

- accounts 配置项（位于 `glados.accounts`）是一个列表，每项为 dict，常见字段：
  - name: 唯一标识（用于 login/checkin）
  - username: 登录邮箱地址
  - cookies / token: 优先使用
  - balance / leftDays / traffic: 会被程序更新并写回 config

- 登录优先级（在 `GladosClient.login_account` 中实现）:
  1. 使用已保存的 `cookies`
  2. 使用 `token`（添加到 Authorization header）
  3. 使用邮箱验证码（通过 `MailBoxClient` 拉取验证码再提交）

- 邮箱验证码提取细节（在 `MailBoxClient.get_verification_code`）：
  - 默认使用正则 r"\b\d{6}\b" 来匹配 6 位码
  - 支持 `delete_after_find=True`，实现为 COPY 到回收箱再标记 `\Deleted` 并 EXPUNGE（注意：EXPUNGE 会影响该 mailbox 上所有已标记的邮件）

- 配置写回：`Config.set` 会即时 save（ruamel.yaml 用于尽量保留原格式）；如果修改字段名或结构，注意保持 YAML 兼容性。

## 运行 / 调试（本地 vs 青龙）

- 本地快速运行（在工作区根）：

  - 使用 modules 的入口：
    - python modules/glados/main.py
    - 或者运行任务脚本： python tasks/task_glados.py

- 在青龙（QingLong）中：
  - `common/notify.py` 会尝试导入青龙的 `notify.send` 或 `sendNotify.send`；因此在青龙上运行会把通知路由到系统通知。调试时本地 fallback 会打印内容。

## 常见修改点与注意事项（对 AI 代理）

- 当修改登录/验证码逻辑时：
  - 同步更新 `MailBoxClient.get_verification_code` 的正则/时间过滤与 `GladosClient.login_account` 中的邮件读取超时（attempts / wait_seconds）默认值。
  - 避免在 `get_verification_code` 中盲目调用 `expunge()`：这会删除所有已标记为 Deleted 的邮件，若修改请标注风险。

- 当修改配置写回：
  - `Config.save()` 使用 ruamel.yaml，会尽量保留注释/引号，测试时对比文件 diff，避免破坏原有格式。

- 日志与错误处理：
  - 全局 logger 在 `common/logger.py` 中注册为 `logger`，代理直接调用 `from common.logger import logger`。

## 典型代码片段（参考）

- 执行一次完整签到流程（示例）：

  from modules.glados.glados import GladosClient
  client = GladosClient("config.yaml")
  client.checkin_all()

- 从配置读取邮箱并尝试获取验证码（重要字段引用）：

  cfg = Config("config.yaml")
  email_cfg = cfg.email  # 包含 address/password/provider/ssl
  mail = MailBoxClient(email_cfg["address"], email_cfg["password"], email_cfg.get("provider", "qq"))

## 需要 AI 代理优先考虑的任务（建议优先级）

1. 修复或改进验证码匹配（`modules/glados/mailbox_client.py`）并增加单元测试。
2. 将 `Config` 的写操作改为更安全的原子写入（写临时文件再替换），以避免并发写入问题。
3. 为 `GladosClient.checkin_all` 增加并发控制或速率限制（当前为串行）。

## 快速参考路径

- 入口/任务: `tasks/task_glados.py`, `modules/glados/main.py`
- 核心逻辑: `modules/glados/glados.py`
- 邮箱: `modules/glados/mailbox_client.py`
- 配置: `modules/glados/config.py`
- 日志/通知: `common/logger.py`, `common/notify.py`

---
请审阅此草案：如果需要我把其中某一节扩充为可执行的单元测试、示例 config.yaml 或添加注意到 PR 模板/CI 检查说明，我可以继续实现。谢谢！
