"""
节点注册表
管理所有节点的元数据、源代码和修改状态
"""

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from src.core.exceptions import ErrorCode, LocalFlowError
from src.core.log_manager import get_logger

from .code_safety import review_code_safety, safety_review_to_warning

logger = get_logger("node_registry")


class NodeSource(Enum):
    """节点来源枚举"""

    OFFICIAL = "official"  # 官方节点
    GITHUB = "github"  # GitHub社区节点
    ENTERPRISE = "enterprise"  # 企业内网节点
    CUSTOM = "custom"  # 用户自定义节点


# 节点来源显示信息
NODE_SOURCE_INFO = {
    NodeSource.OFFICIAL: {"name": "官方", "color": "#4CAF50"},
    NodeSource.GITHUB: {"name": "GitHub", "color": "#6e5494"},
    NodeSource.ENTERPRISE: {"name": "内网", "color": "#FF9800"},
    NodeSource.CUSTOM: {"name": "自定义", "color": "#2196F3"},
}


@dataclass
class NodeDefinition:
    """节点定义"""

    node_type: str  # 节点类型标识
    name: str  # 显示名称
    description: str  # 描述
    source: NodeSource  # 来源
    category: str  # 分类
    source_code: str  # 源代码（execute函数）
    config_schema: Dict  # 配置项定义
    modified: bool = False  # 是否被用户修改
    repo_url: str = ""  # 来源仓库URL（GitHub/内网节点）
    metadata: Dict = field(default_factory=dict)  # 附加元数据
    dependencies: List[str] = field(default_factory=list)  # pip 依赖包列表
    version: str = "1.0.0"  # 节点版本
    input_schema: Dict = field(default_factory=dict)  # 输入变量定义
    output_schema: Dict = field(default_factory=dict)  # 输出变量定义
    input_example: Dict = field(default_factory=dict)  # 输入样例数据
    output_example: Dict = field(default_factory=dict)  # 输出样例数据
    examples: List[Dict] = field(
        default_factory=list
    )  # 使用示例列表, 每项含 title 和 config
    registrations: Dict = field(default_factory=dict)  # 扩展点注册信息（from node.json）


class NodeRegistry:
    """节点注册表"""

    NODE_DIRS = [
        "custom_nodes",
        "external_nodes/github",
        "external_nodes/enterprise",
        "modified_nodes",
        "official_nodes",
    ]

    def __init__(self):
        self._nodes: Dict[str, NodeDefinition] = {}
        self._user_data_dir = Path("user_data")
        self._ensure_dirs()
        self._migrate_legacy_nodes()
        self._load_official_nodes()
        self._load_external_nodes()

    def _ensure_dirs(self):
        """确保所有节点类型的目录在启动时存在"""
        for subdir in self.NODE_DIRS:
            (self._user_data_dir / subdir).mkdir(parents=True, exist_ok=True)

    def _migrate_legacy_nodes(self):
        """迁移旧结构节点到新版本结构"""
        from .node_version_manager import NodeVersionManager

        # 迁移官方节点
        official_dir = self._user_data_dir / "official_nodes"
        if official_dir.exists():
            vm = NodeVersionManager(official_dir)
            migrated = vm.migrate_all_legacy_nodes()
            if migrated:
                logger.info("迁移官方节点: %s", migrated)

        # 迁移自定义节点
        custom_dir = self._user_data_dir / "custom_nodes"
        if custom_dir.exists():
            vm = NodeVersionManager(custom_dir)
            migrated = vm.migrate_all_legacy_nodes()
            if migrated:
                logger.info("迁移自定义节点: %s", migrated)

    def _load_registrations_for_node(self, node_type: str, registrations: dict, version_dir: Path):
        """解析 node.json 中的 registrations，注册扩展点"""
        if not registrations:
            return
        from .node_extension_registries import load_registrations_from_json

        load_registrations_from_json(node_type, registrations, str(version_dir))

    def _apply_schema_builder(self, node_type: str, config_schema: dict) -> dict:
        """使用 SchemaBuilder 替换静态 config_schema（若注册）"""
        from .node_extension_registries import schema_builders

        sb = schema_builders.get(node_type)
        if sb:
            return sb([])
        return config_schema

    def _load_official_nodes(self):
        """从 official_nodes 目录加载官方节点（当前版本）

        加载策略：
        1. 优先从 user_data/official_nodes/ 加载（用户已安装/更新的版本）
        2. 回退到 bundled official_nodes/ 快照（打包时自带）
        3. 若目录均不存在，记录警告但不硬编码 fallback（节点已外置到仓库）
        """
        from .node_repo_manager import NodeRepoManager
        from .node_version_manager import NodeVersionManager

        repo_mgr = NodeRepoManager(self._user_data_dir)
        official_dir = repo_mgr.active_dir

        if not official_dir.exists():
            logger.warning("官方节点目录不存在: %s", official_dir)
            return

        # 使用版本管理器加载
        vm = NodeVersionManager(official_dir)

        # 获取所有节点
        manifest_path = official_dir / "manifest.json"
        node_types = []
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                    nodes_data = manifest.get("nodes", [])
                    if isinstance(nodes_data, list):
                        node_types = nodes_data
                    elif isinstance(nodes_data, dict):
                        node_types = list(nodes_data.keys())
            except Exception:
                pass

        if not node_types:
            for d in official_dir.iterdir():
                if d.is_dir():
                    node_types.append(d.name)

        for node_type in node_types:
            # 解析当前版本
            current_version = vm.resolve_current_version(node_type)

            # 获取文件路径
            node_json = vm.get_node_json_path(node_type, current_version)
            if not node_json.exists():
                continue

            try:
                with open(node_json, "r", encoding="utf-8") as f:
                    config = json.load(f)

                source_code = ""
                entry_file = vm.get_node_py_path(node_type, current_version)
                if entry_file.exists():
                    with open(entry_file, "r", encoding="utf-8") as sf:
                        source_code = sf.read()

                metadata = config.get("metadata", {})
                config_schema = config.get("config_schema", {})
                registrations = config.get("registrations", {})

                # 解析注册信息并注册扩展点
                version_dir = vm.get_version_dir(node_type, current_version)
                self._load_registrations_for_node(node_type, registrations, version_dir)

                # 使用 SchemaBuilder 替换静态 config_schema（若注册）
                config_schema = self._apply_schema_builder(node_type, config_schema)

                node_def = NodeDefinition(
                    node_type=config.get("node_type", node_type),
                    name=config.get("name", node_type),
                    description=config.get("description", ""),
                    source=NodeSource.OFFICIAL,
                    category=config.get("category", "官方"),
                    source_code=source_code,
                    config_schema=config_schema,
                    metadata=metadata,
                    dependencies=config.get("dependencies", []),
                    version=config.get("version", current_version or "1.0.0"),
                    input_schema=config.get("input_schema", {}),
                    output_schema=config.get("output_schema", {}),
                    input_example=config.get("input_example", {}),
                    output_example=config.get("output_example", {}),
                    examples=config.get("examples", []),
                    registrations=registrations,
                )

                modified_file = (
                    self._user_data_dir / "modified_nodes" / f"{node_def.node_type}.py"
                )
                if modified_file.exists():
                    with open(modified_file, "r", encoding="utf-8") as mf:
                        node_def.source_code = mf.read()
                    node_def.modified = True

                self._nodes[node_def.node_type] = node_def

                # 为缺少安全审查的官方节点补充审查
                self._ensure_safety_warning(node_def)

            except Exception as e:
                logger.error("加载官方节点失败 %s: %s", node_type, e)

    def _scan_node_dir(self, vm, source_name, node_dir):
        """扫描并加载单个节点目录（支持平铺和嵌套两种结构）"""
        from .node_version_manager import NodeVersionManager
        node_type = node_dir.name

        # 如果目录名不含下划线且内部有子目录，可能是 owner/repo 路径，递归扫描
        if "_" not in node_type:
            has_sub_dirs = any(d.is_dir() for d in node_dir.iterdir())
            if has_sub_dirs:
                loaded_any = False
                for sub_dir in node_dir.iterdir():
                    if sub_dir.is_dir():
                        sub_vm = NodeVersionManager(sub_dir)
                        for candidate_dir in sub_dir.iterdir():
                            if candidate_dir.is_dir():
                                if self._scan_single_node(sub_vm, source_name, candidate_dir):
                                    loaded_any = True
                return loaded_any

        return self._scan_single_node(vm, source_name, node_dir)

    def _scan_single_node(self, vm, source_name, node_dir):
        """加载单个节点（从 node_json 读取并注册）"""
        node_type = node_dir.name
        current_version = vm.resolve_current_version(node_type)
        node_json = vm.get_node_json_path(node_type, current_version)
        if not node_json.exists():
            return False

        try:
            with open(node_json, "r", encoding="utf-8") as f:
                config = json.load(f)

            source_code = ""
            entry_file = vm.get_node_py_path(node_type, current_version)
            if entry_file.exists():
                with open(entry_file, "r", encoding="utf-8") as sf:
                    source_code = sf.read()

            registrations = config.get("registrations", {})
            # version_dir 用于加载 registrations 中的 Python 模块文件
            # 无版本时，version_dir 就是节点目录本身
            if current_version:
                version_dir = vm.get_version_dir(node_type, current_version)
            else:
                version_dir = node_dir
            self._load_registrations_for_node(node_type, registrations, version_dir)

            node_def = NodeDefinition(
                node_type=config.get("node_type", node_type),
                name=config.get("name", node_type),
                description=config.get("description", ""),
                source=NodeSource(source_name),
                category=config.get("category", "外部"),
                source_code=source_code,
                config_schema=config.get("config_schema", {}),
                repo_url=config.get("repo_url", ""),
                metadata=config.get("metadata", {}),
                dependencies=config.get("dependencies", []),
                version=config.get("version", current_version or "1.0.0"),
                input_schema=config.get("input_schema", {}),
                output_schema=config.get("output_schema", {}),
                input_example=config.get("input_example", {}),
                output_example=config.get("output_example", {}),
                examples=config.get("examples", []),
                registrations=registrations,
            )

            self._nodes[node_def.node_type] = node_def
            self._ensure_safety_warning(node_def)
            return True
        except Exception as e:
            logger.error("加载外部节点失败 %s: %s", node_type, e)
            return False

    def _load_external_nodes(self):
        """加载外部和下载的节点（支持多版本结构）"""
        # 加载自定义节点
        from src.core.custom_node_manager import CustomNodeManager

        manager = CustomNodeManager(self._user_data_dir)
        custom_nodes = manager.load_all_custom_nodes()
        for node in custom_nodes:
            self._nodes[node.node_type] = node

        # 加载外部下载的节点 (GitHub/Enterprise)
        external_dir = self._user_data_dir / "external_nodes"
        if not external_dir.exists():
            return

        # 迁移旧结构的外部节点
        from .node_version_manager import NodeVersionManager

        for source_dir in external_dir.iterdir():
            if not source_dir.is_dir():
                continue
            vm = NodeVersionManager(source_dir)
            migrated = vm.migrate_all_legacy_nodes()
            if migrated:
                logger.info("迁移 %s 节点: %s", source_dir.name, migrated)

        # 加载外部节点（新结构），支持平铺和嵌套两种布局
        for source_dir in external_dir.iterdir():
            if not source_dir.is_dir():
                continue

            vm = NodeVersionManager(source_dir)
            source_name = source_dir.name

            # 遍历所有候选节点目录
            for node_dir in source_dir.iterdir():
                if not node_dir.is_dir():
                    continue

                self._scan_node_dir(vm, source_name, node_dir)

    def _ensure_safety_warning(self, node_def: NodeDefinition):
        """为缺少安全审查的节点补充 safety_warning（仅在内存中，不写回磁盘）

        对于在安全审查功能上线之前下载的节点，其 metadata 中可能没有
        safety_warning 字段。此方法在加载时补充审查，确保执行门控生效。
        """
        if not node_def.source_code:
            return

        # 官方节点（未修改）默认受信任，不强制审查
        if node_def.source == NodeSource.OFFICIAL and not node_def.modified:
            return

        # 已有 safety_warning 的节点无需重复审查
        if node_def.metadata.get("safety_warning"):
            return

        safety_result = review_code_safety(node_def.source_code)
        if safety_result.has_risks:
            node_def.metadata["safety_warning"] = safety_review_to_warning(
                safety_result
            )
            if safety_result.risk_level == "high":
                logger.warning(
                    "节点 %s (%s) 包含高风险代码: %s",
                    node_def.node_type,
                    node_def.source.value,
                    safety_result.high_risks,
                )

    def register_external_node(self, node_def: NodeDefinition) -> bool:
        """注册外部节点"""
        self._nodes[node_def.node_type] = node_def
        return True

    def unregister_node(self, node_type: str) -> bool:
        """注销节点"""
        if node_type in self._nodes:
            del self._nodes[node_type]
            return True
        return False

    # === 查询方法 ===

    def list_node_types(self) -> List[str]:
        """获取所有已注册节点的 node_type 字符串列表"""
        return list(self._nodes.keys())

    def get_all_nodes(self) -> List[dict]:
        """获取所有节点（转换为字典格式供UI使用）"""
        result = []
        for node in self._nodes.values():
            result.append(self._node_to_dict(node))
        return result

    def get_node(self, node_type) -> Optional[NodeDefinition]:
        """获取指定节点 (支持枚举 or 字符串)"""
        # 直接尝试获取
        node = self._nodes.get(node_type)
        if node:
            return node

        # 如果是字符串，尝试匹配枚举键
        if isinstance(node_type, str):
            for key, val in self._nodes.items():
                if hasattr(key, "value") and key.value == node_type:
                    return val

        # 如果是枚举，尝试直接用其值字符串匹配
        if hasattr(node_type, "value"):
            return self._nodes.get(node_type.value)

        return None

    def get_nodes_by_source(self, source: NodeSource) -> List[NodeDefinition]:
        """按来源获取节点"""
        return [n for n in self._nodes.values() if n.source == source]

    def _node_to_dict(self, node: NodeDefinition) -> dict:
        """将NodeDefinition转换为字典"""
        return {
            "type": node.node_type,
            "type_str": node.node_type,
            "name": node.name,
            "description": node.description,
            "source": node.source,
            "category": node.category,
            "modified": node.modified,
            "color": NODE_SOURCE_INFO[node.source]["color"],
            "repo_url": node.repo_url,
            "metadata": node.metadata,
            "dependencies": node.dependencies,
            "version": node.version,
            "input_schema": node.input_schema,
            "output_schema": node.output_schema,
            "input_example": node.input_example,
            "output_example": node.output_example,
            "examples": node.examples,
        }

    # === 源代码管理 ===

    def get_source_code(self, node_type) -> str:
        """获取节点执行用源代码"""
        node = self.get_node(node_type)
        if node:
            return node.source_code
        return ""

    def get_display_source_code(self, node_type) -> str:
        """获取属性面板应展示的源代码"""
        node = self.get_node(node_type)
        if not node:
            return ""

        if node.source == NodeSource.CUSTOM:
            from src.core.custom_node_manager import CustomNodeManager

            manager = CustomNodeManager(self._user_data_dir)
            return manager.get_display_source(node.node_type)

        return node.source_code

    def save_modified_source(self, node_type: str, source_code: str) -> bool:
        """保存修改后的源代码"""
        node = self._nodes.get(node_type)
        if not node:
            return False

        # 更新内存中的源代码
        node.source_code = source_code

        if node.source == NodeSource.CUSTOM:
            # 自定义节点：直接保存到其目录
            from src.core.custom_node_manager import CustomNodeManager

            manager = CustomNodeManager(self._user_data_dir)
            return manager.save_node(node_type, source_code)
        else:
            # 官方或其他节点：作为修改覆盖保存
            node.modified = True
            modified_dir = self._user_data_dir / "modified_nodes"
            modified_dir.mkdir(parents=True, exist_ok=True)

            modified_file = modified_dir / f"{node_type}.py"
            with open(modified_file, "w", encoding="utf-8") as f:
                f.write(source_code)

            return True

    def save_display_source(self, node_type: str, source_code: str) -> bool:
        """保存属性面板编辑的源代码"""
        node = self._nodes.get(node_type)
        if not node:
            return False

        if node.source == NodeSource.CUSTOM:
            from src.core.custom_node_manager import CustomNodeManager

            manager = CustomNodeManager(self._user_data_dir)
            success = manager.save_display_source(node_type, source_code)
            if success:
                reloaded = manager._load_node_from_dir(
                    manager.custom_nodes_dir / node_type
                )
                if reloaded:
                    self._nodes[node_type] = reloaded
            return success

        return self.save_modified_source(node_type, source_code)

    def rescan_playwright_node(self, node_type: str) -> dict:
        """重新扫描 Playwright 节点的脚本参数"""
        node = self._nodes.get(node_type)
        if not node:
            raise LocalFlowError(ErrorCode.NODE_NOT_FOUND, f"节点不存在: {node_type}")

        from src.core.custom_node_manager import CustomNodeManager

        manager = CustomNodeManager(self._user_data_dir)
        result = manager.rescan_playwright_node(node_type)
        reloaded = manager._load_node_from_dir(manager.custom_nodes_dir / node_type)
        if reloaded:
            self._nodes[node_type] = reloaded
        return result

    def reset_to_original(self, node_type: str) -> bool:
        """重置为原始源代码"""
        node = self._nodes.get(node_type)
        if not node:
            return False

        modified_file = self._user_data_dir / "modified_nodes" / f"{node_type}.py"
        if modified_file.exists():
            modified_file.unlink()

        node.modified = False

        if node.source == NodeSource.OFFICIAL:
            from .node_repo_manager import NodeRepoManager

            repo_mgr = NodeRepoManager(self._user_data_dir)
            official_dir = repo_mgr.active_dir
            node_dir = official_dir / node_type
            entry_file = node_dir / "node.py"
            if entry_file.exists():
                with open(entry_file, "r", encoding="utf-8") as f:
                    node.source_code = f.read()
                return True

        return True

    def is_modified(self, node_type: str) -> bool:
        """检查节点是否被修改"""
        node = self._nodes.get(node_type)
        return node.modified if node else False

    def get_node_info(self, node_type) -> dict:
        """获取节点显示信息"""
        node = self.get_node(node_type)
        # 如果按 node_type 没找到，尝试按 name 匹配
        if not node:
            for n in self._nodes.values():
                if n.name == node_type:
                    node = n
                    break
        if node:
            return {
                "name": node.name,
                "source": node.source,
                "source_info": NODE_SOURCE_INFO[node.source],
            }
        # 返回默认信息
        return {
            "name": node_type,
            "source": NodeSource.OFFICIAL,
            "source_info": NODE_SOURCE_INFO[NodeSource.OFFICIAL],
        }

    def build_default_config(self, node_type) -> dict:
        """基于节点 schema 构建默认配置"""
        node = self.get_node(node_type)
        if not node:
            return {}

        config = {}
        for key, field_schema in (node.config_schema or {}).items():
            if isinstance(field_schema, dict) and "default" in field_schema:
                config[key] = field_schema.get("default")

        # 有 BootstrapHook 的节点（如 Playwright）需要 script_source 和 param_schema
        from .node_extension_registries import bootstrap_hooks

        if bootstrap_hooks.has(node_type):
            config["script_source"] = ""
            config["param_schema"] = json.loads(
                json.dumps(node.config_schema or {}, ensure_ascii=False)
            )

        return config


# 全局单例
_registry_instance = None


def get_registry() -> NodeRegistry:
    """获取全局节点注册表实例"""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = NodeRegistry()
    return _registry_instance
