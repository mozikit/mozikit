# language: zh-CN
@parity
功能: 外部集成和节点管理的 CLI 与桌面业务验收
  背景:
    假如独立的临时工作区和真实配置

  @INT_001 @contract @p2
  场景: 节点源码与 ZIP 往返
    当执行业务操作 "节点源码与 ZIP 往返"，变体为 "default"
    那么应满足：重新加载的源码 schema 版本一致

  @INT_002 @contract @p2
  场景: 非法源码不覆盖
    当执行业务操作 "非法源码不覆盖"，变体为 "default"
    那么应满足：源码和注册信息保持不变

  @INT_003 @gui @qt @p2
  场景: 两端引用统计一致
    当执行业务操作 "两端引用统计一致"，变体为 "default"
    那么应满足：工作流节点 ID 与数量一致

  @INT_004 @contract @p2
  场景: GitHub 节点真实落盘管理
    当执行业务操作 "GitHub 节点真实落盘管理"，变体为 "default"
    那么应满足：导入更新移除只影响目标仓库

  @INT_005 @contract @p2
  场景: 官方更新检查与显式安装
    当执行业务操作 "官方更新检查与显式安装"，变体为 "default"
    那么应满足：检查不安装且指定版本可加载

  @INT_006 @contract @p2
  场景: GitHub 工作流同步往返
    当执行业务操作 "GitHub 工作流同步往返"，变体为 "default"
    那么应满足：保存配置生效且远端与本地模型一致

  @INT_007 @e2e @p1
  场景: 凭据保护与删除
    当执行业务操作 "凭据保护与删除"，变体为 "default"
    那么应满足：配置日志无明文且删除不复活

  @INT_008 @contract @p2
  场景: GitHub 登录与退出
    当执行业务操作 "GitHub 登录与退出"，变体为 "default"
    那么应满足：凭据安全保存且退出后不可用

  @INT_009 @contract @p2
  场景: UV 路径镜像环境管理
    当执行业务操作 "UV 路径镜像环境管理"，变体为 "default"
    那么应满足：真实 argv 使用所存路径镜像和环境

  @INT_010 @contract @p1
  场景大纲: 服务故障保护已装资源
    当执行业务操作 "服务故障保护已装资源"，变体为 "<变体>"
    那么应满足：既有文件和凭据不变且退出失败
    例子:
      | 变体 |
      | github-import |
      | github-update |
      | official-install |
      | sync-push |
      | sync-pull |

  @INT_011 @contract @p2
  场景: MCP Tool 真实执行
    当执行业务操作 "MCP Tool 真实执行"，变体为 "default"
    那么应满足：工具参数结果与下游输入正确且进程回收

  @INT_012 @live @manual @p2
  场景: 外部服务现场验收
    当执行业务操作 "外部服务现场验收"，变体为 "default"
    那么应满足：逐项有现场结果且未配置项不冒充通过
