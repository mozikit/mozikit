"""
工作流执行引擎
负责工作流的执行、节点调度、数据传递
"""

import json
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.core.exceptions import ErrorCode, LocalFlowError
from src.core.log_manager import get_logger

from .node_base import NodeBase
from .uv_manager import UVManager

logger = get_logger("workflow_executor")


def write_workflow_file(file_path: str, workflow_data: dict):
    """将工作流数据写入文件（纯I/O操作，可在后台线程安全调用）

    Args:
        file_path: 保存路径
        workflow_data: 工作流数据字典
    """
    created_at = None
    if Path(file_path).exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
                created_at = existing_data.get("created_at")
        except:
            pass

    now = datetime.now().isoformat()
    if not created_at:
        created_at = now

    workflow_data["created_at"] = created_at
    workflow_data["updated_at"] = now

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(workflow_data, f, ensure_ascii=False, indent=2)


@dataclass
class EdgeInfo:
    """边信息 - 包含端口级连接信息"""

    from_node: str
    from_port: str
    to_node: str
    to_port: str


class WorkflowExecutor:
    """工作流执行器"""

    def __init__(
        self, workflow_name: str, uv_manager: UVManager = None, config_manager=None
    ):
        """
        初始化工作流执行器

        Args:
            workflow_name: 工作流名称
            uv_manager: UV管理器实例
            config_manager: 配置管理器实例（用于读取超时设置）
        """
        self.workflow_name = workflow_name
        self.uv_manager = uv_manager or UVManager()
        from src.core.config_manager import ConfigManager

        self.config_manager = config_manager or ConfigManager()
        self.nodes: Dict[str, NodeBase] = {}
        self.edges: List[EdgeInfo] = []
        self.execution_order: List[str] = []
        self.context: Dict[str, Any] = {}
        self.node_results: Dict[str, Dict[str, Any]] = {}
        self.node_outputs: Dict[str, Dict[str, Any]] = {}
        self._stop_event = threading.Event()
        self._worker_process = None

    def add_node(self, node: NodeBase):
        """添加节点"""
        self.nodes[node.node_id] = node

    def add_edge(
        self,
        from_node_id: str,
        from_port_name: str = "",
        to_node_id: str = "",
        to_port_name: str = "",
    ):
        """添加边（连接）"""
        if not to_node_id and from_port_name and not to_port_name:
            to_node_id = from_port_name
            from_port_name = "output"
            to_port_name = "input"

        self.edges.append(
            EdgeInfo(from_node_id, from_port_name, to_node_id, to_port_name)
        )

        if from_node_id in self.nodes:
            self.nodes[from_node_id].outputs.append(to_node_id)
        if to_node_id in self.nodes:
            self.nodes[to_node_id].inputs.append(from_node_id)

    def request_stop(self):
        self._stop_event.set()
        if self._worker_process and self._worker_process.poll() is None:
            try:
                self._worker_process.terminate()
            except Exception:
                try:
                    self._worker_process.kill()
                except Exception:
                    pass

    def is_stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def reset_stop(self):
        self._stop_event.clear()

    def _build_node_input(self, node_id: str) -> dict:
        """根据端口映射构建节点的精确输入数据

        对于有 input_schema 的节点，只传递端口连接指定的数据；
        对于没有 input_schema 的节点，回退到全量 context.copy() 以保持向后兼容。
        """
        node = self.nodes.get(node_id)
        if not node:
            return self.context.copy()

        # 获取节点的 input_schema（从注册表查找节点定义）
        from src.core.node_registry import get_registry

        registry = get_registry()
        node_type_str = (
            node.node_type.value
            if hasattr(node.node_type, "value")
            else str(node.node_type)
        )
        node_def = registry.get_node(node_type_str)
        input_schema = node_def.input_schema if node_def else {}

        if not input_schema:
            # 无 schema -> 向后兼容：全量上下文
            return self.context.copy()

        # 收集所有指向此节点的入边
        incoming_edges = [e for e in self.edges if e.to_node == node_id]

        if not incoming_edges:
            # 没有入边 -> 只传 context 中的初始数据
            return self.context.copy()

        input_data = {}

        for edge in incoming_edges:
            # 获取上游节点的输出
            upstream_output = self.node_outputs.get(edge.from_node)
            if upstream_output is None:
                # 上游尚未执行，从 context 中查找
                upstream_output = self.context

            # 获取上游节点的 output_schema 以解析 from_port 的 from_config
            upstream_node = self.nodes.get(edge.from_node)
            upstream_type = (
                upstream_node.node_type.value
                if upstream_node and hasattr(upstream_node.node_type, "value")
                else (str(upstream_node.node_type) if upstream_node else "")
            )
            upstream_def = registry.get_node(upstream_type) if upstream_type else None
            upstream_output_schema = upstream_def.output_schema if upstream_def else {}

            # 解析上游输出键：优先用 from_config 映射，否则用端口名
            output_port_schema = upstream_output_schema.get(edge.from_port, {})
            if isinstance(output_port_schema, dict):
                output_from_config = output_port_schema.get("from_config")
            else:
                output_from_config = None

            if output_from_config:
                # 输出端口的 from_config 指向 config 中的键，节点返回的 key 就是 config[from_config] 的值
                output_key = (
                    upstream_node.config.get(output_from_config)
                    if upstream_node
                    else None
                )
                # 从上游输出中取值
                value = upstream_output.get(output_key) if output_key else None
            else:
                # 无 from_config，直接用端口名作为输出 key
                value = upstream_output.get(edge.from_port)

            # 解析目标输入键：使用 input_schema 中 to_port 的 from_config
            input_port_schema = input_schema.get(edge.to_port, {})
            if isinstance(input_port_schema, dict):
                input_from_config = input_port_schema.get("from_config")
            else:
                input_from_config = None

            if input_from_config:
                # from_config 指向 config 中的键名，节点代码用 config[from_config] 读取
                input_key = node.config.get(input_from_config, input_from_config)
            else:
                # 无 from_config，用端口名作为 key
                input_key = edge.to_port

            if value is not None or (
                edge.from_port in upstream_output
                if isinstance(upstream_output, dict)
                else False
            ):
                input_data[input_key] = value

        # 合并初始上下文数据（确保非端口连接的数据也可用）
        for key, val in self.context.items():
            if key not in input_data:
                input_data[key] = val

        return input_data

    def prepare_environment(
        self, python_version: str = None, packages: List[str] = None
    ) -> bool:
        """
        准备工作流执行环境

        Args:
            python_version: Python版本
            packages: 需要额外安装的包列表

        Returns:
            是否准备成功
        """
        all_dependencies = self._collect_node_dependencies()

        if packages:
            all_dependencies.extend(packages)

        resolved_packages = self._resolve_dependencies(all_dependencies)

        if not self.uv_manager.create_workflow_env(self.workflow_name, python_version):
            return False

        if resolved_packages:
            logger.info("正在安装工作流依赖: %s", resolved_packages)
            if not self.uv_manager.install_packages(
                self.workflow_name, resolved_packages
            ):
                return False

        return True

    def _collect_node_dependencies(self) -> List[str]:
        """收集工作流中所有节点声明的依赖"""
        from .node_registry import get_registry

        registry = get_registry()
        dependencies = []
        seen_types = set()

        for node in self.nodes.values():
            node_type_str = (
                node.node_type.value
                if hasattr(node.node_type, "value")
                else str(node.node_type)
            )
            if node_type_str in seen_types:
                continue

            node_def = registry.get_node(node_type_str)
            if node_def and node_def.dependencies:
                dependencies.extend(node_def.dependencies)
            seen_types.add(node_type_str)

        return dependencies

    def _resolve_dependencies(self, dependencies: List[str]) -> List[str]:
        """解析并去重依赖，检测基本冲突"""
        if not dependencies:
            return []

        cleaned = sorted(list(set([d.strip() for d in dependencies if d.strip()])))

        packages = {}
        for dep in cleaned:
            import re

            match = re.match(r"^([a-zA-Z0-9_\-\[\]]+)", dep)
            if match:
                pkg_name = match.group(1).lower().replace("_", "-")
                if pkg_name in packages and packages[pkg_name] != dep:
                    logger.warning(
                        "检测到潜在依赖冲突: '%s' vs '%s'", packages[pkg_name], dep
                    )
                packages[pkg_name] = dep

        return cleaned

    def _topological_sort(self) -> List[str]:
        """
        拓扑排序，确定节点执行顺序

        Returns:
            节点ID列表（执行顺序）
        """
        in_degree = defaultdict(int)
        for node_id in self.nodes:
            in_degree[node_id] = 0

        for e in self.edges:
            in_degree[e.to_node] += 1

        queue = [node_id for node_id in self.nodes if in_degree[node_id] == 0]
        result = []

        while queue:
            node_id = queue.pop(0)
            result.append(node_id)

            for e in self.edges:
                if e.from_node == node_id:
                    in_degree[e.to_node] -= 1
                    if in_degree[e.to_node] == 0:
                        queue.append(e.to_node)

        if len(result) != len(self.nodes):
            raise LocalFlowError(ErrorCode.WORKFLOW_CYCLE_DETECTED, "工作流中存在环路，无法执行")

        return result

    def _get_versioned_script_path(self, node: NodeBase) -> str:
        """获取版本感知的脚本路径

        如果工作流中的节点指定了版本，尝试从对应版本目录加载源代码，
        并生成到工作流脚本目录中。
        """
        from src.core.custom_node_manager import CustomNodeManager
        from src.core.node_repo_manager import NodeRepoManager
        from src.core.node_version_manager import NodeVersionManager

        node_type_str = (
            node.node_type.value
            if hasattr(node.node_type, "value")
            else str(node.node_type)
        )

        # 如果节点有版本绑定，尝试获取该版本的源代码
        if node.version:
            # 检查官方节点
            repo_mgr = NodeRepoManager(self._user_data_dir)
            official_vm = repo_mgr.version_manager
            resolved_version, node_py = official_vm.resolve_version_for_execution(
                node_type_str, node.version
            )
            if node_py and node_py.exists():
                with open(node_py, "r", encoding="utf-8") as f:
                    node.source_code = f.read()
                return node.generate_script(
                    str(
                        self.uv_manager.get_workflow_dir(self.workflow_name) / "scripts"
                    )
                )

            # 检查自定义节点
            custom_mgr = CustomNodeManager(self._user_data_dir)
            custom_vm = custom_mgr.version_manager
            resolved_version, node_py = custom_vm.resolve_version_for_execution(
                node_type_str, node.version
            )
            if node_py and node_py.exists():
                with open(node_py, "r", encoding="utf-8") as f:
                    node.source_code = f.read()
                return node.generate_script(
                    str(
                        self.uv_manager.get_workflow_dir(self.workflow_name) / "scripts"
                    )
                )

        # 无版本绑定或版本未找到，使用注册表中的源代码
        return node.generate_script(
            str(self.uv_manager.get_workflow_dir(self.workflow_name) / "scripts")
        )

    def generate_scripts(self) -> Dict[str, str]:
        """
        为所有节点生成Python脚本（支持版本绑定）

        Returns:
            节点ID到脚本路径的映射
        """
        workflow_dir = self.uv_manager.get_workflow_dir(self.workflow_name)
        scripts_dir = workflow_dir / "scripts"
        scripts_dir.mkdir(exist_ok=True)

        script_paths = {}
        for node_id, node in self.nodes.items():
            script_path = self._get_versioned_script_path(node)
            script_paths[node_id] = script_path

        return script_paths

    def _sanitize_for_report(self, value: Any, depth: int = 0) -> Any:
        """将运行产物清洗为 JSON 可序列化形式"""
        if depth > 6:
            return repr(value)

        if value is None or isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, dict):
            return {
                str(key): self._sanitize_for_report(item, depth + 1)
                for key, item in value.items()
            }

        if isinstance(value, (list, tuple, set)):
            return [self._sanitize_for_report(item, depth + 1) for item in value]

        if isinstance(value, Path):
            return str(value)

        try:
            json.dumps(value, ensure_ascii=False)
            return value
        except TypeError:
            return repr(value)

    def _strip_protocol_output(self, output: str) -> str:
        """移除脚本协议用的 JSON 包裹标记，只保留真实日志"""
        if not output:
            return ""

        start_token = "###JSON_OUTPUT###"
        end_token = "###JSON_OUTPUT_END###"
        if start_token not in output:
            return output.strip()

        start = output.find(start_token)
        end = output.find(end_token)

        before = output[:start]
        after = output[end + len(end_token) :] if end != -1 else ""
        cleaned = "\n".join(part for part in [before.strip(), after.strip()] if part)
        return cleaned.strip()

    def _execute_node_with_details(
        self,
        node_id: str,
        input_data: Dict[str, Any] = None,
        worker_process=None,
        on_node_progress: Callable[[str, int, str], None] = None,
        on_node_log: Callable[[str, str], None] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        执行单个节点并返回结构化报告

        Returns:
            (原始输出数据, 节点执行报告)
        """
        if node_id not in self.nodes:
            raise LocalFlowError(ErrorCode.NODE_NOT_FOUND, f"节点不存在: {node_id}")

        node = self.nodes[node_id]
        workflow_dir = self.uv_manager.get_workflow_dir(self.workflow_name)
        scripts_dir = workflow_dir / "scripts"
        scripts_dir.mkdir(exist_ok=True)

        script_path = node.generate_script(str(scripts_dir))
        node_type_str = (
            node.node_type.value
            if hasattr(node.node_type, "value")
            else str(node.node_type)
        )

        started_at = datetime.now()
        logger.info("执行节点: %s (%s)", node_id, node_type_str)

        def _progress_cb(percent, message):
            if on_node_progress:
                on_node_progress(node_id, percent, message)

        def _log_cb(line):
            if on_node_log:
                on_node_log(node_id, line)

        node_timeout = self.config_manager.get_node_timeout_seconds()

        if worker_process:
            command = {
                "type": "run_node",
                "script_path": script_path,
                "input_data": input_data or {},
            }
            result = self.uv_manager.send_command_to_worker(
                worker_process,
                command,
                timeout=node_timeout,
                progress_callback=_progress_cb,
                log_callback=_log_cb,
            )
        else:
            result = self.uv_manager.run_python_script_streaming(
                self.workflow_name,
                script_path,
                input_data or {},
                timeout=node_timeout,
                progress_callback=_progress_cb,
                log_callback=_log_cb,
            )

        duration_ms = int((datetime.now() - started_at).total_seconds() * 1000)
        raw_output = result.get("data") or {}
        stdout = result.get("stdout")
        if stdout is None:
            stdout = self._strip_protocol_output(result.get("output", ""))

        stderr = result.get("stderr")
        if stderr is None and "output" in result:
            stderr = result.get("error", "")

        node_report = {
            "node_id": node_id,
            "node_type": node_type_str,
            "success": bool(result.get("success")),
            "duration_ms": duration_ms,
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "script_path": str(script_path),
            "input": self._sanitize_for_report(input_data or {}),
            "output": self._sanitize_for_report(raw_output),
            "stdout": (stdout or "").strip(),
            "stderr": (stderr or "").strip(),
            "error": (result.get("error") or "").strip(),
            "traceback": (result.get("traceback") or "").strip(),
        }

        return raw_output, node_report

    def execute_node(
        self, node_id: str, input_data: Dict[str, Any] = None, worker_process=None
    ) -> Dict[str, Any]:
        """
        执行单个节点

        Args:
            node_id: 节点ID
            input_data: 输入数据
            worker_process: 可选的Worker进程对象

        Returns:
            节点输出数据
        """
        raw_output, node_report = self._execute_node_with_details(
            node_id, input_data, worker_process
        )

        if not node_report["success"]:
            raise LocalFlowError(ErrorCode.NODE_EXECUTION_FAILED, f"节点执行失败: {node_report['error']}")

        return raw_output

    def _check_safety_warning(self, node_id: str, node_type_str: str) -> str:
        """检查节点是否存在未确认的安全警告"""
        from .node_registry import get_registry

        registry = get_registry()
        node_def = registry.get_node(node_type_str)
        if not node_def:
            return ""

        safety_warning = node_def.metadata.get("safety_warning")
        if not safety_warning:
            return ""

        config = self.nodes.get(node_id)
        if (
            config
            and isinstance(config.config, dict)
            and config.config.get("_safety_confirmed")
        ):
            return ""

        risk_level = safety_warning.get("risk_level", "unknown")
        risks = safety_warning.get("risks", [])
        risk_detail = "; ".join(risks) if risks else "未知风险"
        return f"[{risk_level}级风险] {risk_detail}。请在节点配置中确认后方可执行。"

    def _prefix_log_block(self, node_id: str, content: str) -> str:
        """为聚合日志添加节点前缀，避免多节点日志混在一起"""
        if not content:
            return ""

        return "\n".join(
            f"[{node_id}] {line}" if line else f"[{node_id}]"
            for line in content.splitlines()
        ).strip()

    def _create_run_report(self, trigger_type: str = "manual") -> Dict[str, Any]:
        started_at = datetime.now()
        run_id = f"{started_at.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        return {
            "run_id": run_id,
            "workflow_name": self.workflow_name,
            "trigger_type": trigger_type,
            "success": False,
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": None,
            "duration_ms": 0,
            "execution_order": [],
            "nodes": [],
            "final_context": {},
            "stdout": "",
            "stderr": "",
            "error": "",
            "failed_node_id": "",
            "artifact_dir": "",
        }

    def _persist_run_artifacts(self, report: Dict[str, Any]) -> str:
        """将运行报告、stdout、stderr 持久化到工作流 runs 目录"""
        workflow_dir = self.uv_manager.get_workflow_dir(self.workflow_name)
        runs_dir = workflow_dir / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)

        artifact_dir = runs_dir / report["run_id"]
        artifact_dir.mkdir(parents=True, exist_ok=True)

        report["artifact_dir"] = str(artifact_dir)

        with open(artifact_dir / "run.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        with open(artifact_dir / "stdout.log", "w", encoding="utf-8") as f:
            f.write(report.get("stdout", "") or "")

        with open(artifact_dir / "stderr.log", "w", encoding="utf-8") as f:
            f.write(report.get("stderr", "") or "")

        return str(artifact_dir)

    def build_execution_record(
        self, report: Dict[str, Any], workflow_path: str = "", trigger_type: str = None
    ) -> Dict[str, Any]:
        """将运行报告转成首页历史记录使用的摘要"""
        if report.get("stopped"):
            status = "stopped"
        elif report.get("success"):
            status = "success"
        else:
            status = "failed"
        return {
            "id": report.get("run_id", str(uuid.uuid4())[:8]),
            "workflow_name": report.get("workflow_name", self.workflow_name),
            "workflow_path": workflow_path,
            "status": status,
            "started_at": report.get("started_at", ""),
            "finished_at": report.get("finished_at", ""),
            "duration_ms": report.get("duration_ms", 0),
            "output": report.get("final_context"),
            "error": report.get("error") or None,
            "trigger_type": trigger_type or report.get("trigger_type", "manual"),
            "artifact_dir": report.get("artifact_dir", ""),
        }

    def execute(
        self,
        initial_data: Dict[str, Any] = None,
        return_report: bool = False,
        trigger_type: str = "manual",
        on_node_start: Callable[[str], None] = None,
        on_node_complete: Callable[[Dict[str, Any]], None] = None,
        on_node_progress: Callable[[str, int, str], None] = None,
        on_node_log: Callable[[str, str], None] = None,
        skip_successful_nodes: bool = False,
    ) -> Dict[str, Any]:
        """
        执行整个工作流

        Args:
            initial_data: 初始输入数据
            return_report: 是否返回结构化运行报告
            trigger_type: 触发类型（manual/scheduled）
            on_node_start: 每个节点开始执行时的回调，参数为 node_id
            on_node_complete: 每个节点完成后的回调，参数为 node_report dict
            on_node_progress: 节点进度回调，参数为 (node_id, percent, message)
            on_node_log: 实时日志回调，参数为 (node_id, line)
            skip_successful_nodes: 是否跳过已缓存的成功节点

        Returns:
            最终输出数据，或结构化运行报告
        """
        report = self._create_run_report(trigger_type)
        report_started_at = datetime.fromisoformat(report["started_at"])
        stdout_blocks: List[str] = []
        stderr_blocks: List[str] = []

        self.reset_stop()
        self._worker_process = None
        worker_process = None

        try:
            self.execution_order = self._topological_sort()
            report["execution_order"] = list(self.execution_order)
            logger.info("执行顺序: %s", self.execution_order)

            self.context = initial_data or {}
            self.node_outputs = {}

            script_paths = self.generate_scripts()
            logger.info("已生成 %d 个节点脚本", len(script_paths))

            logger.info("正在启动工作流执行引擎...")
            worker_process = self.uv_manager.start_worker(self.workflow_name)
            self._worker_process = worker_process
            if worker_process:
                logger.info("工作流执行引擎启动成功")
            else:
                logger.warning("工作流执行引擎启动失败，将使用传统模式执行")

            for node_id in self.execution_order:
                if self._stop_event.is_set():
                    report["success"] = False
                    report["error"] = "工作流已被用户停止"
                    report["stopped"] = True
                    logger.info(
                        "工作流已被用户停止，已执行 %d/%d 个节点",
                        len(report["nodes"]),
                        len(self.execution_order),
                    )
                    break

                if on_node_start:
                    on_node_start(node_id)

                node = self.nodes[node_id]
                node_type_str = (
                    node.node_type.value
                    if hasattr(node.node_type, "value")
                    else str(node.node_type)
                )

                if skip_successful_nodes and node_id in self.node_results:
                    cached = self.node_results[node_id]
                    cached_report = cached["report"].copy()
                    cached_report["duration_ms"] = 0
                    cached_report["started_at"] = datetime.now().isoformat(
                        timespec="seconds"
                    )
                    cached_report["finished_at"] = datetime.now().isoformat(
                        timespec="seconds"
                    )
                    cached_report["stdout"] = "[已缓存，跳过执行]"
                    report["nodes"].append(cached_report)
                    if on_node_complete:
                        on_node_complete(cached_report)
                    self.context.update(cached["output"])
                    self.node_outputs[node_id] = cached["output"].copy()
                    logger.info("节点 %s 已缓存，跳过执行", node_id)
                    continue

                safety_warning = self._check_safety_warning(node_id, node_type_str)
                if safety_warning:
                    warning_msg = (
                        f"节点 {node_id} ({node_type_str}) 因安全警告被跳过: "
                        f"{safety_warning}"
                    )
                    logger.warning(warning_msg)
                    node_report = {
                        "node_id": node_id,
                        "node_type": node_type_str,
                        "success": False,
                        "duration_ms": 0,
                        "started_at": datetime.now().isoformat(timespec="seconds"),
                        "finished_at": datetime.now().isoformat(timespec="seconds"),
                        "script_path": "",
                        "input": self._sanitize_for_report(input_data or {}),
                        "output": {},
                        "stdout": "",
                        "stderr": warning_msg,
                        "error": warning_msg,
                        "traceback": "",
                    }
                    report["nodes"].append(node_report)
                    if on_node_complete:
                        on_node_complete(node_report)
                    report["success"] = False
                    report["error"] = warning_msg
                    report["failed_node_id"] = node_id
                    break

                input_data = self._build_node_input(node_id)
                raw_output, node_report = self._execute_node_with_details(
                    node_id, input_data, worker_process, on_node_progress, on_node_log
                )

                if self._stop_event.is_set():
                    report["success"] = False
                    report["error"] = "工作流已被用户停止"
                    report["stopped"] = True
                    if node_report.get("success"):
                        self.context.update(raw_output)
                        self.node_outputs[node_id] = raw_output.copy()
                        self.node_results[node_id] = {
                            "output": raw_output.copy(),
                            "report": node_report.copy(),
                        }
                    report["nodes"].append(node_report)
                    if on_node_complete:
                        on_node_complete(node_report)
                    logger.info("工作流已被用户停止（节点 %s 执行期间）", node_id)
                    break

                report["nodes"].append(node_report)

                if on_node_complete:
                    on_node_complete(node_report)

                if node_report["stdout"]:
                    stdout_blocks.append(
                        self._prefix_log_block(node_id, node_report["stdout"])
                    )
                if node_report["stderr"]:
                    stderr_blocks.append(
                        self._prefix_log_block(node_id, node_report["stderr"])
                    )

                if not node_report["success"]:
                    report["success"] = False
                    report["error"] = node_report["error"] or f"节点 {node_id} 执行失败"
                    report["failed_node_id"] = node_id
                    logger.error("节点 %s 执行失败: %s", node_id, report["error"])
                    break

                self.context.update(raw_output)
                self.node_outputs[node_id] = raw_output.copy()
                self.node_results[node_id] = {
                    "output": raw_output.copy(),
                    "report": node_report.copy(),
                }
                logger.info("节点 %s 执行成功", node_id)
            else:
                report["success"] = True

        except Exception as e:
            report["success"] = False
            report["error"] = str(e)
            if not return_report:
                raise
        finally:
            self._worker_process = None
            if worker_process:
                try:
                    self.uv_manager.send_command_to_worker(
                        worker_process, {"type": "exit"}, timeout=2
                    )
                    worker_process.terminate()
                    worker_process.wait(timeout=2)
                except Exception:
                    if worker_process.poll() is None:
                        worker_process.kill()
                logger.info("工作流执行引擎已关闭")

            report["finished_at"] = datetime.now().isoformat(timespec="seconds")
            report["duration_ms"] = int(
                (datetime.now() - report_started_at).total_seconds() * 1000
            )
            report["final_context"] = self._sanitize_for_report(self.context)
            report["stdout"] = "\n".join(
                block for block in stdout_blocks if block
            ).strip()
            report["stderr"] = "\n".join(
                block for block in stderr_blocks if block
            ).strip()
            try:
                self._persist_run_artifacts(report)
            except Exception as persist_error:
                persist_message = f"持久化运行产物失败: {persist_error}"
                logger.error("持久化运行产物失败: %s", persist_error)
                report["stderr"] = (
                    f"{report['stderr']}\n{persist_message}".strip()
                    if report["stderr"]
                    else persist_message
                )

        if return_report:
            return report

        if not report["success"]:
            raise LocalFlowError(ErrorCode.WORKFLOW_EXECUTION_FAILED, report["error"] or "工作流执行失败")

        return self.context

    def build_workflow_data(
        self, node_positions: dict = None, canvas_state: dict = None
    ) -> dict:
        """构建工作流保存数据（不写入文件，用于异步保存时在主线程准备数据）

        Args:
            node_positions: 节点位置信息 {node_id: {"x": x, "y": y}}
            canvas_state: 画布状态信息 {"scale_x": float, "scale_y": float, "offset_x": float, "offset_y": float}

        Returns:
            dict: 工作流数据字典
        """
        workflow_data = {
            "version": 2,
            "workflow_name": self.workflow_name,
            "nodes": [],
            "edges": [
                {
                    "from_node": e.from_node,
                    "from_port": e.from_port,
                    "to_node": e.to_node,
                    "to_port": e.to_port,
                }
                for e in self.edges
            ],
            "dependencies": self._collect_node_dependencies(),
        }

        if canvas_state:
            workflow_data["canvas_state"] = canvas_state

        for node in self.nodes.values():
            node_dict = node.to_dict()
            if node_positions and node.node_id in node_positions:
                node_dict["position"] = node_positions[node.node_id]
            workflow_data["nodes"].append(node_dict)

        return workflow_data

    def save_workflow(
        self, file_path: str, node_positions: dict = None, canvas_state: dict = None
    ):
        """保存工作流到文件

        Args:
            file_path: 保存路径
            node_positions: 节点位置信息 {node_id: {"x": x, "y": y}}
            canvas_state: 画布状态信息 {"scale_x": float, "scale_y": float, "offset_x": float, "offset_y": float}
        """
        workflow_data = self.build_workflow_data(node_positions, canvas_state)
        write_workflow_file(file_path, workflow_data)

    @classmethod
    def load_workflow(
        cls, file_path: str, uv_manager: UVManager = None
    ) -> "WorkflowExecutor":
        """从文件加载工作流"""
        with open(file_path, "r", encoding="utf-8") as f:
            workflow_data = json.load(f)

        executor = cls(workflow_data["workflow_name"], uv_manager)

        for node_data in workflow_data["nodes"]:
            node = NodeBase.from_dict(node_data)
            executor.add_node(node)

        version = workflow_data.get("version", 1)
        for edge_data in workflow_data["edges"]:
            if version >= 2 and isinstance(edge_data, dict):
                executor.add_edge(
                    edge_data["from_node"],
                    edge_data["from_port"],
                    edge_data["to_node"],
                    edge_data["to_port"],
                )
            else:
                # 旧格式: [from_id, to_id]
                from_id, to_id = edge_data[0], edge_data[1]
                executor.add_edge(from_id, "output", to_id, "input")

        return executor

    def get_execution_stats(self) -> dict:
        """获取执行统计信息"""
        return {
            "workflow_name": self.workflow_name,
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "execution_order": self.execution_order,
            "context_keys": list(self.context.keys()),
        }
