# language: zh-CN
@parity
功能: 显式复用上游结果的 CLI 与桌面业务验收
  背景:
    假如独立的临时工作区和真实配置

  @CACHE_001 @contract @p2
  场景: 默认是新运行
    当执行业务操作 "默认是新运行"，变体为 "default"
    那么应满足：上游和目标每次执行

  @CACHE_002 @contract @p2
  场景: 显式复用仅跳过上游
    当执行业务操作 "显式复用仅跳过上游"，变体为 "default"
    那么应满足：上游一次目标两次且有来源记录

  @CACHE_003 @gui @qt @p2
  场景: GUI 与 CLI 复用语义一致
    当执行业务操作 "GUI 与 CLI 复用语义一致"，变体为 "default"
    那么应满足：目标重跑且有效上游复用

  @CACHE_004 @contract @p1
  场景大纲: 不兼容快照整次拒绝
    当执行业务操作 "不兼容快照整次拒绝"，变体为 "<变体>"
    那么应满足：不执行任何节点且不修改缓存
    例子:
      | 变体 |
      | identity |
      | graph |
      | input |
      | config |
      | source |
      | version |
      | environment |
      | artifact |
      | credential |

  @CACHE_005 @contract @p2
  场景: 目标配置可改变
    当执行业务操作 "目标配置可改变"，变体为 "default"
    那么应满足：上游复用且目标用新配置运行

  @CACHE_006 @contract @p1
  场景大纲: 不可恢复来源不回退
    当执行业务操作 "不可恢复来源不回退"，变体为 "<变体>"
    那么应满足：失败且不重跑有副作用的上游
    例子:
      | 变体 |
      | unknown |
      | failed |
      | stopped |
      | display |
      | missing |
      | lossy |

  @CACHE_007 @contract @p2
  场景: 快照无损且受保护
    当执行业务操作 "快照无损且受保护"，变体为 "default"
    那么应满足：大输出和类型完整且快照权限受保护
