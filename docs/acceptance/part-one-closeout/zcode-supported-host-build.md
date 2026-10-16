# ZCode supported source host — real account availability

2026-10-14：隔离构建及真实账户元数据验证已完成。最后一次官方余额 GET 返回 **HTTP 200**，SDK 确认 `account:zai-start-plan` 当前 **available**，服务器返回模型 `GLM-5.3`、`GLM-5.3-Flash`。本轮累计 **3 次真实余额 GET、0 次模型请求**；完整 B 执行、执行模型身份、OS scope 与生产启用仍未通过。[完整 JSON 证据](./zcode-supported-host-build.json)。

## 固定来源与本地构建

官方来源固定为 `zai-org/ZCode` commit `aac4755666d09fdcd70272fcf063c077a639015f`。下载归档 SHA256 为 `a77cb72315deb872fb7de183111f3b8887e30c4cff5f99e5c23794238899bee3`，89,405,689 bytes。最终 bundle 有 332 个输入，其中 **236 个官方源码输入的 Git blob hash 全部匹配**完整固定 tree，未改 upstream 源码。

只在 [.tools/zcode-supported-sdk](../../../.tools/zcode-supported-sdk/) 安装了 upstream 锁中的 `esbuild@0.25.12`、`zod@4.6.5` 及 esbuild 对应 Windows 二进制。使用独立空 npm user/global 配置、禁 lifecycle scripts、本地 cache/lock；未全局安装、未改产品锁。构建只引入官方 CredentialService、OAuthCredentialRepo、Start Plan availability、余额 URL 与来源头 helpers，未引入 `createLocalServices`、桌面宿主、设置迁移、CA 或后台服务。[官方 manifest](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/packages/services/package.json)。实际命令和依赖完整性记录见 [commands.json](../../../.tools/zcode-supported-sdk/commands.json) 及报告 JSON。

## 四个独立保存的阶段

| 阶段 | 真实观察 | 解释 |
| --- | --- | --- |
| 首次构建 | HTTP 400，availability unknown | 本地 esbuild 漏官方 define；SDK version 回退 `0.0.0-dev`，且未带 device header。不能据此判断账号或路线不可用。 |
| 修正构建后前置失败 | exit 1，**0 HTTP** | 官方 Headers 转小写，本地 title 校验错误要求大写键；新增行为 RED 后修正。claim 保留。 |
| 修正版本及 Headers | HTTP 400、numeric code **3001**，unknown | SDK 3.15.1/production、诚实 external source；仍未带必需设备头。 |
| 官方只读既有设备 reader | **HTTP 200、available** | SDK 内部读既有 MID 并用于同一余额 GET；只输出 present/applied 布尔。 |

官方规范明文规定余额接口必须带既有 `X-Device-Mid`，缺失返回 HTTP 400/code 3001。纯 header builder 只在调用方供值时加入它；服务 helper 从既有 telemetry state 读取。补齐后的成功支持这个具体协议修正，前述失败不是 token 失效、无套餐或 external source 非法的证据。[设备头规范](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/docs/zcode-endpoint-device-mid-header.md)，[可用性语义](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/docs/model-provider-coding-plan-availability.md)。

各阶段 receipt、claim 和源码均单独保存：[first](../../../.tools/zcode-supported-sdk/first/)、[前置失败](../../../.tools/zcode-supported-sdk/diagnostic-preflight-failed/)、[3001](../../../.tools/zcode-supported-sdk/corrected-HTTP3001/)、[200](../../../.tools/zcode-supported-sdk/existing-mid-phase/)。**36 个阶段源码 hash 全部与对应原冻结 manifest 匹配**。部分旧公开 bundle/test 字节按原 SHA256 精确重建，JSON 已注明；没有封存 credential、device 标识值或 raw response。历史报告链接已改为匹配旧字节的封存路径，未把新工作路径说成旧 hash 仍相同。

## 只读与传输边界

SDK import、凭据或 device 读取前即封锁 Node 文件修改/复制/备份/删除/可写 open 和子进程启动；credential save/delete、OAuth save/set/clear 也拒绝。SDK 原始 console/stdout/stderr 被抑制，仅固定 metadata 投影可输出。这个 guard 覆盖已审固定可信调用链，**不宣称 OS sandbox**。真实调用的 FS/process mutation attempts 均为 0；官方损坏 JSON/解密错误的备份及清理路径已用临时夹具证明保留原字节。

公开 ApiClient 只允许 exact 官方 HTTPS balance GET，禁 body/redirect，每次 15 秒、65,536-byte cap，整进程 30 秒、独立排他 claim。最终使用明确 service request-id，不生成任何 UUID。默认 SDK reader 只读既有 device field，不创建/更新；缺失或非法即停止 HTTP。没有读取其它 device cache、凭据明文或账户 profile；授权材料一直留在私有 SDK/transport 中。

SDK 默认内部 title 在发请求前通过公开 context API 改成真实的 `zcode-supported-sdk-investigation`，外部 User-Agent 明确，未以 `electron` 发出请求。模型请求 security policy 未被引入、替换、禁用或绕过。[公开 API port](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/packages/shared/src/api.ts)，[公开 header context](https://github.com/zai-org/ZCode/blob/aac4755666d09fdcd70272fcf063c077a639015f/packages/shared/src/zcode-source-headers.ts)。

## 最终观察与尚缺条件

官方 OAuthRepo 的实际 active family 为 `zai`。最终 receipt 为 available=true、pending=false、unknown=false、`existing_mid_present=true`、`header_applied=true`，没有返回任何标识原值。耗时 489 ms、exit 0、stderr 0 bytes、新 9-file source window 无漂移。[真实安全投影](../../../.tools/zcode-supported-sdk/existing-mid-phase/account-existing-mid-metadata.json)。

最新离线层共 **68 个 GREEN 检查**：guard 10、官方损坏存储夹具 12、API/投影/诊断 14、构建 define 4、既有/缺失/非法 device-state 28；对应业务 RED 与 GREEN 日志均保留。离线检查只证明本地边界，真实 200 单独证明当前账户可用性。

尚需验证官方 AccountProviderService 向安装 CLI 同步真实 registry/current model、RequestAuthService 私有应用真实 headers、真实模型响应及取消。目录成员不等于执行模型身份；生产、scope、完整 B 仍 false。下一 lane 由 root 授权为零模型目录/会话验证，本报告不据此把 D004/D005/D020 标成完成。
