# language: zh-CN
@parity
功能: Playwright 脚本与录制工具的 CLI 与桌面业务验收
  背景:
    假如独立的临时工作区和真实配置

  @PW_001 @gui @qt @p2
  场景: 脚本与参数 schema 等价
    当执行业务操作 "脚本与参数 schema 等价"，变体为 "default"
    那么应满足：两端参数一致且保留仍存在的值

  @PW_002 @contract @p2
  场景: 查看校验重扫清空
    当执行业务操作 "查看校验重扫清空"，变体为 "default"
    那么应满足：只读操作不写文件且清空移除参数

  @PW_003 @contract @p2
  场景大纲: 无效脚本不覆盖
    当执行业务操作 "无效脚本不覆盖"，变体为 "<变体>"
    那么应满足：原始配置字节保持不变
    例子:
      | 变体 |
      | syntax |
      | missing |
      | wrong-type |
      | empty |

  @PW_004 @contract @p2
  场景大纲: 安装使用独立解释器
    当执行业务操作 "安装使用独立解释器"，变体为 "<变体>"
    那么应满足：从不把 GUI 或 CLI EXE 当 Python
    例子:
      | 变体 |
      | source |
      | msi |
      | portable |

  @PW_005 @contract @p2
  场景: 成功录制经校验保存
    当执行业务操作 "成功录制经校验保存"，变体为 "default"
    那么应满足：工具参数正确且写回合法脚本

  @PW_006 @contract @p1
  场景大纲: 录制失败保留原配置
    当执行业务操作 "录制失败保留原配置"，变体为 "<变体>"
    那么应满足：进程清理且原文件不变
    例子:
      | 变体 |
      | interrupt |
      | start |
      | exit |
      | missing |
      | empty |
      | syntax |

  @PW_007 @gui @qt @p2
  场景: 两端发现相同工具环境
    当执行业务操作 "两端发现相同工具环境"，变体为 "default"
    那么应满足：中文空格路径可用且不受 PATH 误导

  @PW_008 @contract @p1
  场景大纲: 安装失败保护旧环境
    当执行业务操作 "安装失败保护旧环境"，变体为 "<变体>"
    那么应满足：原文件和可用旧工具环境不变
    例子:
      | 变体 |
      | uv |
      | network |
      | write |
