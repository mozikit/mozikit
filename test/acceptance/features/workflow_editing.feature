# language: zh-CN
@parity
功能: 工作流编辑的 CLI 与桌面业务验收
  背景:
    假如独立的临时工作区和真实配置

  @EDIT_001 @gui @qt @p2
  场景大纲: 属性表单与 CLI 类型一致
    当执行业务操作 "属性表单与 CLI 类型一致"，变体为 "<变体>"
    那么应满足：两端保存相同 JSON 类型与布局
    例子:
      | 变体 |
      | bool |
      | int |
      | float |
      | string |
      | array |
      | object |

  @EDIT_002 @contract @p2
  场景: 节点增改删保留其他数据
    当执行业务操作 "节点增改删保留其他数据"，变体为 "default"
    那么应满足：只删除目标节点和关联连接

  @EDIT_003 @contract @p2
  场景: 连接替换规则一致
    当执行业务操作 "连接替换规则一致"，变体为 "default"
    那么应满足：同一目标端口只保留新连接

  @EDIT_004 @contract @p2
  场景大纲: 非法连接不写文件
    当执行业务操作 "非法连接不写文件"，变体为 "<变体>"
    那么应满足：拒绝且文件字节不变
    例子:
      | 变体 |
      | self |
      | source-port |
      | target-port |
      | missing-node |
      | type |

  @EDIT_005 @contract @p2
  场景: 断开端口保留其他连接
    当执行业务操作 "断开端口保留其他连接"，变体为 "default"
    那么应满足：邻接引用与剩余端口连接一致

  @EDIT_006 @gui @qt @p2
  场景: GUI 重新打开 CLI 工作流
    当执行业务操作 "GUI 重新打开 CLI 工作流"，变体为 "default"
    那么应满足：保存后业务模型与 CLI 相同
