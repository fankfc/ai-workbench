# ZCode official account host → native session slice

固定公开源码 commit `aac4755666d09fdcd70272fcf063c077a639015f` 的最小官方账户配置源已成功接入安装 CJS 的**零模型 metadata 会话**：capabilities、账户配置接收确认、strict create、owned read、close 全部取得经官方 schema 验证的响应。读取本次会话实际 current 为 `account:zai-start-plan / GLM-5.3`，available 为 `GLM-5.3` 和 `GLM-5.3-Flash`，没有 disabled/unknown 目录项。child 正常退出，D011 Job 实际 running/temp/open_handles/active_processes 全为 0。

本切片实际执行 **3 次 metadata 启动、0 次新余额 GET、0 次模型调用**。目录种植只复用真实 HTTP200 receipt `2a9075a22a9c3b280d295e5d56386e91f20b280074254eed54c65d7d14b0291d`，捕获时间 `2026-10-14T04:07:13.911088+00:00`；最后探针的历史 receipt age 为 3404 秒。它证明历史账户目录来源，不能作为本轮 inference 权限。之前 3 次实际余额 GET/4 个 account host 阶段的证据仍独立保存在 [账户宿主报告](zcode-supported-host-build.md)，不能与本切片混算。

三阶段保留如下。

1. 首次 metadata：服务端内部错误 `-32603`，未捕获 stage/method；raw frames 已销毁，精确归因 unknown，未追造日志。
2. 新 diagnostic：官方 bootstrap 只有双 env 明确存在才保持 builtin 文件；builtin-only 会重定向活动 cache。采用公开 installed builtin + workspace 官方 canonical 空 personal 配置，SDK 与 CJS 命名空间一致。该条件改变后 caps/accountconfig 确认与 create 返回已通过，随后本地 `B_SESSION_SELECTION_UNAVAILABLE`。双 env 与首次错误的因果关系不能凭这次变化独断。
3. 最后 catalog binding：修正临时 helper 的 available 形状错误。官方 `zcodeModelOptionSchema` 的目录项为 `{ref:modelSelection,...}`，current 为直接 selection；旧 helper 误以 direct selection 解码目录而全部过滤。5 个业务 RED → 6 个 GREEN 后，最后一次受管实际验证完成 create/read/close。阶段/实际 bootstrap/codec/schema/catalog 合计 20 个离线检查通过。

该错误仅属于 ignored helper，冻结的生产 `zcode_protocol.py` 原本正确解包 ref，未修改任何冻结生产源码、测试或锁，也未重复全量回归。工作区 personal 文件只含官方 schema 与空配置规则，不含 providers/default model/credentials；用户安全规则和用户配置未修改。SDK personal revision 按官方 canonical 内容算法计算。

每个实际 RPC 的固定 stage/method/响应确认记录在 [结构化报告](zcode-host-session-slice.json)。账户更新的 `receivedRevision` 只证明接收，公开协议未返回 applied revision；该字段仍 null。请求使用 guarded/deferred/title=false/toolAllowlist=[]/dynamic=false/offPeak=false，没有 legacy 重试删字段。reasoning 请求值为 low，但实际 current 的公开投影未携带 reasoning，因此没有授予返回档位已验证的结论。

账户材料仅在官方 SDK 私有内存与匿名父子管道中，不输出 token/device 原值/headers/raw body。SDK guard mutation attempts 为 0，但该 guard 只覆盖已审可信 SDK 调用路径，并非 OS sandbox；CJS 标准工作区/存储动作不由 host guard 的计数证明。各阶段私有 raw stdout 只在有界内存使用，未封存 frames。

metadata 路径未请求认证 headers，`headers_applied=false`，`auth_service_exercised=false`。服务端实际 response.model 身份、OS scope、真实 provider 执行能力和 production enabled 均 false。最小原生目录接入已证明；下一次 B1 不因目录接入而自动授权，不再次启动 native metadata 循环。

历史字节与 claim/receipt 分别封存于 `.tools/zcode-supported-sdk/session-slice/first-session-stage/`（8 源文件）、`diagnostic-session-stage/`（15 源文件）和 `catalog-session-stage/`（16 源文件）。全部源 SHA、Node/CJS SHA 与旧 receipt SHA 经实际 postrun 校验一致；新 SDK 305 个公开官方输入也匹配固定 commit 的 Git blob。首次 evidence 的 method/stage 缺口继续明确保留。
