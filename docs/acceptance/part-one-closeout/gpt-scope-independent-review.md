# GPT 零模型作用域配置：独立窄复核

2026-10-14。实际受限元数据报告的 **21 项 canonical 配置**、原 / 受限 MCP 集合均为 1 且该项 explicitly enabled=false、两个显式 CodeModeHost 布尔 false、owned ephemeral thread 的空 environments / 0 turns 及 read/unsubscribe，均与冻结 helper 一致。独立只读字段 / hash 核对 **11/11，exit 0**；111 个产品 / tests / lock hash 无漂移，见 [JSON](C:/Users/asd15/Documents/ChatGPT/ai/docs/acceptance/part-one-closeout/gpt-scope-independent-review.json)。作者两个原语法失败报告和 helper 快照均保留，没有覆盖为成功。

没有重跑作者既有 13 个验证或绿 fixture，也没有启动 CLI / 模型、读 auth / HOME / native history。本 reviewer 新 starts=0。此实际 metadata snapshot 成功，不授予 `scope_enforced`；`runtime_scope_qualification=false` 与 `production_enabled=false` 正确保留。typed CodeModeHost 值是真实 raw effective 字段投影，不是 public ConfigRead 缺编译字段时的默认推断。

固定官方 tag `rust-v0.160.0` 中查到的真实配置刷新入口如下：

- [config_processor.rs:356–387](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/app-server/src/request_processors/config_processor.rs#L356) 重建各 thread 的 latest config / session layers，然后调用 `thread.refresh_runtime_config`。已定位入口是 batch-write 的 `reload_user_config=true`（172–177），以及 experimental feature enablement-set（192）。
- [plugins.rs:1536](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/app-server/src/request_processors/plugins.rs#L1536) 在实际 plugin install 后 reload user config，再 invalidate MCP runtime / refresh hooks。
- [mcp_processor.rs:85–92](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/app-server/src/request_processors/mcp_processor.rs#L85) 的显式 `mcp_server_refresh` 调 [mcp_refresh.rs:9–26](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/app-server/src/mcp_refresh.rs#L9)，从 latest session layers 载入并调用 `thread.refresh_mcp_config`。
- 已读 [SkillsWatcher:154–168](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/app-server/src/skills_watcher.rs#L154) 仅清 skills cache / 发 SkillsChanged；[FsWatch:110–140](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/app-server/src/fs_watch.rs#L110) 仅发被订阅路径的通知。这两条事件路径没有调用 MCP config reload。

证据缓存 `.tools/gpt-lifetime-source/`，public URL / SHA manifest 为该目录的 `source-manifest.json`，亦嵌入独立 JSON。猜测的旧 `codex_message_processor` 路径 404 已记录，修正为本版本 request_processors 布局；初始下载 exit 1 是调查路径错误，不是业务 RED。

**剩余未知：未闭合全仓库调用图，不能宣称 MCP 只有 trusted private-client RPC 才能刷新，也没有证据称普通文件变更必在本次线程自动触发。** 已定位的 Session refresh 确会更换 MCP config、标 dirty 并 prewarm；新 server 名称不受只枚举旧键的 overrides 覆盖。因此实际静态集合成功与整个 generation 生命周期上界必须分开。正式 runtime 仍需证明不可变 ceiling / 拒配置变化 / 可验证 dispatch 权限；单凭当前 21 项配置、空环境或无工具观测不能发行真实 scope capability。
