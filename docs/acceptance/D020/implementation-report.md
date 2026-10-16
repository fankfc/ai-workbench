# D020 本地垂直集成与真实阻塞

测试专用scenario_driver接受CASE、--root、--options，stdout输出单个UTF-8 JSON对象；只允许明确fake模式。外部B执行和A判断使用固定响应，实际API、SQLite、不可变blob、Windows进程、验证器、版本图、用量、审批和公开事件均在本地运行。

代码场景实际执行Python；论文场景读取CSV并复算；文档场景核对固定来源、数字和名称；综合场景执行分析代码生成汇总JSON及SVG，并独立核对数据、结果和图表。综合依赖图包含data、analysis、result、figure、answer五节点，报告依赖真实result和figure版本。

16个本地集成用例覆盖四域正常路径、返修、补证、取消迟到、服务重建、旧审批、重复通知、起步前预算、返修后预算、连接失败、Claude语言门禁和上游改版。预算后返修实际消耗45 token、三次fixture调用、两个候选，下一次A调用被阻止。重建服务场景已保存真实候选和检查结果，保留原请求及未知用量且不新增调用；该场景是工厂重建，真正OS崩溃窗口另由D010/D012子进程测试覆盖。

最终whole测试记录和最终四域报告以backend-full-test.log、backend-junit.xml及本目录vertical-report.json为准。request-ledger.json来自每个实际测试数据库的账本，不是按预期填写的统计。独立测量记录见remaining-vertical-postfix.json；它带其复核窗口的源码哈希。最终新版本再由root完整回归验证，不能用旧哈希窗口替代新验证。

D004 Claude未登录，D005 ZCode未选择实际模型，必需真实A/B贯通没有通过。D006允许记录路线决策完成，但GPT仍disabled，当前真实工具任务被策略拒绝且model_id未知。显式real_provider测试因此跳过且不再启动模型。D020卡片保持blocked，local_backend_verified可为true，real_handoff_complete保持false。

后续模块按backend-handoff.json及docs/runbooks/backend-operations.md接入。完整Claude英文上下文、A原件来源、中文翻译QA、渲染、正式双语bundle和GUI仍待实施；当前不能发布正式Claude交付或声称优化资格。
