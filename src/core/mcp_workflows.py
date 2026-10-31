"""Headless workflow operations shared by the MCP tools.

Paths exposed by this service are relative to one workspace. Workflow execution
uses the same engine and persisted run reports as the CLI and desktop app.
"""

import json
from collections import defaultdict, deque
from itertools import islice
from pathlib import Path, PureWindowsPath
from threading import Lock


class WorkflowService:
    def __init__(self, workspace):
        self.workspace = Path(workspace).expanduser().resolve()
        # The executor writes scripts and environments per workflow. Serialize
        # runs to prevent concurrent calls overwriting those shared files.
        self._run_lock = Lock()

    def _contained(self, path):
        resolved = Path(path).resolve()
        try:
            resolved.relative_to(self.workspace)
        except ValueError:
            raise ValueError("路径必须位于所选工作空间内") from None
        return resolved

    def _workflow_path(self, path):
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        candidate = self._contained(candidate)
        if not candidate.is_file() or candidate.suffix.lower() != ".json":
            raise ValueError("工作流必须是工作空间内已存在的 JSON 文件")
        return candidate

    @staticmethod
    def _read_json(path):
        with path.open(encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            raise ValueError("JSON 顶层必须是对象")
        return data

    @staticmethod
    def _safe_segment(value):
        return (
            isinstance(value, str)
            and bool(value.strip())
            and value not in {".", ".."}
            and not any(char in value for char in ("/", "\\", "\0"))
            and not PureWindowsPath(value).drive
        )

    def list_workflows(self):
        workflows = []
        for candidate in sorted(self.workspace.glob("*/workflow.json")):
            try:
                result = self.get_workflow(str(candidate))
                data = result["workflow"]
                if not isinstance(data.get("workflow_name"), str):
                    continue
                nodes = data.get("nodes", [])
                workflows.append({
                    "name": data["workflow_name"],
                    "path": result["path"],
                    "node_count": len(nodes) if isinstance(nodes, list) else 0,
                    "updated_at": data.get("updated_at"),
                })
            except (OSError, ValueError):
                # A broken file or an external symlink must not hide all the
                # other workflows, or expose data outside the workspace.
                continue
        return {"workspace": str(self.workspace), "workflows": workflows}

    def get_workflow(self, path):
        file_path = self._workflow_path(path)
        return {
            "path": file_path.relative_to(self.workspace).as_posix(),
            "workflow": self._read_json(file_path),
        }

    def validate_workflow(self, path):
        file_path = self._workflow_path(path)
        try:
            data = self._read_json(file_path)
            order = self._validate_data(data)
            return {
                "valid": True,
                "path": file_path.relative_to(self.workspace).as_posix(),
                "workflow_name": data["workflow_name"],
                "node_count": len(data["nodes"]),
                "edge_count": len(data["edges"]),
                "execution_order": order,
                "errors": [],
            }
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)]}

    def _validate_data(self, data):
        if not self._safe_segment(data.get("workflow_name")):
            raise ValueError("workflow_name 必须是非空名称，不能包含路径")
        # UVManager uses workflow_name as the environment/artifact directory.
        self._contained(self.workspace / data["workflow_name"])
        nodes, edges = data.get("nodes"), data.get("edges")
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise ValueError("nodes 和 edges 必须是数组")
        version = data.get("version", 1)
        if isinstance(version, bool) or not isinstance(version, int) or version not in (1, 2):
            raise ValueError("仅支持工作流格式 version 1 或 2")

        node_ids = []
        for node in nodes:
            if not isinstance(node, dict) or not self._safe_segment(node.get("node_id")):
                raise ValueError("每个节点必须具有不含路径的非空 node_id")
            if not isinstance(node.get("node_type"), str) or not node["node_type"].strip():
                raise ValueError("每个节点必须具有非空 node_type")
            if not isinstance(node.get("config", {}), dict):
                raise ValueError("节点 config 必须是对象")
            for key in ("inputs", "outputs"):
                if not isinstance(node.get(key, []), list):
                    raise ValueError("节点 inputs 和 outputs 必须是数组")
            node_ids.append(node["node_id"])
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("node_id 不能重复")

        degree = dict.fromkeys(node_ids, 0)
        children = defaultdict(list)
        for edge in edges:
            if version == 2 and isinstance(edge, dict):
                if not all(isinstance(edge.get(key), str) for key in
                           ("from_node", "from_port", "to_node", "to_port")):
                    raise ValueError("version 2 连接必须包含节点和端口字符串")
                source, target = edge["from_node"], edge["to_node"]
            elif isinstance(edge, list) and len(edge) == 2 and all(isinstance(x, str) for x in edge):
                source, target = edge
            else:
                raise ValueError("连接格式无效")
            if source not in degree or target not in degree:
                raise ValueError("连接引用了不存在的节点")
            degree[target] += 1
            children[source].append(target)

        ready = deque(node_id for node_id in node_ids if degree[node_id] == 0)
        order = []
        while ready:
            node_id = ready.popleft()
            order.append(node_id)
            for target in children[node_id]:
                degree[target] -= 1
                if degree[target] == 0:
                    ready.append(target)
        if len(order) != len(node_ids):
            raise ValueError("工作流中存在环路")
        return order

    def run_workflow(self, path, input_data=None):
        if input_data is not None and not isinstance(input_data, dict):
            raise ValueError("input_data 必须是对象")
        with self._run_lock:
            file_path = self._workflow_path(path)
            self._validate_data(self._read_json(file_path))
            from src.core.uv_manager import UVManager
            from src.core.workflow_executor import WorkflowExecutor

            executor = WorkflowExecutor.load_workflow(
                str(file_path), uv_manager=UVManager(str(self.workspace))
            )
            if not executor.prepare_environment():
                raise RuntimeError("工作流环境准备失败，请检查 uv 和依赖安装日志")
            report = executor.execute(
                initial_data=input_data or {}, return_report=True, trigger_type="mcp"
            )
            return report

    def _runs_dir(self, path):
        data = self.get_workflow(path)["workflow"]
        name = data.get("workflow_name")
        if not self._safe_segment(name):
            raise ValueError("workflow_name 无效")
        return self._contained(self.workspace / name / "runs")

    def list_runs(self, path, limit=20):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit 必须在 1 到 100 之间")
        runs = []
        for candidate in sorted(self._runs_dir(path).glob("*/run.json"), reverse=True):
            try:
                report = self._read_json(self._contained(candidate))
                runs.append({key: report.get(key) for key in (
                    "run_id", "workflow_name", "success", "started_at",
                    "finished_at", "duration_ms", "error", "failed_node_id",
                )})
            except (OSError, ValueError):
                continue
            if len(runs) == limit:
                break
        return {"runs": runs}

    def _run_file(self, path, run_id, filename):
        if not self._safe_segment(run_id):
            raise ValueError("run_id 必须是不含路径的非空标识")
        file_path = self._contained(self._runs_dir(path) / run_id / filename)
        if not file_path.is_file():
            raise ValueError("运行记录或日志不存在")
        return file_path

    def get_run(self, path, run_id):
        return self._read_json(self._run_file(path, run_id, "run.json"))

    def get_run_logs(self, path, run_id, stream="stdout", offset=0, limit=200):
        if stream not in ("stdout", "stderr"):
            raise ValueError("stream 必须是 stdout 或 stderr")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset 必须是非负整数")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit 必须在 1 到 1000 之间")
        with self._run_file(path, run_id, stream + ".log").open(encoding="utf-8") as log:
            lines = list(islice(log, offset, offset + limit + 1))
        return {
            "run_id": run_id, "stream": stream, "offset": offset,
            "lines": [line.rstrip("\r\n") for line in lines[:limit]],
            "next_offset": offset + min(len(lines), limit),
            "has_more": len(lines) > limit,
        }
