# language: zh-CN
@parity
功能: 配置持久化与持续集成的 CLI 与桌面业务验收
  背景:
    假如独立的临时工作区和真实配置

  @PERSIST_001 @contract @p1
  场景: 占用后有限重试成功
    当执行业务操作 "占用后有限重试成功"，变体为 "default"
    那么应满足：配置有效且无临时文件

  @PERSIST_002 @contract @p1
  场景: 永久错误保留旧配置
    当执行业务操作 "永久错误保留旧配置"，变体为 "default"
    那么应满足：错误传播且旧文件完整

  @PERSIST_003 @e2e @p1
  场景: 多进程更新不丢提交
    当执行业务操作 "多进程更新不丢提交"，变体为 "default"
    那么应满足：所有成功提交的配置和历史可重读

  @PERSIST_004 @contract @p1
  场景: 保存顺序与显式删除
    当执行业务操作 "保存顺序与显式删除"，变体为 "default"
    那么应满足：旧快照不会恢复已删除数据

  @PERSIST_005 @windows @p1
  场景: Windows 原失败路径
    当执行业务操作 "Windows 原失败路径"，变体为 "default"
    那么应满足：真实 Windows 上重复保存无占用错误

  @CI_001 @contract @p2
  场景: 开发分支均有检查
    当执行业务操作 "开发分支均有检查"，变体为 "default"
    那么应满足：Linux 与 Windows 均覆盖 dev 和 main

  @CI_002 @contract @p1
  场景大纲: 发布校验同一 SHA
    当执行业务操作 "发布校验同一 SHA"，变体为 "<变体>"
    那么应满足：只允许全部必需检查绿色的同一 SHA
    例子:
      | 变体 |
      | green |
      | old-sha |
      | windows-failed |
      | linux-missing |
      | running |

  @CI_003 @contract @p2
  场景大纲: 语句分支分别达标
    当执行业务操作 "语句分支分别达标"，变体为 "<变体>"
    那么应满足：门槛分别计算且不能用混合 Cover 代替
    例子:
      | 变体 |
      | 85/75 |
      | 84.9/90 |
      | 95/74.9 |

  @CI_004 @contract @p1
  场景大纲: 验收缺席不是成功
    当执行业务操作 "验收缺席不是成功"，变体为 "<变体>"
    那么应满足：缺少场景步骤平台或证据时验收失败
    例子:
      | 变体 |
      | undefined |
      | empty |
      | skip |
      | help-only |
      | packaged-missing |
      | live-missing |

  @CI_005 @contract @p2
  场景: 性能独立度量
    当执行业务操作 "性能独立度量"，变体为 "default"
    那么应满足：性能无 coverage 且平台任务正确
