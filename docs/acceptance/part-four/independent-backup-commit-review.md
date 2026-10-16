# Windows 受管备份目录提交独立复核

日期：2026-10-15。只读审查 `storage/directory_commit.py`、`storage/backup.py`、`storage/restore.py`、`api/backups.py` 及新增定向测试；没有改动产品源码、测试或执行全量测试。

## 结论

本次限定范围内没有发现已复现阻断项。实现只重试本地目录 rename，不重复数据库快照、文件复制、模型或其他外部请求。

- `directory_commit.py` 严格限定 `.pending-` 后 32 位小写十六进制名称；每次 rename 前重新核对原始绝对路径、同父关系、祖先无 reparse、源及父目录身份、目标不存在。
- 仅 Windows `winerror` 5/32/33 可重试；最多五次 rename、四次固定等待，累计等待 0.30 秒。该数字限制重试与主动等待，不是对操作系统单次 I/O 时长的保证。其他错误立即失败，没有跨卷搬移或覆盖 fallback。
- `DirectoryCommitBusy` 继承 `DirectoryCommitBlocked`；create/import/restore 的专用 except 在通用清理分支之前重抛，因此持续占用或所有权变化时保留 staging，不以递归删除掩盖原错误。
- API 对 busy 返回固定中文可重试说明，不暴露原始异常；恢复失败会解除 storage_frozen，既有目录和备份引用不被替换。

## 独立实际探针

使用新脚本 `independent-directory-commit-probe.py` 调用实际 helper，Windows CreateFileW 故意不授予 FILE_SHARE_DELETE。仅在本次自有临时树内制造占用和路径变化，未重跑实现代理的测试集。结果保存在同名 `.json`：

| 情形 | 实际 rename 次数 | 结果 |
| --- | ---: | --- |
| 首次共享锁失败后释放句柄 | 2 | 同一路径提交成功，快照原字节保持 |
| 持续持有句柄 | 5 | DirectoryCommitBusy，pending 与原字节保留、目标未创建 |
| 首次失败后的等待中出现目标 | 1 | DirectoryCommitBlocked，现有目标和 pending 均保持 |
| 首次失败后的等待中源目录被同名替换 | 1 | DirectoryCommitBlocked，旧源和替换目录均保持，目标未创建 |

四个情形均通过；所有实际句柄均关闭，临时树已移除，旧 live 文件保持原字节；模型调用为零。被测 helper SHA256：`2540318d7c65bf886088f6cf32719ca75f6efbba84d8726dc5c12ac22f5cc28f`。

## 结论边界

真实句柄探针说明共享删除限制能产生此次同类 Windows 错误，不能证明最终回归那一次的具体占用者。实现是预检及重试边界复核，不是所有平台上抗 TOCTOU 的原子 no-replace 操作，也不是对同用户恶意进程的操作系统隔离。最终完整回归与真实提供方、人工验收仍由 root 的对应证据决定。
