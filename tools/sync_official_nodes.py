#!/usr/bin/env python3
"""
官方节点快照同步脚本

从官方节点仓库（或配置的镜像源）拉取远程 manifest 与各节点当前版本文件，
生成项目根目录 official_nodes/ 快照，随主程序打包作为离线/首启兜底。

用法:
    python tools/sync_official_nodes.py [--source <url>] [--output <dir>]

源地址优先级: --source > MOZIKIT_OFFICIAL_NODES_URL > ConfigManager 配置 > 默认官方仓库
（与 NodeRepoManager.resolve_official_repo_url 保持一致）

设计说明:
- 复用 NodeRepoManager 的 _gh_get / _download_file 与 compute_content_hash 逻辑，
  不引入新依赖。
- 生成的 manifest.json 记录 repo_name / repo_url / repo_version / snapshot_commit /
  app_min_version / nodes，可据此重建同一快照。
"""

import argparse
import base64
import json
import shutil
import sys
from pathlib import Path

# 允许从仓库根目录导入 src 包（脚本位于 tools/ 下）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.code_safety import compute_content_hash  # noqa: E402
from src.core.node_repo_manager import (  # noqa: E402
    NodeRepoManager,
    RemoteManifest,
    _gh_get,
)
from src.core.node_version_manager import NodeVersionManager  # noqa: E402

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "official_nodes"


def resolve_source_url(cli_source: str) -> str:
    """解析源地址: --source > MOZIKIT_OFFICIAL_NODES_URL > 配置/默认"""
    if cli_source and cli_source.strip():
        return cli_source.strip()
    # 复用 NodeRepoManager 的解析逻辑（环境变量 > ConfigManager > 默认）
    return NodeRepoManager(Path("user_data")).resolve_official_repo_url()


def fetch_remote_manifest(owner_repo: str) -> RemoteManifest:
    """拉取远程 manifest.json（复用 _gh_get）"""
    status, data = _gh_get(
        f"{NodeRepoManager.GITHUB_API_BASE}/repos/{owner_repo}/contents/manifest.json"
    )
    if status != 200:
        raise RuntimeError(f"获取远程 manifest.json 失败: HTTP {status}")
    content = base64.b64decode(data["content"]).decode("utf-8")
    return RemoteManifest.from_dict(json.loads(content))


def normalize_hash(declared: str) -> str:
    """去除哈希声明中的算法前缀（如 "sha256:abc" -> "abc"）"""
    return declared.split(":", 1)[-1].strip().lower()


def sync_snapshot(source_url: str, output_dir: Path) -> Path:
    """执行快照同步，返回生成的 manifest 路径"""
    owner_repo = NodeRepoManager._parse_github_url(source_url)
    if not owner_repo:
        raise RuntimeError(f"无法解析仓库 URL: {source_url}")

    print(f"[sync] 源仓库: {source_url}")
    remote = fetch_remote_manifest(owner_repo)

    # 清理已被远程移除的节点目录，避免快照残留过期节点
    if output_dir.exists():
        for node_dir in output_dir.iterdir():
            if node_dir.is_dir() and node_dir.name not in remote.nodes:
                print(f"[sync] 清理过期节点: {node_dir.name}")
                shutil.rmtree(node_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    vm = NodeVersionManager(output_dir)
    mgr = NodeRepoManager(Path("user_data"))

    for node_type, node_info in sorted(remote.nodes.items()):
        version = node_info.latest_version()
        if not version:
            print(f"[sync] 跳过 {node_type}: 无可用版本")
            continue
        remote_version = node_info.get_version(version)
        if not remote_version:
            continue

        version_dir = vm.create_version_dir(node_type, version)
        for filename, file_info in remote_version.files.items():
            print(f"[sync] 下载 {node_type}@{version}/{filename}")
            content = mgr._download_file(owner_repo, node_type, version, filename)
            if content is None:
                raise RuntimeError(f"下载失败: {node_type}@{version}/{filename}")

            # 校验清单声明的哈希（不匹配仅告警，不中断）
            declared_hash = ""
            if isinstance(file_info, dict):
                declared_hash = normalize_hash(str(file_info.get("hash", "") or ""))
            if declared_hash and compute_content_hash(content) != declared_hash:
                print(
                    f"[sync] [WARNING] {filename} 哈希不匹配: "
                    f"声明 {declared_hash}, 实际 "
                    f"{compute_content_hash(content)}"
                )

            if filename == "node.json":
                try:
                    content = json.dumps(
                        json.loads(content), ensure_ascii=False, indent=2
                    )
                except Exception:
                    pass
            (version_dir / filename).write_text(content, encoding="utf-8")

        vm.set_current_version(node_type, version)
        print(f"[sync] {node_type}@{version} -> current")

    # 生成快照 manifest（记录实际使用的源地址，镜像时指向镜像自身）
    manifest = remote.to_dict()
    manifest["repo_url"] = source_url
    manifest["snapshot_commit"] = remote.snapshot_commit
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return manifest_path


def main():
    parser = argparse.ArgumentParser(description="同步官方节点快照")
    parser.add_argument(
        "--source",
        "-s",
        default="",
        help="官方节点仓库地址（默认: MOZIKIT_OFFICIAL_NODES_URL 或配置文件）",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=str(DEFAULT_OUTPUT_DIR),
        help="快照输出目录（默认: 项目根 official_nodes/）",
    )
    args = parser.parse_args()

    try:
        source_url = resolve_source_url(args.source)
        output_dir = Path(args.output).resolve()
        manifest_path = sync_snapshot(source_url, output_dir)
        print(f"[sync] 快照生成完成: {manifest_path}")
    except Exception as e:
        print(f"[sync] [ERROR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
