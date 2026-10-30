# language: zh-CN
@parity
功能: Windows 桌面发行版的 CLI 与桌面业务验收
  背景:
    假如独立的临时工作区和真实配置

  @DIST_001 @windows @packaged @p2
  场景大纲: 任意目录运行成品 CLI
    当执行业务操作 "任意目录运行成品 CLI"，变体为 "<变体>"
    那么应满足：中文输出和 JSON 正确且不启动 GUI
    例子:
      | 变体 |
      | msi |
      | portable |

  @DIST_002 @windows @packaged @p2
  场景大纲: 成品录制依赖安装
    当执行业务操作 "成品录制依赖安装"，变体为 "<变体>"
    那么应满足：无开发 Python 仍使用真实工具解释器
    例子:
      | 变体 |
      | msi |
      | portable |

  @DIST_003 @windows @packaged @p2
  场景: portable PATH 注册隔离
    当执行业务操作 "portable PATH 注册隔离"，变体为 "default"
    那么应满足：只改变自己用户 PATH 项

  @DIST_004 @windows @packaged @p2
  场景: MSI PATH 所有权
    当执行业务操作 "MSI PATH 所有权"，变体为 "default"
    那么应满足：不移除安装器管理的 PATH 项

  @DIST_005 @windows @packaged @p2
  场景: 成品两端工作流历史共享
    当执行业务操作 "成品两端工作流历史共享"，变体为 "default"
    那么应满足：同一工作区配置和报告可读取

  @DIST_006 @windows @packaged @p2
  场景: 更新检查与确认语义
    当执行业务操作 "更新检查与确认语义"，变体为 "default"
    那么应满足：检查不安装且明确确认后才交接

  @DIST_007 @windows @packaged @p2
  场景: 更新包校验失败
    当执行业务操作 "更新包校验失败"，变体为 "default"
    那么应满足：安装器不启动且用户数据不变

  @DIST_008 @windows @packaged @live @manual @p2
  场景大纲: 真实 Chrome 录制往返
    当执行业务操作 "真实 Chrome 录制往返"，变体为 "<变体>"
    那么应满足：实际录制回填且 GUI 可执行
    例子:
      | 变体 |
      | msi |
      | portable |
