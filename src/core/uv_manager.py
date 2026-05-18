"""
UV环境管理器
管理每个工作流的Python虚拟环境（使用uv的共享缓存）
"""
import os
import sys
import subprocess
import json
from pathlib import Path
from typing import Optional, List
from src.core.log_manager import get_logger
from src.core import resolve_workspace

logger = get_logger("uv_manager")


class UVManager:
    """UV虚拟环境管理器"""
    
    def __init__(self, workspace_root: str = None):
        """
        初始化UV管理器
        
        Args:
            workspace_root: 工作空间根目录，默认为 ./workflows
        """
        if workspace_root is None:
            workspace_root = str(resolve_workspace())
        
        self.workspace_root = Path(workspace_root)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.custom_uv_path = None
        self.custom_mirror = None
        self._load_mirror_config()
    
    def get_workflow_dir(self, workflow_name: str) -> Path:
        """获取工作流目录"""
        workflow_dir = self.workspace_root / workflow_name
        workflow_dir.mkdir(parents=True, exist_ok=True)
        return workflow_dir
    
    def get_venv_path(self, workflow_name: str) -> Path:
        """获取虚拟环境路径"""
        return self.get_workflow_dir(workflow_name) / ".venv"
    
    def create_workflow_env(self, workflow_name: str, python_version: str = None) -> bool:
        """
        为工作流创建UV虚拟环境（使用共享缓存）
        
        Args:
            workflow_name: 工作流名称
            python_version: Python版本，如 "3.11"
        
        Returns:
            是否创建成功
        """
        workflow_dir = self.get_workflow_dir(workflow_name)
        venv_path = self.get_venv_path(workflow_name)
        
        # 如果已存在，跳过创建
        if venv_path.exists():
            logger.info("虚拟环境已存在: %s", venv_path)
            return True
        
        # 获取uv可执行文件路径
        uv_path = self.get_preferred_uv_path()
        if not uv_path:
            logger.error("未找到uv命令，请先安装uv")
            return False
        
        if os.name == 'nt':
            creationflags = 0x08000000  # CREATE_NO_WINDOW
        else:
            creationflags = 0
            
        try:
            # 使用 uv venv 创建虚拟环境（自动使用共享缓存）
            cmd = [uv_path, "venv", str(venv_path)]
            if python_version:
                cmd.extend(["--python", python_version])
            
            result = subprocess.run(
                cmd,
                cwd=str(workflow_dir),
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=60,
                creationflags=creationflags
            )
            
            if result.returncode == 0:
                logger.info("成功创建虚拟环境: %s", venv_path)
                return True
            else:
                logger.error("创建虚拟环境失败: %s", result.stderr)
                return False
                
        except Exception as e:
            logger.error("创建虚拟环境时出错: %s", e)
            return False
    
    def install_packages(self, workflow_name: str, packages: List[str]) -> bool:
        """
        在工作流环境中安装包（使用共享缓存）
        
        Args:
            workflow_name: 工作流名称
            packages: 包列表
        
        Returns:
            是否安装成功
        """
        venv_path = self.get_venv_path(workflow_name)
        
        if not venv_path.exists():
            logger.error("虚拟环境不存在: %s", venv_path)
            return False
        
        if not packages:
            return True
        
        # 获取uv可执行文件路径
        uv_path = self.get_preferred_uv_path()
        if not uv_path:
            logger.error("未找到uv命令，请先安装uv")
            return False
        
        if os.name == 'nt':
            creationflags = 0x08000000  # CREATE_NO_WINDOW
        else:
            creationflags = 0
            
        try:
            # 使用 uv pip install 安装包（自动使用共享缓存）
            python_exe = self._get_python_executable(workflow_name)
            
            for package in packages:
                cmd = [uv_path, "pip", "install", package, "--python", str(python_exe)]
                
                # 如果配置了镜像，添加镜像参数
                current_mirror = self.get_current_mirror()
                if current_mirror:
                    cmd.extend(["--index-url", current_mirror])
                    logger.info("使用镜像: %s", current_mirror)
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    timeout=300,
                    creationflags=creationflags
                )
                
                if result.returncode != 0:
                    logger.error("安装包 %s 失败: %s", package, result.stderr)
                    return False
                else:
                    logger.info("成功安装: %s", package)
            
            return True
            
        except Exception as e:
            logger.error("安装包时出错: %s", e)
            return False
            
    def _get_python_executable(self, workflow_name: str) -> Path:
        """获取虚拟环境中的Python可执行文件路径"""
        venv_path = self.get_venv_path(workflow_name)
        
        if os.name == 'nt':  # Windows
            python_exe = venv_path / "Scripts" / "python.exe"
        else:  # Unix-like
            python_exe = venv_path / "bin" / "python"
            
        # 在冻结状态下（打包后），如果虚拟环境不存在，不能回退到 sys.executable
        # 因为 sys.executable 是主程序 exe，会导致无限递归启动窗口
        if getattr(sys, 'frozen', False):
            if not python_exe.exists():
                logger.error("致命错误: 虚拟环境未找到且处于打包模式: %s", python_exe)
                # 这里我们返回一个不存在的路径，让后续调用失败而不是启动exe
                return python_exe
        
        return python_exe
    
    def run_python_script(
        self,
        workflow_name: str,
        script_path: str,
        input_data: dict = None,
        timeout: int = 300
    ) -> dict:
        """
        在工作流环境中运行Python脚本
        
        Args:
            workflow_name: 工作流名称
            script_path: 脚本路径
            input_data: 输入数据（将通过stdin传递）
            timeout: 超时时间（秒）
        
        Returns:
            执行结果字典 {success, output, error, data}
        """
        python_exe = self._get_python_executable(workflow_name)
        
        # 如果虚拟环境不存在，使用当前Python
        if not python_exe.exists():
            if getattr(sys, 'frozen', False):
                return {
                    "success": False,
                    "output": "",
                    "error": f"致命错误: 虚拟环境未找到({python_exe})且处于打包模式，无法执行脚本",
                    "data": None
                }
            logger.info("虚拟环境不存在，使用当前Python: %s", sys.executable)
            python_exe = Path(sys.executable)
        
        if os.name == 'nt':
            creationflags = 0x08000000  # CREATE_NO_WINDOW
        else:
            creationflags = 0
            
        try:
            # 准备输入数据
            input_json = json.dumps(input_data) if input_data else ""
            
            # 运行脚本
            result = subprocess.run(
                [str(python_exe), script_path],
                input=input_json,
                errors='replace',
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=timeout,
                creationflags=creationflags
            )
            
            # 解析输出
            success = result.returncode == 0
            output = result.stdout
            error = result.stderr
            
            # 尝试从输出中提取JSON数据
            data = None
            if success and output:
                try:
                    # 查找JSON标记
                    if "###JSON_OUTPUT###" in output:
                        json_start = output.find("###JSON_OUTPUT###") + len("###JSON_OUTPUT###")
                        json_end = output.find("###JSON_OUTPUT_END###")
                        if json_end != -1:
                            json_str = output[json_start:json_end].strip()
                            data = json.loads(json_str)
                except Exception as e:
                    logger.error("解析输出JSON失败: %s", e)
            
            return {
                "success": success,
                "output": output,
                "error": error,
                "data": data
            }
            
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "output": "",
                "error": f"脚本执行超时（{timeout}秒）",
                "data": None
            }
        except Exception as e:
            return {
                "success": False,
                "output": "",
                "error": f"执行脚本时出错: {e}",
                "data": None
            }
    
    def run_python_script_streaming(
        self,
        workflow_name: str,
        script_path: str,
        input_data: dict = None,
        timeout: int = 300,
        progress_callback=None,
        log_callback=None,
    ) -> dict:
        """
        在工作流环境中运行Python脚本（流式读取，支持进度回调）

        Args:
            workflow_name: 工作流名称
            script_path: 脚本路径
            input_data: 输入数据（将通过stdin传递）
            timeout: 超时时间（秒）
            progress_callback: 进度回调函数 callback(percent, message)
            log_callback: 实时日志回调函数 callback(line)

        Returns:
            执行结果字典 {success, output, error, data}
        """
        python_exe = self._get_python_executable(workflow_name)

        if not python_exe.exists():
            if getattr(sys, 'frozen', False):
                return {
                    "success": False,
                    "output": "",
                    "error": f"致命错误: 虚拟环境未找到({python_exe})且处于打包模式，无法执行脚本",
                    "data": None
                }
            python_exe = Path(sys.executable)

        if os.name == 'nt':
            creationflags = 0x08000000
        else:
            creationflags = 0

        try:
            input_json = json.dumps(input_data) if input_data else ""

            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            process = subprocess.Popen(
                [str(python_exe), script_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                encoding='utf-8',
                errors='replace',
                env=env,
                creationflags=creationflags,
            )

            if input_json:
                process.stdin.write(input_json)
                process.stdin.flush()
            process.stdin.close()

            import threading
            import time

            stdout_lines = []
            stderr_lines = []

            def _read_stdout():
                try:
                    for line in process.stdout:
                        if "###PROGRESS##" in line:
                            if progress_callback:
                                try:
                                    progress_json = line.split("###PROGRESS##", 1)[1].strip()
                                    progress_data = json.loads(progress_json)
                                    progress_callback(
                                        progress_data.get("percent", 0),
                                        progress_data.get("message", ""),
                                    )
                                except Exception:
                                    pass
                        elif "###LOG##" in line:
                            stdout_lines.append(line)
                            if log_callback:
                                try:
                                    log_line = line.split("###LOG##", 1)[1].rstrip('\n')
                                    log_callback(log_line)
                                except Exception:
                                    pass
                        elif "###JSON_OUTPUT###" in line or "###JSON_OUTPUT_END###" in line:
                            stdout_lines.append(line)
                        else:
                            stdout_lines.append(line)
                            if log_callback:
                                try:
                                    log_callback(line.rstrip('\n'))
                                except Exception:
                                    pass
                except Exception:
                    pass

            def _read_stderr():
                try:
                    for line in process.stderr:
                        stderr_lines.append(line)
                except Exception:
                    pass

            stdout_thread = threading.Thread(target=_read_stdout, daemon=True)
            stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
            stdout_thread.start()
            stderr_thread.start()

            process.wait(timeout=timeout)
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)

            success = process.returncode == 0
            output = "".join(stdout_lines)
            error = "".join(stderr_lines)

            data = None
            if success and output:
                try:
                    if "###JSON_OUTPUT###" in output:
                        json_start = output.find("###JSON_OUTPUT###") + len("###JSON_OUTPUT###")
                        json_end = output.find("###JSON_OUTPUT_END###")
                        if json_end != -1:
                            json_str = output[json_start:json_end].strip()
                            data = json.loads(json_str)
                except Exception as e:
                    logger.error("解析输出JSON失败: %s", e)

            return {
                "success": success,
                "output": output,
                "error": error,
                "data": data
            }

        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            return {
                "success": False,
                "output": "",
                "error": f"脚本执行超时（{timeout}秒）",
                "data": None
            }
        except Exception as e:
            return {
                "success": False,
                "output": "",
                "error": f"执行脚本时出错: {e}",
                "data": None
            }

    def delete_workflow_env(self, workflow_name: str) -> bool:
        """删除工作流环境"""
        import shutil
        
        venv_path = self.get_venv_path(workflow_name)
        
        if venv_path.exists():
            try:
                shutil.rmtree(venv_path)
                logger.info("已删除虚拟环境: %s", venv_path)
                return True
            except Exception as e:
                logger.error("删除虚拟环境失败: %s", e)
                return False
        
        return True
    
    def check_uv_installed(self) -> bool:
        """检查uv是否已安装"""
        uv_paths = self.find_uv_installations()
        return len(uv_paths) > 0

    def create_environment(self, name: str, python_version: str = "3.12") -> bool:
        """创建独立虚拟环境（CLI 使用）

        Args:
            name: 环境名称
            python_version: Python 版本号

        Returns:
            是否成功
        """
        return self.create_workflow_env(name, python_version)

    def remove_environment(self, name: str) -> bool:
        """删除独立虚拟环境（CLI 使用）

        Args:
            name: 环境名称

        Returns:
            是否成功
        """
        return self.delete_workflow_env(name)

    def list_environments(self) -> List[dict]:
        """列出所有虚拟环境（CLI 使用）

        扫描 workflows/ 下包含 .venv 的目录作为环境列表。

        Returns:
            环境信息列表: [{"name": str, "python_version": str, "path": str}, ...]
        """
        envs = []
        if not self.workspace_root.exists():
            return envs

        for child in self.workspace_root.iterdir():
            if not child.is_dir():
                continue
            venv_path = child / ".venv"
            if not venv_path.exists():
                continue
            # 尝试读取 Python 版本
            python_version = "unknown"
            cfg_file = venv_path / "pyvenv.cfg"
            if cfg_file.exists():
                try:
                    for line in cfg_file.read_text().splitlines():
                        if line.startswith("version ="):
                            python_version = line.split("=", 1)[1].strip()
                            break
                except Exception:
                    pass
            envs.append({
                "name": child.name,
                "python_version": python_version,
                "path": str(venv_path),
            })

        return envs

    def find_uv_installations(self) -> List[str]:
        """
        查找系统中所有可用的uv安装路径
        
        Returns:
            可用的uv可执行文件路径列表
        """
        uv_paths = []
        
        if os.name == 'nt':
            creationflags = 0x08000000  # CREATE_NO_WINDOW
        else:
            creationflags = 0

        # 1. 首先检查PATH中的uv命令
        try:
            result = subprocess.run(
                ["where" if os.name == 'nt' else "which", "uv"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=creationflags
            )
            if result.returncode == 0:
                # where/which 可能返回多个路径
                paths = [path.strip() for path in result.stdout.strip().split('\n') if path.strip()]
                uv_paths.extend(paths)
        except:
            pass
        
        # 2. 检查常见的安装位置
        common_paths = self._get_common_uv_paths()
        
        for path in common_paths:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                if path not in uv_paths:
                    uv_paths.append(path)
        
        # 3. 验证每个找到的uv是否真的可用
        valid_uv_paths = []
        for uv_path in uv_paths:
            if self._verify_uv_executable(uv_path):
                valid_uv_paths.append(uv_path)
        
        return valid_uv_paths
    
    def _get_common_uv_paths(self) -> List[str]:
        """获取常见的uv安装路径"""
        paths = []
        
        if os.name == 'nt':  # Windows
            # 用户级别安装
            local_app_data = os.environ.get('LOCALAPPDATA', '')
            if local_app_data:
                paths.extend([
                    os.path.join(local_app_data, 'uv', 'uv.exe'),
                    os.path.join(local_app_data, 'uv', 'bin', 'uv.exe'),
                    os.path.join(local_app_data, 'Programs', 'uv', 'uv.exe'),
                ])
            
            # 系统级别安装
            program_files = os.environ.get('ProgramFiles', 'C:\\Program Files')
            program_files_x86 = os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)')
            
            paths.extend([
                os.path.join(program_files, 'uv', 'uv.exe'),
                os.path.join(program_files, 'uv', 'bin', 'uv.exe'),
                os.path.join(program_files_x86, 'uv', 'uv.exe'),
                os.path.join(program_files_x86, 'uv', 'bin', 'uv.exe'),
            ])
            
            # Python Scripts 目录
            python_scripts = os.path.join(os.path.dirname(sys.executable), 'Scripts')
            paths.append(os.path.join(python_scripts, 'uv.exe'))
            
            # 当前用户的Python Scripts目录
            try:
                import site
                user_scripts = os.path.join(site.USER_BASE, 'Scripts') if site.USER_BASE else ''
                if user_scripts:
                    paths.append(os.path.join(user_scripts, 'uv.exe'))
            except:
                pass
        
        else:  # Unix-like (Linux, macOS)
            # 用户级别安装
            home = os.path.expanduser('~')
            paths.extend([
                os.path.join(home, '.local', 'bin', 'uv'),
                os.path.join(home, '.cargo', 'bin', 'uv'),
                os.path.join(home, 'bin', 'uv'),
            ])
            
            # 系统级别安装
            paths.extend([
                '/usr/local/bin/uv',
                '/usr/bin/uv',
                '/opt/uv/bin/uv',
            ])
            
            # Python 用户base
            try:
                import site
                if site.USER_BASE:
                    paths.append(os.path.join(site.USER_BASE, 'bin', 'uv'))
            except:
                pass
        
        return [p for p in paths if os.path.exists(p)]
    
    def _verify_uv_executable(self, uv_path: str) -> bool:
        """验证uv可执行文件是否可用"""
        if os.name == 'nt':
            creationflags = 0x08000000  # CREATE_NO_WINDOW
        else:
            creationflags = 0
            
        try:
            result = subprocess.run(
                [uv_path, '--version'],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=creationflags
            )
            return result.returncode == 0
        except:
            return False
    
    def get_preferred_uv_path(self, selected_path: str = None) -> Optional[str]:
        """
        获取首选的uv路径
        
        Args:
            selected_path: 用户选择的uv路径，如果提供则优先使用
        
        Returns:
            首选的uv可执行文件路径，如果没有找到则返回None
        """
        # 如果用户指定了路径，验证并使用
        if selected_path and os.path.isfile(selected_path) and self._verify_uv_executable(selected_path):
            return selected_path
        
        # 如果有自定义路径，优先使用
        if self.custom_uv_path and os.path.isfile(self.custom_uv_path) and self._verify_uv_executable(self.custom_uv_path):
            return self.custom_uv_path
        
        uv_paths = self.find_uv_installations()
        if not uv_paths:
            return None
        
        if os.name == 'nt':
            creationflags = 0x08000000  # CREATE_NO_WINDOW
        else:
            creationflags = 0

        # 优先选择PATH中的uv（通常是第一个）
        try:
            result = subprocess.run(
                ["where" if os.name == 'nt' else "which", "uv"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=creationflags
            )
            if result.returncode == 0:
                primary_path = result.stdout.strip().split('\n')[0].strip()
                if primary_path in uv_paths:
                    return primary_path
        except:
            pass
        
        # 如果PATH中的不可用，返回第一个找到的
        return uv_paths[0]
    
    def set_custom_uv_path(self, uv_path: str) -> bool:
        """
        设置自定义的uv路径
        
        Args:
            uv_path: uv可执行文件路径
        
        Returns:
            是否设置成功
        """
        if os.path.isfile(uv_path) and self._verify_uv_executable(uv_path):
            self.custom_uv_path = uv_path
            return True
        return False
    
    def set_custom_mirror(self, mirror_url: str) -> bool:
        """
        设置自定义镜像地址
        
        Args:
            mirror_url: 镜像地址
        
        Returns:
            是否设置成功
        """
        self.custom_mirror = mirror_url
        self._save_mirror_config()
        return True
    
    def _load_mirror_config(self):
        """加载镜像配置"""
        # 检查配置文件
        config_file = os.path.join(os.path.expanduser("~"), ".uv", "uv.toml")
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                import re
                match = re.search(r'index-url\s*=\s*"([^"]+)"', content)
                if match:
                    self.custom_mirror = match.group(1)
                    return
            except:
                pass
        
        # 检查环境变量
        env_mirror = os.environ.get("UV_INDEX_URL", "")
        if env_mirror:
            self.custom_mirror = env_mirror
    
    def _save_mirror_config(self):
        """保存镜像配置（异步，原子写入）"""
        if not self.custom_mirror:
            return
        os.environ["UV_INDEX_URL"] = self.custom_mirror
        mirror = self.custom_mirror

        def _do():
            try:
                from src.core._file_utils import atomic_write
                config_dir = Path.home() / ".uv"
                config_dir.mkdir(parents=True, exist_ok=True)
                config_file = config_dir / "uv.toml"
                content = config_file.read_text("utf-8") if config_file.exists() else ""
                import re
                if "[pip]" in content:
                    content = re.sub(
                        r'index-url\s*=\s*".*?"',
                        f'index-url = "{mirror}"',
                        content,
                    )
                else:
                    if content and not content.endswith("\n"):
                        content += "\n"
                    content += f'[pip]\nindex-url = "{mirror}"\n'
                atomic_write(config_file, content)
            except Exception as e:
                logger.error("保存镜像配置时出错: %s", e)

        import threading
        threading.Thread(target=_do, daemon=True).start()
    
    def get_current_mirror(self) -> str:
        """获取当前使用的镜像地址"""
        if self.custom_mirror:
            return self.custom_mirror
        return os.environ.get("UV_INDEX_URL", "")

    def start_worker(self, workflow_name: str, timeout: int = 15) -> Optional[subprocess.Popen]:
        """
        启动工作流工作进程
        
        Args:
            workflow_name: 工作流名称
            timeout: 启动超时时间
            
        Returns:
            进程对象，失败返回None
        """
        python_exe = self._get_python_executable(workflow_name)
        
        # 如果虚拟环境不存在，使用当前Python
        if not python_exe.exists():
            logger.error("虚拟环境不存在: %s", python_exe)
            return None
            
        # 获取Runner脚本
        if getattr(sys, 'frozen', False):
            # 打包运行模式
            base_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
            runner_script = Path(base_dir) / "src" / "core" / "workflow_runner.py"
        else:
            # 源码运行模式
            runner_script = Path(__file__).parent / "workflow_runner.py"
            
        if not runner_script.exists():
            logger.error("Runner脚本不存在: %s", runner_script)
            return None
            
        try:
            # 设置环境变量强制使用UTF-8
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            
            if os.name == 'nt':
                creationflags = 0x08000000  # CREATE_NO_WINDOW
            else:
                creationflags = 0

            # 启动进程
            process = subprocess.Popen(
                [str(python_exe), str(runner_script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  #行缓冲
                encoding='utf-8',
                errors='replace',  # 忽略无法解码的字符
                env=env,
                creationflags=creationflags
            )
            
            # 等待READY信号
            import time
            start_time = time.time()
            while time.time() - start_time < timeout:
                if process.poll() is not None:
                    logger.error("Worker进程提前退出，退出码: %s", process.returncode)
                    return None
                    
                line = process.stdout.readline()
                if line and "READY" in line:
                    return process
                time.sleep(0.1)
                
            process.kill()
            logger.error("Worker进程启动超时")
            return None
            
        except Exception as e:
            logger.error("启动Worker失败: %s", e)
            return None

    def send_command_to_worker(self, process: subprocess.Popen, command: dict, timeout: int = 300, progress_callback=None, log_callback=None) -> dict:
        """
        向Worker发送命令并等待结果
        
        Args:
            process: Worker进程对象
            command: 命令字典
            timeout: 超时时间
            progress_callback: 进度回调函数 callback(percent, message)
            log_callback: 实时日志回调函数 callback(line)
            
        Returns:
            执行结果
        """
        if process.poll() is not None:
            return {"success": False, "error": "Worker进程已结束"}
            
        try:
            cmd_str = json.dumps(command, ensure_ascii=False) + "\n"
            process.stdin.write(cmd_str)
            process.stdin.flush()
            
            import time
            start_time = time.time()
            output_buffer = []
            json_started = False
            
            while time.time() - start_time < timeout:
                if process.poll() is not None:
                    error = process.stderr.read() if process.stderr else "未知错误"
                    return {"success": False, "error": f"Worker进程异常退出: {error}"}
                
                line = process.stdout.readline()
                if not line:
                    continue
                
                if "###PROGRESS##" in line:
                    if progress_callback:
                        try:
                            progress_json = line.split("###PROGRESS##", 1)[1].strip()
                            progress_data = json.loads(progress_json)
                            progress_callback(
                                progress_data.get("percent", 0),
                                progress_data.get("message", ""),
                            )
                        except Exception:
                            pass
                    continue

                if "###LOG##" in line:
                    if log_callback:
                        try:
                            log_line = line.split("###LOG##", 1)[1].rstrip('\n')
                            log_callback(log_line)
                        except Exception:
                            pass
                    continue
                    
                if "###JSON_OUTPUT###" in line:
                    json_started = True
                    continue
                    
                if "###JSON_OUTPUT_END###" in line:
                    try:
                        json_str = "".join(output_buffer).strip()
                        return json.loads(json_str)
                    except Exception as e:
                        return {"success": False, "error": f"解析JSON失败: {e}"}
                
                if json_started:
                    output_buffer.append(line)
            
            return {"success": False, "error": "等待Worker响应超时"}
            
        except Exception as e:
            return {"success": False, "error": f"与Worker通信失败: {e}"}
