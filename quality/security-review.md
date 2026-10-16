# 阶段三安全检查

本地自动检查运行真实鉴权、诊断导出、附件作用域、路径解析与公开投影。证据按最终源码版本保存到 artifacts/qa/D047。

Electron IPC、DOM 注入及 MutationObserver 检查由 security-boundary.spec.ts 记录。该结果必须独立核验，后端场景不会虚构 renderer 执行次数。

完整目录联接/符号链接攻击矩阵与人工安全评审未齐全；真实模型授权资格沿用第一、二阶段阻塞项，不能授予正式发布资格。
