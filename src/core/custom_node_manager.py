"""
自定义节点管理器
管理用户创建的本地节点，支持多版本共存

存储结构:
    custom_nodes/
    └── my_custom_node/
        ├── versions/
        │   ├── 1.0.0/
        │   │   ├── node.json
        │   │   └── node.py
        │   └── 2.0.0/
        │       ├── node.json
        │       └── node.py
        └── current -> versions/2.0.0
"""

import ast
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.exceptions import ErrorCode, LocalFlowError
from src.core.log_manager import get_logger

from .node_version_manager import LocalManifest, NodeVersionManager, VersionInfo
from .playwright_node_utils import (
    build_playwright_config_schema,
    build_playwright_wrapper_source,
    extract_playwright_params,
    is_playwright_node,
)

logger = get_logger("custom_node_manager")


class CustomNodeManager:
    """自定义节点管理器 - 支持多版本"""

    NODE_TEMPLATE = '''def execute(self, input_data: dict) -> dict:
    """
    执行节点逻辑

    Args:
        input_data: 输入数据字典，包含上游节点的输出

    Returns:
        输出数据字典，将传递给下游节点
    """
    # 获取配置
    # param1 = self.config.get("param1", "")

    # 获取输入
    # input_val = input_data.get("input_key", None)

    # TODO: 在此处编写逻辑
    result = {}

    return {**input_data, **result}
'''

    def __init__(self, user_data_dir: Path):
        self.user_data_dir = user_data_dir
        self.custom_nodes_dir = user_data_dir / "custom_nodes"
        self.custom_nodes_dir.mkdir(parents=True, exist_ok=True)
        self._version_mgr = NodeVersionManager(self.custom_nodes_dir)

    @property
    def version_manager(self) -> NodeVersionManager:
        return self._version_mgr

    def load_all_custom_nodes(self) -> List:
        """从本地目录加载所有自定义节点（当前版本）"""
        from .node_registry import NodeDefinition, NodeSource

        nodes = []

        if not self.custom_nodes_dir.exists():
            return nodes

        for node_dir in self.custom_nodes_dir.iterdir():
            if not node_dir.is_dir():
                continue

            # 迁移旧结构
            if self._version_mgr.needs_migration(node_dir.name):
                self._version_mgr.migrate_legacy_node(node_dir.name)

            node_def = self._load_node_from_dir(node_dir)
            if node_def:
                nodes.append(node_def)

        return nodes

    def _load_node_from_dir(self, node_dir: Path, version: Optional[str] = None):
        """从指定目录加载节点定义"""
        from .node_registry import NodeDefinition, NodeSource

        node_type = node_dir.name

        # 解析版本
        if version is None:
            version = self._version_mgr.resolve_current_version(node_type)

        # 获取文件路径
        node_json = self._version_mgr.get_node_json_path(node_type, version)
        if not node_json.exists():
            return None

        try:
            with open(node_json, "r", encoding="utf-8") as f:
                config = json.load(f)

            node_def = NodeDefinition(
                node_type=config.get("node_type", node_type),
                name=config.get("name", node_type),
                description=config.get("description", ""),
                source=NodeSource.CUSTOM,
                category=config.get("category", "自定义"),
                source_code="",
                config_schema=config.get("config_schema", {}),
                metadata=config.get("metadata", {}),
                dependencies=config.get("dependencies", []),
                version=config.get("version", version or "1.0.0"),
                input_schema=config.get("input_schema", {}),
                output_schema=config.get("output_schema", {}),
                input_example=config.get("input_example", {}),
                output_example=config.get("output_example", {}),
                examples=config.get("examples", []),
            )

            entry_file = self._version_mgr.get_node_py_path(node_type, version)
            if entry_file.exists():
                with open(entry_file, "r", encoding="utf-8") as sf:
                    node_def.source_code = sf.read()

            return node_def
        except Exception as e:
            logger.error("加载节点失败 %s: %s", node_dir, e)
            return None

    def create_node(
        self,
        name: str,
        description: str,
        category: str = "自定义",
        version: str = "1.0.0",
    ) -> Optional[Any]:
        """创建新节点"""
        from .node_registry import NodeDefinition, NodeSource

        node_type = self._build_node_type(name)
        return self._create_node_definition(
            node_type=node_type,
            name=name,
            description=description,
            category=category,
            source_code=self.NODE_TEMPLATE,
            config_schema={},
            dependencies=[],
            version=version,
        )

    def create_playwright_node(
        self,
        name: str,
        description: str,
        script_source: str,
        category: str = "浏览器自动化",
        version: str = "1.0.0",
    ) -> Optional[Any]:
        """创建 Playwright 脚本节点"""
        self.validate_python_source(script_source)

        node_type = self._build_node_type(name)
        target_script_path = (
            self.custom_nodes_dir / node_type / "versions" / version / "script.py"
        )
        param_names = extract_playwright_params(script_source)
        config_schema = build_playwright_config_schema(param_names)
        metadata = {
            "node_kind": "playwright_script",
            "script_file": "script.py",
            "param_names": param_names,
        }

        return self._create_node_definition(
            node_type=node_type,
            name=name,
            description=description,
            category=category,
            source_code=build_playwright_wrapper_source(
                target_script_path, param_names
            ),
            config_schema=config_schema,
            dependencies=["playwright"],
            version=version,
            metadata=metadata,
            additional_files={"script.py": script_source},
        )

    def create_generated_node(
        self,
        name: str,
        description: str,
        source_code: str,
        config_schema: dict = None,
        dependencies: list = None,
        category: str = "AI 生成",
        version: str = "1.0.0",
    ) -> Optional[Any]:
        """创建 AI 生成节点（含安全审查）"""
        from .code_safety import review_code_safety, safety_review_to_warning
        from .node_registry import NodeDefinition, NodeSource

        is_valid, error_msg = self.validate_node(source_code)
        if not is_valid:
            raise LocalFlowError(ErrorCode.NODE_VALIDATION_FAILED, error_msg)

        safety_review = review_code_safety(source_code)

        if safety_review.high_risks:
            risk_detail = "; ".join(safety_review.high_risks)
            raise LocalFlowError(
                ErrorCode.CODE_SAFETY_REJECTED,
                f"代码安全审查未通过，检测到高风险操作: {risk_detail}。拒绝创建此节点。"
            )

        node_type = self._build_node_type(name)

        effective_metadata = {}
        if safety_review.risk_level in ("medium", "low"):
            effective_metadata["safety_warning"] = {
                "risk_level": safety_review.risk_level,
                "risks": safety_review.all_risks(),
            }
            logger.warning(
                "AI 生成节点 %s 存在安全风险: %s",
                node_type,
                safety_review.all_risks(),
            )

        return self._create_node_definition(
            node_type=node_type,
            name=name,
            description=description,
            category=category,
            source_code=source_code,
            config_schema=config_schema or {},
            dependencies=dependencies or [],
            version=version,
            metadata=effective_metadata if effective_metadata else None,
        )

    def _build_node_type(self, name: str) -> str:
        """基于节点名称生成唯一 node_type"""
        import re

        node_type = re.sub(r"[^\w]", "_", name.lower())
        return f"custom_{node_type}_{datetime.now().strftime('%H%M%S')}"

    def _create_node_definition(
        self,
        node_type: str,
        name: str,
        description: str,
        category: str,
        source_code: str,
        config_schema: dict,
        dependencies: list,
        version: str,
        metadata: dict = None,
        additional_files: dict = None,
    ):
        """一次性创建完整节点目录，避免生成半成品文件"""
        from .node_registry import NodeDefinition, NodeSource

        node_dir = self.custom_nodes_dir / node_type
        version_dir = node_dir / "versions" / version
        if version_dir.exists():
            return None

        config = {
            "node_type": node_type,
            "name": name,
            "description": description,
            "category": category,
            "version": version,
            "entry_file": "node.py",
            "dependencies": dependencies,
            "config_schema": config_schema,
            "metadata": metadata or {},
        }

        temp_dir = self.custom_nodes_dir / f".{node_type}_tmp"
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            with open(temp_dir / "node.json", "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

            with open(temp_dir / "node.py", "w", encoding="utf-8") as f:
                f.write(source_code)

            for relative_path, file_content in (additional_files or {}).items():
                target_file = temp_dir / relative_path
                target_file.parent.mkdir(parents=True, exist_ok=True)
                with open(target_file, "w", encoding="utf-8") as extra_file:
                    extra_file.write(file_content)

            # 移动到版本目录
            version_dir.parent.mkdir(parents=True, exist_ok=True)
            try:
                temp_dir.replace(version_dir)
            except PermissionError:
                shutil.move(str(temp_dir), str(version_dir))
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

        # 设置 current
        self._version_mgr.set_current_version(node_type, version)

        # 创建/更新清单
        manifest = self._version_mgr.load_manifest(node_type)
        if not manifest:
            manifest = LocalManifest(
                node_type=node_type,
                node_name=name,
                current_version=version,
            )
        manifest.add_or_update_version(
            VersionInfo(
                version=version,
                installed_at=datetime.now().isoformat(),
                source="custom",
            )
        )
        self._version_mgr.save_manifest(node_type, manifest)

        return NodeDefinition(
            node_type=node_type,
            name=name,
            description=description,
            source=NodeSource.CUSTOM,
            category=category,
            source_code=source_code,
            config_schema=config_schema,
            metadata=metadata or {},
            dependencies=dependencies,
            version=version,
        )

    def save_node(
        self,
        node_type: str,
        source_code: str,
        config_schema: dict = None,
        name: str = None,
        description: str = None,
        category: str = None,
        dependencies: list = None,
        metadata: dict = None,
        version: Optional[str] = None,
    ) -> bool:
        """保存节点修改

        Args:
            version: 指定版本，None 则使用 current
        """
        if version is None:
            version = self._version_mgr.resolve_current_version(node_type)
        if not version:
            return False

        version_dir = self._version_mgr.get_version_dir(node_type, version)
        if not version_dir.exists():
            return False

        config_file = version_dir / "node.json"
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
        else:
            return False

        # 更新配置
        if config_schema is not None:
            config["config_schema"] = config_schema
        if name is not None:
            config["name"] = name
        if description is not None:
            config["description"] = description
        if category is not None:
            config["category"] = category
        if dependencies is not None:
            config["dependencies"] = dependencies
        if metadata is not None:
            config["metadata"] = metadata

        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        # 更新代码
        entry_file = version_dir / config.get("entry_file", "node.py")
        with open(entry_file, "w", encoding="utf-8") as f:
            f.write(source_code)

        return True

    def get_display_source(self, node_type: str, version: Optional[str] = None) -> str:
        """获取属性面板应显示的源代码"""
        if version is None:
            version = self._version_mgr.resolve_current_version(node_type)

        version_dir = self._version_mgr.get_version_dir(node_type, version)
        if not version_dir.exists():
            return ""

        config_file = version_dir / "node.json"
        if not config_file.exists():
            return ""

        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)

        metadata = config.get("metadata", {})
        if is_playwright_node(metadata):
            script_file = metadata.get("script_file", "script.py")
            script_path = version_dir / script_file
            if script_path.exists():
                return script_path.read_text(encoding="utf-8")

        entry_file = version_dir / config.get("entry_file", "node.py")
        if entry_file.exists():
            return entry_file.read_text(encoding="utf-8")
        return ""

    def save_display_source(
        self, node_type: str, source_code: str, version: Optional[str] = None
    ) -> bool:
        """保存属性面板里编辑的源代码"""
        if version is None:
            version = self._version_mgr.resolve_current_version(node_type)

        version_dir = self._version_mgr.get_version_dir(node_type, version)
        if not version_dir.exists():
            return False

        config_file = version_dir / "node.json"
        if not config_file.exists():
            return False

        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)

        metadata = config.get("metadata", {})
        if is_playwright_node(metadata):
            self.validate_python_source(source_code)
            script_file = metadata.get("script_file", "script.py")
            script_path = version_dir / script_file
            script_path.write_text(source_code, encoding="utf-8")

            param_names = extract_playwright_params(source_code)
            config["config_schema"] = build_playwright_config_schema(
                param_names,
                config.get("config_schema", {}),
            )
            metadata["param_names"] = param_names
            config["metadata"] = metadata

            wrapper_source = build_playwright_wrapper_source(script_path, param_names)
            return self.save_node(
                node_type,
                wrapper_source,
                config_schema=config["config_schema"],
                metadata=config["metadata"],
                version=version,
            )

        is_valid, error_msg = self.validate_node(source_code)
        if not is_valid:
            raise LocalFlowError(ErrorCode.NODE_VALIDATION_FAILED, error_msg)
        return self.save_node(node_type, source_code, version=version)

    def rescan_playwright_node(
        self, node_type: str, version: Optional[str] = None
    ) -> dict:
        """重新扫描 Playwright 脚本中的参数并更新 schema"""
        if version is None:
            version = self._version_mgr.resolve_current_version(node_type)

        version_dir = self._version_mgr.get_version_dir(node_type, version)
        if not version_dir.exists():
            raise LocalFlowError(ErrorCode.NODE_NOT_FOUND, f"节点不存在: {node_type}")

        config_file = version_dir / "node.json"
        if not config_file.exists():
            raise LocalFlowError(ErrorCode.NODE_NOT_FOUND, f"节点配置不存在: {node_type}")

        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)

        metadata = config.get("metadata", {})
        if not is_playwright_node(metadata):
            raise LocalFlowError(ErrorCode.NODE_VALIDATION_FAILED, "该节点不是 Playwright 脚本节点")

        script_file = metadata.get("script_file", "script.py")
        script_path = version_dir / script_file
        if not script_path.exists():
            raise LocalFlowError(ErrorCode.FILE_NOT_FOUND, f"未找到脚本文件: {script_path}")

        script_source = script_path.read_text(encoding="utf-8")
        self.validate_python_source(script_source)

        param_names = extract_playwright_params(script_source)
        config_schema = build_playwright_config_schema(
            param_names,
            config.get("config_schema", {}),
        )
        metadata["param_names"] = param_names

        wrapper_source = build_playwright_wrapper_source(script_path, param_names)
        if not self.save_node(
            node_type,
            wrapper_source,
            config_schema=config_schema,
            metadata=metadata,
            version=version,
        ):
            raise LocalFlowError(ErrorCode.NODE_CREATION_FAILED, "保存 Playwright 节点失败")

        return {
            "param_names": param_names,
            "config_schema": config_schema,
        }

    def validate_node(self, source_code: str) -> Tuple[bool, str]:
        """验证节点代码语法"""
        try:
            ast.parse(source_code)

            # 检查是否定义了 execute 函数
            has_execute = False
            tree = ast.parse(source_code)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "execute":
                    has_execute = True
                    break

            if not has_execute:
                return False, "未找到 execute(self, input_data) 函数定义"

            return True, ""
        except SyntaxError as e:
            return False, f"语法错误: {e.msg} (第{e.lineno}行)"
        except Exception as e:
            return False, f"验证失败: {str(e)}"

    def validate_python_source(self, source_code: str) -> None:
        """验证任意 Python 脚本语法"""
        try:
            ast.parse(source_code)
        except SyntaxError as exc:
            raise LocalFlowError(ErrorCode.SYNTAX_ERROR, f"语法错误: {exc.msg} (第{exc.lineno}行)") from exc

    def export_node(
        self,
        node_type: str,
        output_path: str,
        version: Optional[str] = None,
        all_versions: bool = False,
    ) -> bool:
        """导出节点为标准格式 ZIP 包

        Args:
            version: 指定版本，None 则导出 current
            all_versions: 是否导出所有版本
        """
        node_dir = self.custom_nodes_dir / node_type
        if not node_dir.exists():
            return False

        try:
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                if all_versions:
                    # 导出所有版本
                    versions_dir = node_dir / "versions"
                    if versions_dir.exists():
                        for version_dir in versions_dir.iterdir():
                            if version_dir.is_dir():
                                for file in version_dir.rglob("*"):
                                    if file.is_file():
                                        arcname = f"versions/{version_dir.name}/{file.relative_to(version_dir)}"
                                        zf.write(file, arcname)
                    # 包含 manifest 和 current
                    for meta_file in [".manifest", "current"]:
                        meta_path = node_dir / meta_file
                        if meta_path.exists():
                            zf.write(meta_path, meta_file)
                else:
                    if version is None:
                        version = self._version_mgr.resolve_current_version(node_type)
                    version_dir = self._version_mgr.get_version_dir(node_type, version)
                    if version_dir.exists():
                        for file in version_dir.iterdir():
                            if file.is_file():
                                zf.write(file, file.name)
                        # 包含版本信息
                        manifest = self._version_mgr.load_manifest(node_type)
                        if manifest:
                            zf.writestr(
                                "version_info.json",
                                json.dumps(
                                    {
                                        "version": version,
                                        "node_type": node_type,
                                    },
                                    ensure_ascii=False,
                                    indent=2,
                                ),
                            )
            return True
        except Exception as e:
            logger.error("导出节点失败: %s", e)
            return False

    def import_node(
        self, zip_path: str, target_version: Optional[str] = None
    ) -> Optional[str]:
        """从 ZIP 包导入节点

        Returns:
            导入的 node_type，或 None 如果失败
        """
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                # 检查是否有版本信息
                version_info = None
                if "version_info.json" in zf.namelist():
                    version_info = json.loads(
                        zf.read("version_info.json").decode("utf-8")
                    )

                # 检查是否有 versions/ 目录结构
                has_versions = any(n.startswith("versions/") for n in zf.namelist())

                if has_versions:
                    # 多版本导入
                    node_type = None
                    for name in zf.namelist():
                        if name.startswith("versions/"):
                            parts = name.split("/")
                            if len(parts) >= 2:
                                # 确定 node_type（从路径推断或从 version_info）
                                if version_info:
                                    node_type = version_info.get("node_type")
                                break

                    if not node_type:
                        # 尝试从 node.json 获取
                        for name in zf.namelist():
                            if name.endswith("node.json"):
                                node_json = json.loads(zf.read(name).decode("utf-8"))
                                node_type = node_json.get("node_type")
                                break

                    if not node_type:
                        raise LocalFlowError(ErrorCode.NODE_VALIDATION_FAILED, "无法确定节点类型")

                    # 解压到目标目录
                    node_dir = self.custom_nodes_dir / node_type
                    node_dir.mkdir(parents=True, exist_ok=True)

                    for name in zf.namelist():
                        if name.endswith("/"):
                            continue
                        target = node_dir / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with open(target, "wb") as f:
                            f.write(zf.read(name))

                    # 更新清单
                    manifest = self._version_mgr.load_manifest(
                        node_type
                    ) or LocalManifest(node_type=node_type)
                    for v_dir in (node_dir / "versions").iterdir():
                        if v_dir.is_dir() and not manifest.has_version(v_dir.name):
                            manifest.add_or_update_version(
                                VersionInfo(
                                    version=v_dir.name,
                                    source="imported",
                                )
                            )
                    if not manifest.current_version and manifest.versions:
                        manifest.current_version = manifest.versions[0].version
                        self._version_mgr.set_current_version(
                            node_type, manifest.current_version
                        )
                    self._version_mgr.save_manifest(node_type, manifest)

                    return node_type
                else:
                    # 单版本导入
                    node_json_data = None
                    if "node.json" in zf.namelist():
                        node_json_data = json.loads(
                            zf.read("node.json").decode("utf-8")
                        )

                    if not node_json_data:
                        raise LocalFlowError(ErrorCode.NODE_VALIDATION_FAILED, "ZIP 中未找到 node.json")

                    node_type = node_json_data.get("node_type", "imported_node")
                    version = (
                        target_version or version_info.get("version", "1.0.0")
                        if version_info
                        else "1.0.0"
                    )

                    version_dir = self._version_mgr.create_version_dir(
                        node_type, version
                    )

                    for name in zf.namelist():
                        if name.endswith("/"):
                            continue
                        target = version_dir / name
                        with open(target, "wb") as f:
                            f.write(zf.read(name))

                    # 设置 current
                    self._version_mgr.set_current_version(node_type, version)

                    # 更新清单
                    manifest = self._version_mgr.load_manifest(
                        node_type
                    ) or LocalManifest(
                        node_type=node_type,
                        node_name=node_json_data.get("name", node_type),
                    )
                    manifest.add_or_update_version(
                        VersionInfo(
                            version=version,
                            source="imported",
                        )
                    )
                    manifest.current_version = version
                    self._version_mgr.save_manifest(node_type, manifest)

                    return node_type

        except Exception as e:
            logger.error("导入节点失败: %s", e)
            return None

    def delete_node(self, node_type: str) -> bool:
        """删除节点（所有版本）"""
        node_dir = self.custom_nodes_dir / node_type
        if node_dir.exists():
            shutil.rmtree(node_dir)
            return True
        return False

    def delete_node_version(self, node_type: str, version: str) -> bool:
        """删除节点的特定版本"""
        return self._version_mgr.remove_version(node_type, version)

    def list_node_versions(self, node_type: str) -> List[str]:
        """列出节点的所有版本"""
        return self._version_mgr.list_local_versions(node_type)

    def _get_node_dir_and_config(self, node_type: str, version: Optional[str] = None):
        """读取节点目录及配置"""
        if version is None:
            version = self._version_mgr.resolve_current_version(node_type)

        version_dir = self._version_mgr.get_version_dir(node_type, version)
        config_file = version_dir / "node.json"
        if not config_file.exists():
            return None, None

        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)
        return version_dir, config
