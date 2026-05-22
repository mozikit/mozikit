"""
配置管理类
用于保存和恢复应用程序的各种设置和状态
"""

import json
import os
from pathlib import Path

from src.core.credential_store import (
    delete_credential,
    retrieve_credential,
    store_credential,
)
from src.core.log_manager import get_logger

logger = get_logger("config_manager")


class ConfigManager:
    """配置管理器"""

    DEFAULT_AI_SETTINGS = {
        "provider_type": "openai_compatible",
        "base_url": "",
        "api_key": "",
        "model": "",
        "timeout_seconds": 60,
        "temperature": 0.2,
        "max_history_rounds": 20,
    }

    DEFAULT_GITHUB_SETTINGS = {
        "token": "",
        "username": "",
        "connected": False,
    }

    _CREDENTIAL_VERSION_KEY = "credential_store_version"
    _CREDENTIAL_VERSION_CURRENT = 2

    def _skip_legacy_decrypt(self) -> bool:
        """凭证存储版本 >= 2 时跳过旧的 XOR/明文解密路径"""
        return self.config.get(self._CREDENTIAL_VERSION_KEY, 0) >= 2

    def _mark_credential_version(self):
        """标记凭证存储版本为当前版本"""
        if self.config.get(self._CREDENTIAL_VERSION_KEY, 0) < self._CREDENTIAL_VERSION_CURRENT:
            self.config[self._CREDENTIAL_VERSION_KEY] = self._CREDENTIAL_VERSION_CURRENT

    DEFAULT_SYNC_SETTINGS = {
        "default_repo": "",
        "default_branch": "main",
        "sync_path": "workflows",
    }

    DEFAULT_NODE_REPO_SETTINGS = {
        "official_repo_url": "https://github.com/localflow-app/localflow-official-nodes",
        "auto_check_updates": True,
        "last_check_version": "",
        "last_check_time": "",
    }

    # 默认节点版本策略
    # "latest": 使用最新版本（当前默认）
    # "current": 使用 current 链接指向的版本
    # "prompt": 提示用户选择
    DEFAULT_NODE_VERSION_POLICY = "latest"

    # ── 旧加密方法（已弃用，保留仅为向后兼容读取旧格式数据） ──
    # 新的凭证存储使用 credential_store 模块（操作系统密钥链 + PBKDF2 加密）
    _MACHINE_KEY = None

    def __init__(self, config_file="config.json"):
        self.config_file = Path(config_file)
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """加载配置文件"""
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("加载配置文件失败: %s", e)
                return {}
        return {}

    def save_config(self):
        """保存配置文件（异步，原子写入）"""
        from src.core._file_utils import atomic_write_json
        atomic_write_json(self.config_file, self.config.copy())

    def save_config_sync(self):
        """同步保存配置文件（用于关闭窗口等需要等待保存完成的场景）"""
        from src.core._file_utils import atomic_write_json_sync
        atomic_write_json_sync(self.config_file, self.config)

    def get_dock_state(self, dock_name: str) -> dict:
        """获取dock窗口状态

        Args:
            dock_name: dock窗口名称

        Returns:
            dict: 包含 visible/width/height 的状态信息
        """
        return self.config.get("dock_states", {}).get(
            dock_name, {"visible": False, "width": 300, "height": 240}
        )

    def set_dock_state(
        self,
        dock_name: str,
        visible: bool = None,
        width: int = None,
        height: int = None,
    ):
        """设置dock窗口状态

        Args:
            dock_name: dock窗口名称
            visible: 可见性
            width: 宽度
            height: 高度
        """
        if "dock_states" not in self.config:
            self.config["dock_states"] = {}

        if dock_name not in self.config["dock_states"]:
            self.config["dock_states"][dock_name] = {
                "visible": False,
                "width": 300,
                "height": 240,
            }

        if visible is not None:
            self.config["dock_states"][dock_name]["visible"] = visible

        if width is not None:
            self.config["dock_states"][dock_name]["width"] = width

        if height is not None:
            self.config["dock_states"][dock_name]["height"] = height

    def apply_dock_state(self, dock_widget, dock_name: str):
        """应用dock窗口状态

        Args:
            dock_widget: QDockWidget实例
            dock_name: dock窗口名称
        """
        state = self.get_dock_state(dock_name)

        # 应用可见性
        dock_widget.setVisible(state["visible"])

        from PySide6.QtCore import Qt

        allowed_areas = dock_widget.allowedAreas()
        if allowed_areas & (Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea):
            dock_widget.setMinimumWidth(state["width"])
            dock_widget.setMaximumWidth(state["width"] * 2)  # 允许一定程度的调整
        # 注意：对于底部 dock（执行结果面板），不应用高度设置
        # 因为主窗口已经使用 setFixedHeight 固定了高度
        # 应用高度设置会覆盖固定高度，导致撑开主窗口的问题

    def save_dock_state(self, dock_widget, dock_name: str):
        """保存dock窗口状态

        Args:
            dock_widget: QDockWidget实例
            dock_name: dock窗口名称
        """
        self.set_dock_state(
            dock_name,
            visible=dock_widget.isVisible(),
            width=dock_widget.width(),
            height=dock_widget.height(),
        )

    def get_window_geometry(self) -> dict:
        """获取窗口几何信息"""
        return self.config.get("window_geometry", {})

    def set_window_geometry(self, x: int, y: int, width: int, height: int):
        """设置窗口几何信息"""
        self.config["window_geometry"] = {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
        }

    def get_ai_settings(self) -> dict:
        """获取 AI 生成配置"""
        settings = self.config.get("ai_settings", {})
        merged = self.DEFAULT_AI_SETTINGS.copy()
        merged.update(settings)
        api_key = merged.get("api_key", "")
        if api_key:
            decrypted = retrieve_credential("ai_api_key", api_key, skip_legacy=self._skip_legacy_decrypt())
            if decrypted:
                merged["api_key"] = decrypted
        return merged

    def set_ai_settings(self, settings: dict):
        """设置 AI 生成配置"""
        merged = self.DEFAULT_AI_SETTINGS.copy()
        merged.update(settings or {})
        api_key = merged.get("api_key", "")
        if api_key:
            # 将 API 密钥安全存储，返回值写入 config.json
            merged["api_key"] = store_credential("ai_api_key", api_key)
        self.config["ai_settings"] = merged
        self._mark_credential_version()
        self.save_config()

    def get_recent_workflows(self) -> list:
        """获取最近打开的工作流"""
        return self.config.get("recent_workflows", [])

    def add_recent_workflow(self, workflow_name: str, workflow_path: str):
        """添加最近打开的工作流"""
        if "recent_workflows" not in self.config:
            self.config["recent_workflows"] = []

        # 移除已存在的记录
        self.config["recent_workflows"] = [
            w for w in self.config["recent_workflows"] if w["name"] != workflow_name
        ]

        # 添加到开头
        self.config["recent_workflows"].insert(
            0, {"name": workflow_name, "path": workflow_path}
        )

        # 限制数量
        self.config["recent_workflows"] = self.config["recent_workflows"][:10]

    # ========== 定时任务管理 ==========

    def get_scheduled_tasks(self) -> list:
        """获取所有定时任务"""
        return self.config.get("scheduled_tasks", [])

    def get_scheduled_task(self, task_id: str) -> dict:
        """获取指定定时任务"""
        for task in self.config.get("scheduled_tasks", []):
            if task.get("id") == task_id:
                return task
        return None

    def add_scheduled_task(self, task: dict) -> str:
        """添加定时任务

        Args:
            task: 任务配置 {
                "id": str,
                "workflow_name": str,
                "workflow_path": str,
                "cron_expression": str,  # Cron表达式
                "enabled": bool,
                "last_run": str,
                "next_run": str,
                "created_at": str
            }

        Returns:
            任务ID
        """
        if "scheduled_tasks" not in self.config:
            self.config["scheduled_tasks"] = []

        self.config["scheduled_tasks"].append(task)
        self.save_config()
        return task.get("id")

    def update_scheduled_task(self, task_id: str, updates: dict) -> bool:
        """更新定时任务"""
        for i, task in enumerate(self.config.get("scheduled_tasks", [])):
            if task.get("id") == task_id:
                self.config["scheduled_tasks"][i].update(updates)
                self.save_config()
                return True
        return False

    def delete_scheduled_task(self, task_id: str) -> bool:
        """删除定时任务"""
        tasks = self.config.get("scheduled_tasks", [])
        for i, task in enumerate(tasks):
            if task.get("id") == task_id:
                tasks.pop(i)
                self.config["scheduled_tasks"] = tasks
                self.save_config()
                return True
        return False

    def set_scheduled_tasks(self, tasks: list):
        """设置所有定时任务"""
        self.config["scheduled_tasks"] = tasks
        self.save_config()

    # ========== 运行历史管理 ==========

    def get_execution_history(self, workflow_name: str = None, limit: int = 50) -> list:
        """获取运行历史

        Args:
            workflow_name: 可选，筛选特定工作流的历史
            limit: 返回的最大记录数

        Returns:
            运行历史列表
        """
        history = self.config.get("execution_history", [])

        if workflow_name:
            history = [h for h in history if h.get("workflow_name") == workflow_name]

        return history[:limit]

    def add_execution_record(self, record: dict):
        """添加运行记录

        Args:
            record: 运行记录 {
                "id": str,
                "workflow_name": str,
                "workflow_path": str,
                "status": "success" | "failed" | "running",
                "started_at": str,
                "finished_at": str,
                "duration_ms": int,
                "output": dict,
                "error": str
            }
        """
        if "execution_history" not in self.config:
            self.config["execution_history"] = []

        # 添加到开头
        self.config["execution_history"].insert(0, record)

        # 限制历史记录数量（保留最近500条）
        self.config["execution_history"] = self.config["execution_history"][:500]
        self.save_config()

    def clear_execution_history(self, workflow_name: str = None):
        """清除运行历史

        Args:
            workflow_name: 可选，只清除特定工作流的历史
        """
        if workflow_name:
            history = self.config.get("execution_history", [])
            history = [h for h in history if h.get("workflow_name") != workflow_name]
            self.config["execution_history"] = history
        else:
            self.config["execution_history"] = []
        self.save_config()

    def get_execution_stats(self) -> dict:
        """获取执行统计信息"""
        history = self.config.get("execution_history", [])

        total_runs = len(history)
        successful_runs = len([h for h in history if h.get("status") == "success"])
        failed_runs = len([h for h in history if h.get("status") == "failed"])

        return {
            "total_runs": total_runs,
            "successful_runs": successful_runs,
            "failed_runs": failed_runs,
            "success_rate": (successful_runs / total_runs * 100)
            if total_runs > 0
            else 0,
        }

    # ========== GitHub 认证管理 ==========

    def get_github_settings(self) -> dict:
        """获取 GitHub 认证设置"""
        settings = self.config.get("github_settings", {})
        merged = self.DEFAULT_GITHUB_SETTINGS.copy()
        merged.update(settings)
        token = merged.get("token", "")
        if token:
            decrypted = retrieve_credential("github_token", token, skip_legacy=self._skip_legacy_decrypt())
            if decrypted:
                merged["token"] = decrypted
        return merged

    def set_github_settings(self, settings: dict):
        """设置 GitHub 认证设置"""
        merged = self.DEFAULT_GITHUB_SETTINGS.copy()
        merged.update(settings or {})
        token = merged.get("token", "")
        if token:
            # 将 Token 安全存储，返回值写入 config.json
            merged["token"] = store_credential("github_token", token)
        else:
            # 空值表示用户断开连接，删除密钥链中的凭证
            delete_credential("github_token")
        self.config["github_settings"] = merged
        self._mark_credential_version()
        self.save_config()

    def get_github_token(self) -> str:
        """获取 GitHub token"""
        return self.get_github_settings().get("token", "")

    # ========== 工作流同步设置 ==========

    def get_sync_settings(self) -> dict:
        """获取工作流同步设置"""
        settings = self.config.get("sync_settings", {})
        merged = self.DEFAULT_SYNC_SETTINGS.copy()
        merged.update(settings)
        return merged

    def set_sync_settings(self, settings: dict):
        """设置工作流同步设置"""
        merged = self.DEFAULT_SYNC_SETTINGS.copy()
        merged.update(settings or {})
        self.config["sync_settings"] = merged
        self.save_config()

    # ========== 节点仓库管理 ==========

    def get_node_repo_settings(self) -> dict:
        """获取节点仓库设置"""
        settings = self.config.get("node_repo_settings", {})
        merged = self.DEFAULT_NODE_REPO_SETTINGS.copy()
        merged.update(settings)
        return merged

    def set_node_repo_settings(self, settings: dict):
        """设置节点仓库设置"""
        merged = self.DEFAULT_NODE_REPO_SETTINGS.copy()
        merged.update(settings or {})
        self.config["node_repo_settings"] = merged
        self.save_config()

    # ========== 节点版本策略管理 ==========

    def get_node_version_policy(self) -> str:
        """获取默认节点版本策略

        Returns:
            "latest" | "current" | "prompt"
        """
        return self.config.get("node_version_policy", self.DEFAULT_NODE_VERSION_POLICY)

    def set_node_version_policy(self, policy: str):
        """设置默认节点版本策略

        Args:
            policy: "latest", "current", 或 "prompt"
        """
        if policy in ("latest", "current", "prompt"):
            self.config["node_version_policy"] = policy
            self.save_config()

    # ========== 节点执行超时管理 ==========

    DEFAULT_NODE_TIMEOUT_SECONDS = 600

    def get_node_timeout_seconds(self) -> int:
        """获取节点执行超时时间（秒）"""
        return self.config.get(
            "node_timeout_seconds", self.DEFAULT_NODE_TIMEOUT_SECONDS
        )

    def set_node_timeout_seconds(self, timeout: int):
        """设置节点执行超时时间（秒）"""
        self.config["node_timeout_seconds"] = max(10, min(3600, timeout))
        self.save_config()

    # ========== 画布缩放比例管理 ==========

    def get_canvas_zoom(self) -> float:
        """获取画布默认缩放比例"""
        return self.config.get("canvas_zoom", 1.0)

    def set_canvas_zoom(self, zoom: float):
        """设置画布默认缩放比例"""
        self.config["canvas_zoom"] = max(0.2, min(3.0, zoom))
        self.save_config()

    # ========== 表格列宽管理 ==========

    def get_table_column_widths(self, table_key: str) -> dict:
        """获取指定表格的列宽配置

        Args:
            table_key: 表格标识键

        Returns:
            dict: {列索引: 列宽} 的字典
        """
        return self.config.get("table_column_widths", {}).get(table_key, {})

    def set_table_column_widths(self, table_key: str, widths: dict):
        """设置指定表格的列宽配置

        Args:
            table_key: 表格标识键
            widths: {列索引: 列宽} 的字典
        """
        if "table_column_widths" not in self.config:
            self.config["table_column_widths"] = {}
        self.config["table_column_widths"][table_key] = widths
        self.save_config()
