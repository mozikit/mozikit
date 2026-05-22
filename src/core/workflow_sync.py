"""
GitHub 工作流同步模块
支持将工作流推送到 GitHub 仓库（私有/公开），以及从 GitHub 拉取工作流。
复用已有的 GitHub OAuth token，使用标准库 urllib，无外部依赖。
"""
import base64
import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

from src.core.config_manager import ConfigManager
from src.core.log_manager import get_logger

logger = get_logger("workflow_sync")

GITHUB_API_BASE = "https://api.github.com"


def _gh_get(url: str, token: str, timeout: int = 15) -> Tuple[int, dict]:
    """GitHub GET 请求"""
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return resp.status, body
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {}
        return e.code, body
    except Exception as e:
        return 0, {"error": str(e)}


def _gh_put(url: str, token: str, data: dict, timeout: int = 15) -> Tuple[int, dict]:
    """GitHub PUT 请求（用于创建/更新文件）"""
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"))
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.method = "PUT"
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return resp.status, body
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {}
        return e.code, body
    except Exception as e:
        return 0, {"error": str(e)}


def _gh_delete(url: str, token: str, data: dict, timeout: int = 15) -> Tuple[int, dict]:
    """GitHub DELETE 请求（用于删除文件）"""
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"))
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.method = "DELETE"
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8")) if resp.read() else {}
            return resp.status, body
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {}
        return e.code, body
    except Exception as e:
        return 0, {"error": str(e)}


def compute_blob_sha(content: str) -> str:
    """计算 GitHub blob SHA（与 GitHub API 返回的 sha 一致）

    GitHub 使用 git hash-object 算法：
    sha1("blob " + str(len(content)) + "\\0" + content)
    """
    blob = f"blob {len(content.encode('utf-8'))}\0{content}"
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def parse_repo(repo_str: str) -> Tuple[Optional[str], Optional[str]]:
    """解析 'owner/repo' 格式的仓库字符串"""
    repo_str = repo_str.strip().strip("/")
    parts = repo_str.split("/", 1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0], parts[1]
    # 尝试解析 URL 格式
    if "github.com" in repo_str:
        # https://github.com/owner/repo
        idx = repo_str.index("github.com")
        path = repo_str[idx + len("github.com"):].strip("/")
        parts = path.split("/", 1)
        if len(parts) == 2:
            return parts[0], parts[1].replace(".git", "")
    return None, None


class WorkflowSync:
    """工作流 GitHub 同步器"""

    def __init__(self, config_manager: ConfigManager):
        self._config = config_manager
        self._token = config_manager.get_github_token()
        self._owner = ""
        self._repo = ""
        self._branch = "main"
        self._path_prefix = "workflows"

    def set_repo(self, owner_repo: str, branch: str = "main", path: str = "workflows"):
        """设置目标仓库

        Args:
            owner_repo: "owner/repo" 格式的仓库标识
            branch: 分支名（默认 main）
            path: 仓库内路径前缀（默认 workflows）
        """
        owner, repo = parse_repo(owner_repo)
        if not owner or not repo:
            raise ValueError(f"无效的仓库标识: {owner_repo}，请使用 owner/repo 格式")
        self._owner = owner
        self._repo = repo
        self._branch = branch or "main"
        self._path_prefix = (path or "workflows").strip("/")

    def is_configured(self) -> bool:
        """检查同步是否已配置"""
        return bool(self._owner and self._repo and self._token)

    def get_repo_config(self) -> dict:
        """获取当前同步配置"""
        return {
            "owner": self._owner,
            "repo": self._repo,
            "branch": self._branch,
            "path_prefix": self._path_prefix,
        }

    def refresh_token(self):
        """刷新 token（从配置重新读取）"""
        self._token = self._config.get_github_token()

    # ── 核心操作 ──

    def _remote_path(self, workflow_name: str) -> str:
        """获取工作流在仓库中的远程路径"""
        return f"{self._path_prefix}/{workflow_name}/workflow.json"

    def _get_file_sha(self, remote_path: str) -> Tuple[Optional[str], Optional[str]]:
        """获取远程文件的 SHA 和 base64 内容

        Returns:
            (sha, base64_content) 或 (None, None) 表示文件不存在
        """
        url = f"{GITHUB_API_BASE}/repos/{self._owner}/{self._repo}/contents/{remote_path}?ref={self._branch}"
        status, data = _gh_get(url, self._token)
        if status == 200:
            return data.get("sha"), data.get("content")
        if status == 404:
            return None, None
        logger.warning("获取远程文件信息失败: HTTP %d, path=%s", status, remote_path)
        return None, None

    def push_workflow(self, workflow_path: str) -> Tuple[bool, str]:
        """将本地工作流推送到 GitHub

        Args:
            workflow_path: 本地 workflow.json 文件路径

        Returns:
            (success, message)
        """
        if not self.is_configured():
            return False, "同步未配置：请先设置 GitHub 仓库和 Token"

        workflow_path = Path(workflow_path)
        if not workflow_path.exists():
            return False, f"本地工作流文件不存在: {workflow_path}"

        workflow_name = workflow_path.parent.name
        remote_path = self._remote_path(workflow_name)

        try:
            with open(workflow_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return False, f"读取工作流文件失败: {e}"

        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")

        # 检查远程文件是否存在（获取 SHA）
        existing_sha, _ = self._get_file_sha(remote_path)

        # 准备提交数据
        data = {
            "message": f"sync: 更新工作流 {workflow_name}",
            "content": encoded,
            "branch": self._branch,
        }
        if existing_sha:
            data["sha"] = existing_sha

        url = f"{GITHUB_API_BASE}/repos/{self._owner}/{self._repo}/contents/{remote_path}"
        status, resp = _gh_put(url, self._token, data)

        if status in (200, 201):
            action = "推送" if existing_sha else "创建"
            return True, f"{action}成功: {workflow_name} → {self._owner}/{self._repo}/{remote_path}"
        else:
            error_msg = resp.get("message", str(resp))
            if status == 403:
                return False, f"推送被拒绝（403），请检查 Token 是否有写入权限"
            if status == 404:
                return False, f"仓库或路径不存在（404），请检查仓库地址和分支名"
            if status == 409:
                return False, f"推送冲突（409），远程文件已被修改，请先拉取最新版本"
            return False, f"推送失败 (HTTP {status}): {error_msg}"

    def pull_workflow(self, workflow_name: str, dest_dir: str) -> Tuple[bool, str]:
        """从 GitHub 拉取工作流到本地

        Args:
            workflow_name: 工作流名称
            dest_dir: 本地目标目录（工作流将写入 {dest_dir}/{workflow_name}/workflow.json）

        Returns:
            (success, message)
        """
        if not self.is_configured():
            return False, "同步未配置：请先设置 GitHub 仓库和 Token"

        remote_path = self._remote_path(workflow_name)

        sha, encoded_content = self._get_file_sha(remote_path)
        if sha is None:
            return False, f"远程工作流不存在: {remote_path}"

        try:
            content = base64.b64decode(encoded_content).decode("utf-8")
        except Exception as e:
            return False, f"解码远程文件失败: {e}"

        # 验证是否为有效的 JSON
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            return False, f"远程文件不是有效的工作流 JSON: {e}"

        # 写入本地
        target_dir = Path(dest_dir) / workflow_name
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / "workflow.json"

        try:
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            return False, f"写入本地文件失败: {e}"

        return True, f"拉取成功: {remote_path} → {target_file}"

    def delete_remote_workflow(self, workflow_name: str) -> Tuple[bool, str]:
        """删除远程工作流

        Args:
            workflow_name: 工作流名称

        Returns:
            (success, message)
        """
        if not self.is_configured():
            return False, "同步未配置：请先设置 GitHub 仓库和 Token"

        remote_path = self._remote_path(workflow_name)

        existing_sha, _ = self._get_file_sha(remote_path)
        if existing_sha is None:
            return False, f"远程工作流不存在: {remote_path}"

        data = {
            "message": f"sync: 删除工作流 {workflow_name}",
            "sha": existing_sha,
            "branch": self._branch,
        }

        url = f"{GITHUB_API_BASE}/repos/{self._owner}/{self._repo}/contents/{remote_path}"
        status, resp = _gh_delete(url, self._token, data)

        if status == 200:
            return True, f"删除成功: {remote_path}"
        else:
            error_msg = resp.get("message", str(resp))
            return False, f"删除失败 (HTTP {status}): {error_msg}"

    def check_status(self, workflow_path: str) -> dict:
        """检查工作流同步状态

        Args:
            workflow_path: 本地 workflow.json 文件路径

        Returns:
            dict: {
                "status": "identical"|"ahead"|"behind"|"diverged"|"remote_only"|"local_only"|"error",
                "local_sha": str or None,
                "remote_sha": str or None,
                "local_updated_at": str or None,
                "remote_updated_at": str or None,
                "message": str
            }
        """
        result = {
            "status": "error",
            "local_sha": None,
            "remote_sha": None,
            "local_updated_at": None,
            "remote_updated_at": None,
            "message": "",
        }

        if not self.is_configured():
            result["message"] = "同步未配置"
            return result

        workflow_path = Path(workflow_path)
        workflow_name = workflow_path.parent.name
        remote_path = self._remote_path(workflow_name)

        # 计算本地 SHA
        local_sha = None
        local_updated = None
        if workflow_path.exists():
            try:
                with open(workflow_path, "r", encoding="utf-8") as f:
                    local_content = f.read()
                local_sha = compute_blob_sha(local_content)
                data = json.loads(local_content)
                local_updated = data.get("updated_at", "")
            except Exception as e:
                result["message"] = f"读取本地文件失败: {e}"
                return result
        else:
            result["local_sha"] = None
            result["remote_sha"] = None
            result["status"] = "local_only" if self._remote_path else "local_only"
            # 这里不应该发生，因为调用者应该提供存在的文件
            result["message"] = "本地工作流文件不存在"
            return result

        # 获取远程信息
        remote_sha, encoded_content = self._get_file_sha(remote_path)
        remote_updated = None
        if encoded_content:
            try:
                remote_content = base64.b64decode(encoded_content).decode("utf-8")
                remote_data = json.loads(remote_content)
                remote_updated = remote_data.get("updated_at", "")
            except Exception:
                pass

        result["local_sha"] = local_sha
        result["remote_sha"] = remote_sha
        result["local_updated_at"] = local_updated
        result["remote_updated_at"] = remote_updated

        if remote_sha is None:
            result["status"] = "local_only"
            result["message"] = "仅在本地存在，远程不存在"
        elif local_sha == remote_sha:
            result["status"] = "identical"
            result["message"] = "本地与远程一致"
        else:
            # 无法精确判断 ahead/behind，显示已不同
            result["status"] = "diverged"
            result["message"] = "本地与远程内容不同"

        return result

    def list_remote_workflows(self) -> Tuple[bool, List[dict]]:
        """列出远程仓库中的工作流

        Returns:
            (success, workflows): workflows 是列表，每项包含 name, sha, updated_at
        """
        if not self.is_configured():
            return False, []

        # 列出路径下的目录
        url = f"{GITHUB_API_BASE}/repos/{self._owner}/{self._repo}/contents/{self._path_prefix}?ref={self._branch}"
        status, data = _gh_get(url, self._token)

        if status != 200:
            if status == 404:
                # 路径不存在，可能是空仓库
                return True, []
            logger.warning("列出远程工作流失败: HTTP %d", status)
            return False, []

        workflows = []
        for entry in data:
            if entry.get("type") != "dir":
                continue
            dir_name = entry["name"]
            # 检查目录下是否有 workflow.json
            wf_url = f"{self._path_prefix}/{dir_name}/workflow.json"
            sha, _ = self._get_file_sha(f"{self._path_prefix}/{dir_name}/workflow.json")
            if sha:
                workflows.append({
                    "name": dir_name,
                    "sha": sha,
                    "path": wf_url,
                })

        return True, workflows
