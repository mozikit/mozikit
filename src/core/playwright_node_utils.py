"""
Playwright 脚本节点辅助工具
"""
import json
import re
from typing import Dict, List


PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
PLAYWRIGHT_RUNTIME_FIELDS = (
    "playwright_headless",
    "playwright_timeout_seconds",
    "playwright_download_dir",
    "playwright_artifacts_dir",
    "playwright_auto_download",
    "playwright_browser_channel",
)


def extract_playwright_params(script_source: str) -> List[str]:
    """从脚本中提取 {{param_name}} 占位符"""
    seen = []
    for match in PLACEHOLDER_PATTERN.finditer(script_source or ""):
        name = match.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def _default_param_label(name: str) -> str:
    return name.replace("_", " ").strip().title() or name


def build_playwright_config_schema(
    param_names: List[str], existing_schema: Dict | None = None
) -> Dict[str, Dict]:
    """构建 Playwright 节点的配置表单"""
    existing_schema = existing_schema or {}
    schema: Dict[str, Dict] = {}

    for param_name in param_names:
        previous = existing_schema.get(param_name, {})
        schema[param_name] = {
            "type": previous.get("type", "string"),
            "label": previous.get("label", _default_param_label(param_name)),
            "default": previous.get("default", ""),
            "placeholder": previous.get("placeholder", f"填写 {param_name}"),
        }

    runtime_defaults = {
        "playwright_headless": {
            "type": "bool",
            "label": "无头模式",
            "default": False,
        },
        "playwright_timeout_seconds": {
            "type": "int",
            "label": "超时时间(秒)",
            "default": 120,
        },
        "playwright_download_dir": {
            "type": "string",
            "label": "下载目录",
            "default": "",
            "placeholder": "为空时自动创建临时目录",
        },
        "playwright_artifacts_dir": {
            "type": "string",
            "label": "产物目录",
            "default": "",
            "placeholder": "为空时自动创建临时目录",
        },
        "playwright_auto_download": {
            "type": "bool",
            "label": "自动下载文件",
            "default": True,
            "description": "自动等待下载完成、保存文件并读取内容",
        },
        "playwright_browser_channel": {
            "type": "string",
            "label": "浏览器通道",
            "default": "",
            "placeholder": "留空用内置浏览器，填 chrome / msedge 等",
            "description": "使用本地安装的浏览器（如 chrome），避免下载 Playwright 内置浏览器",
        },
    }

    for key, default_schema in runtime_defaults.items():
        previous = existing_schema.get(key, {})
        merged = dict(default_schema)
        merged.update({k: v for k, v in previous.items() if v is not None})
        schema[key] = merged

    return schema


def is_playwright_node(node_metadata: Dict | None) -> bool:
    """判断节点是否为 Playwright 脚本节点"""
    metadata = node_metadata or {}
    return metadata.get("node_kind") == "playwright_script"


def get_playwright_param_names_from_schema(config_schema: Dict | None) -> List[str]:
    """从 schema 中提取业务参数，排除运行时字段"""
    config_schema = config_schema or {}
    return [
        key
        for key in config_schema.keys()
        if key not in PLAYWRIGHT_RUNTIME_FIELDS
    ]


def build_playwright_default_config(existing_config: Dict | None = None) -> Dict:
    """为 Playwright 节点构建默认配置"""
    existing_config = dict(existing_config or {})

    # 向后兼容：旧版 playwright_auto_read_downloads → playwright_auto_download
    if "playwright_auto_read_downloads" in existing_config and "playwright_auto_download" not in existing_config:
        existing_config["playwright_auto_download"] = existing_config.pop("playwright_auto_read_downloads")

    schema = build_playwright_config_schema(
        extract_playwright_params(existing_config.get("script_source", "")),
        existing_config.get("param_schema", {}),
    )

    config = {
        "script_source": existing_config.get("script_source", ""),
        "param_schema": schema,
    }

    for key, field_schema in schema.items():
        if key in existing_config:
            config[key] = existing_config[key]
        elif "default" in field_schema:
            config[key] = field_schema.get("default")

    # 保留其它未知字段，避免未来扩展或旧工作流数据被吞掉。
    for key, value in existing_config.items():
        if key not in config:
            config[key] = value

    return config


def build_playwright_inline_wrapper_source(
    script_source: str, param_names: List[str]
) -> str:
    """生成包装 execute()，在工作流中回放内嵌 Playwright 脚本"""
    script_source_literal = json.dumps(script_source or "", ensure_ascii=False)
    param_names_literal = json.dumps(param_names, ensure_ascii=False)

    lines = [
        "def execute(self, input_data):",
        '    """执行 Playwright 录制脚本"""',
        "    import json",
        "    import os",
        "    import re",
        "    import subprocess",
        "    import sys",
        "    from pathlib import Path",
        "",
        "    def _as_bool(value):",
        "        if isinstance(value, bool):",
        "            return value",
        '        return str(value).strip().lower() in ("1", "true", "yes", "on")',
        "",
        "    def _parse_json_payload(stdout_text: str):",
        '        start_token = "###JSON_OUTPUT###"',
        '        end_token = "###JSON_OUTPUT_END###"',
        "        if start_token not in stdout_text or end_token not in stdout_text:",
        "            return None, stdout_text.strip()",
        "        start = stdout_text.find(start_token) + len(start_token)",
        "        end = stdout_text.find(end_token, start)",
        "        payload_text = stdout_text[start:end].strip()",
        "        before = stdout_text[: stdout_text.find(start_token)].strip()",
        "        after = stdout_text[end + len(end_token) :].strip() if end != -1 else ''",
        '        extra_log = "\\n".join(part for part in [before, after] if part).strip()',
        "        return json.loads(payload_text), extra_log",
        "",
        "    def _render_script(template_text: str, params: dict):",
        "        rendered = template_text",
        f"        for name in sorted({param_names_literal}, key=len, reverse=True):",
        '            replacement = f\'LF_PARAMS[{json.dumps(name, ensure_ascii=False)}]\'',
        r"            quoted_pattern = re.compile(r'([\"\'])\{\{\s*' + re.escape(name) + r'\s*\}\}\1')",
        "            rendered = quoted_pattern.sub(replacement, rendered)",
        r"            raw_pattern = re.compile(r'\{\{\s*' + re.escape(name) + r'\s*\}\}')",
        "            rendered = raw_pattern.sub(replacement, rendered)",
        "        return rendered",
        "",
        f"    template_text = {script_source_literal}",
        "    if not str(template_text).strip():",
        '        raise RuntimeError("请先在节点详情中配置 Playwright 脚本")',
        "",
        f"    param_names = {param_names_literal}",
        '    params = {name: self.config.get(name) for name in param_names}',
        "    headless = _as_bool(self.config.get('playwright_headless', False))",
        "    timeout_seconds = int(self.config.get('playwright_timeout_seconds', 120) or 120)",
        "    download_dir_value = str(self.config.get('playwright_download_dir', '') or '').strip()",
        "    artifacts_dir_value = str(self.config.get('playwright_artifacts_dir', '') or '').strip()",
        "    # 向后兼容：读取 playwright_auto_download，回退旧字段",
        "    auto_download = self.config.get('playwright_auto_download')",
        "    if auto_download is None:",
        "        auto_download = self.config.get('playwright_auto_read_downloads', True)",
        "    auto_download = _as_bool(auto_download)",
        "    browser_channel = str(self.config.get('playwright_browser_channel', '') or '').strip()",
        "",
        "    runtime_root = Path(__file__).resolve().parent / f'{Path(__file__).stem}_playwright'",
        "    runtime_root.mkdir(parents=True, exist_ok=True)",
        "",
        "    if artifacts_dir_value:",
        "        artifacts_dir = Path(artifacts_dir_value).expanduser().resolve()",
        "        artifacts_dir.mkdir(parents=True, exist_ok=True)",
        "    else:",
        "        artifacts_dir = (runtime_root / 'artifacts').resolve()",
        "        artifacts_dir.mkdir(parents=True, exist_ok=True)",
        "",
        "    if download_dir_value:",
        "        unsafe_dir = Path(download_dir_value).expanduser().resolve()",
        "        # 安全性检查：确保下载目录在工作区或用户主目录范围内",
        "        home = Path.home()",
        "        try:",
        "            unsafe_dir.relative_to(runtime_root)",
        "            download_dir = unsafe_dir",
        "        except ValueError:",
        "            try:",
        "                unsafe_dir.relative_to(home)",
        "                download_dir = unsafe_dir",
        "            except ValueError:",
        "                logger = __import__('logging').getLogger('playwright')",
        "                logger.warning(",
        '                    "下载目录 %s 超出允许范围，回退到默认下载目录", unsafe_dir',
        "                )",
        "                download_dir = (runtime_root / 'downloads').resolve()",
        "        download_dir.mkdir(parents=True, exist_ok=True)",
        "    else:",
        "        download_dir = (runtime_root / 'downloads').resolve()",
        "        download_dir.mkdir(parents=True, exist_ok=True)",
        "",
        "    rendered_script = _render_script(template_text, params)",
        "    runtime_script_path = artifacts_dir / 'playwright_runtime.py'",
        "",
        "    bootstrap = '\\n'.join([",
        "        'import json',",
        "        'import os',",
        "        'import time',",
        "        'import sys',",
        "        'from pathlib import Path',",
        "        f\"LF_INPUT_DATA = {repr(input_data)}\",",
        "        f\"LF_PARAMS = {repr(params)}\",",
        "        f\"LF_DOWNLOAD_DIR = {repr(str(download_dir))}\",",
        "        f\"LF_ARTIFACTS_DIR = {repr(str(artifacts_dir))}\",",
        "        f\"LF_HEADLESS = {repr(headless)}\",",
        "        f\"LF_TIMEOUT_SECONDS = {repr(timeout_seconds)}\",",
        "        'LF_OUTPUT = {}',",
        "        'LF_ARTIFACTS = {}',",
        "        'LF_DOWNLOAD_EVENTS = []',",
        "        f\"LF_AUTO_DOWNLOAD = {repr(auto_download)}\",",
        "        '',",
        "        'def lf_log(message):',",
        "        '    print(f\"[localflow] {message}\", flush=True)',",
        "        '',",
        "        'def lf_set_output(data=None, **kwargs):',",
        "        '    global LF_OUTPUT',",
        "        '    if data is None:',",
        "        '        data = {}',",
        "        '    if not isinstance(data, dict):',",
        "        '        raise TypeError(\"lf_set_output 需要 dict\")',",
        "        '    merged = dict(data)',",
        "        '    merged.update(kwargs)',",
        "        '    LF_OUTPUT = merged',",
        "        '',",
        "        'def lf_add_artifact(name, path):',",
        "        '    LF_ARTIFACTS[str(name)] = str(path)',",
        "        '',",
        "        'def lf_download_wait(timeout=None, min_stable_seconds=2):',",
        "        '    _timeout = timeout or LF_TIMEOUT_SECONDS',",
        "        '    _download_dir = Path(LF_DOWNLOAD_DIR)',",
        "        '    _start = time.time()',",
        "        '    _last_count = -1',",
        "        '    _stable_since = None',",
        "        '    lf_log(\"等待下载完成...\")',",
        "        '    while time.time() - _start < _timeout:',",
        "        '        _files = list(_download_dir.iterdir()) if _download_dir.exists() else []',",
        "        '        _crdownload = [f for f in _files if f.suffix == \".crdownload\"]',",
        "        '        if _crdownload:',",
        "        '            _last_count = -1',",
        "        '            _stable_since = None',",
        "        '            time.sleep(0.5)',",
        "        '            continue',",
        "        '        _current_count = len([f for f in _files if f.is_file()])',",
        "        '        if _current_count == _last_count and _current_count > 0:',",
        "        '            if _stable_since is None:',",
        "        '                _stable_since = time.time()',",
        "        '            elif time.time() - _stable_since >= min_stable_seconds:',",
        "        '                lf_log(f\"下载稳定，共 {_current_count} 个文件\")',",
        "        '                return list(_download_dir.iterdir())',",
        "        '        else:',",
        "        '            _stable_since = None',",
        "        '        _last_count = _current_count',",
        "        '        time.sleep(0.5)',",
        "        '    lf_log(f\"下载等待超时，已获取 {_last_count if _last_count >= 0 else 0} 个文件\")',",
        "        '    return list(_download_dir.iterdir()) if _download_dir.exists() else []',",
        "        '',",
        "        'def lf_read_file(file_path, encoding=\"utf-8\", max_size_mb=10):',",
        "        '    _path = Path(file_path)',",
        "        '    if not _path.exists():',",
        "        '        raise FileNotFoundError(f\"文件不存在: {file_path}\")',",
        "        '    _size_mb = _path.stat().st_size / (1024 * 1024)',",
        "        '    if _size_mb > max_size_mb:',",
        "        '        return None',",
        "        '    _suffix = _path.suffix.lower()',",
        "        '    if _suffix == \".json\":',",
        "        '        with open(_path, \"r\", encoding=encoding) as _f:',",
        "        '            return json.load(_f)',",
        "        '    elif _suffix in (\".csv\", \".tsv\", \".txt\", \".log\", \".md\", \".html\", \".xml\", \".ini\", \".yaml\", \".yml\"):',",
        "        '        with open(_path, \"r\", encoding=encoding) as _f:',",
        "        '            return _f.read()',",
        "        '    return None',",
        "        '',",
        "        'def lf_configure_browser_download(browser_context):',",
        "        '    try:',",
        "        '        if hasattr(browser_context, \"set_default_download_path\"):',",
        "        '            browser_context.set_default_download_path(LF_DOWNLOAD_DIR)',",
        "        '        elif hasattr(browser_context, \"_impl_obj\"):',",
        "        '            pass',",
        "        '    except Exception:',",
        "        '        pass',",
        "        '    return browser_context',",
        "        '',",
        "        'def lf_create_context(browser, **kwargs):',",
        "        '    kwargs.setdefault(\"accept_downloads\", True)',",
        "        '    context = browser.new_context(**kwargs)',",
        "        '    return context',",
        "        '',",
        "        'def lf_handle_download(page, download_event):',",
        "        '    _save_path = os.path.join(LF_DOWNLOAD_DIR, download_event.suggested_filename)',",
        "        '    download_event.save_as(_save_path)',",
        "        '    LF_DOWNLOAD_EVENTS.append({\"path\": _save_path, \"name\": download_event.suggested_filename})',",
        "        '    lf_log(f\"手动保存下载: {download_event.suggested_filename}\")',",
        "        '',",
        "        'def _lf_auto_handle_download(download):',",
        "        '    try:',",
        "        '        _save_path = os.path.join(LF_DOWNLOAD_DIR, download.suggested_filename)',",
        "        '        lf_log(f\"正在下载: {download.suggested_filename} -> {_save_path}\")',",
        "        '        download.save_as(_save_path)',",
        "        '        LF_DOWNLOAD_EVENTS.append({\"path\": _save_path, \"name\": download.suggested_filename})',",
        "        '        lf_log(f\"下载完成: {_save_path}\")',",
        "        '    except Exception as _e:',",
        "        '        import traceback; traceback.print_exc()',",
        "        '        print(f\"[localflow] 自动保存下载失败: {_e}\")',",
        "        '',",
        "        'def _lf_patch_page(page):',",
        "        '    page.on(\"download\", _lf_auto_handle_download)',",
        "        '    lf_log(f\"页面已注册下载自动保存处理器\")',",
        "        '    return page',",
        "        '',",
        "        'def _lf_patch_browser(browser):',",
        "        '    lf_log(f\"修补浏览器 new_page 和 new_context\")',",
        "        '    _orig_new_page = browser.new_page',",
        "        '    def _new_page(*args, **kwargs):',",
        "        '        page = _orig_new_page(*args, **kwargs)',",
        "        '        return _lf_patch_page(page)',",
        "        '    browser.new_page = _new_page',",
        "        '    _orig_new_context = browser.new_context',",
        "        '    def _new_context(*args, **kwargs):',",
        "        '        kwargs.setdefault(\"accept_downloads\", True)',",
        "        '        lf_log(f\"创建浏览器上下文 (accept_downloads=True)\")',",
        "        '        context = _orig_new_context(*args, **kwargs)',",
        "        '        return _lf_patch_context(context)',",
        "        '    browser.new_context = _new_context',",
        "        '    return browser',",
        "        '',",
        "        'def _lf_patch_context(context):',",
        "        '    _orig_new_page = context.new_page',",
        "        '    def _new_page(*args, **kwargs):',",
        "        '        page = _orig_new_page(*args, **kwargs)',",
        "        '        return _lf_patch_page(page)',",
        "        '    context.new_page = _new_page',",
        "        '    lf_log(f\"浏览器上下文 new_page 已修补\")',",
        "        '    return context',",
        "    ])",
        "",
        "    auto_patch = '''",
        "# 自动拦截 Playwright 下载事件，无需用户手动处理",
        "try:",
        "    from playwright.sync_api import sync_playwright",
        "    _orig_playwright = sync_playwright",
        "    def _patched_playwright(*args, **kwargs):",
        "        pw = _orig_playwright(*args, **kwargs)",
        "        _orig_launch = pw.chromium.launch",
        "        def _patched_launch(*args, **kwargs):",
        "            browser = _orig_launch(*args, **kwargs)",
        "            return _lf_patch_browser(browser)",
        "        pw.chromium.launch = _patched_launch",
        "        _orig_launch_firefox = pw.firefox.launch",
        "        def _patched_launch_firefox(*args, **kwargs):",
        "            browser = _orig_launch_firefox(*args, **kwargs)",
        "            return _lf_patch_browser(browser)",
        "        pw.firefox.launch = _patched_launch_firefox",
        "        _orig_launch_webkit = pw.webkit.launch",
        "        def _patched_launch_webkit(*args, **kwargs):",
        "            browser = _orig_launch_webkit(*args, **kwargs)",
        "            return _lf_patch_browser(browser)",
        "        pw.webkit.launch = _patched_launch_webkit",
        "        return pw",
        "    __import__('playwright.sync_api').sync_playwright = _patched_playwright",
        "except Exception:",
        "    pass",
        "'''",
        "",
        "    footer = '''",
        "import json",
        "import time",
        "from pathlib import Path",
        "",
        "# 自动等待下载完成",
        "if LF_AUTO_DOWNLOAD:",
        "    lf_download_wait(timeout=LF_TIMEOUT_SECONDS)",
        "else:",
        "    time.sleep(1)",
        "",
        "_download_root = Path(LF_DOWNLOAD_DIR)",
        "# 排除 .crdownload 临时文件",
        "_raw_files = sorted(",
        "    [",
        "        path for path in _download_root.iterdir()",
        "        if path.is_file() and path.suffix != '.crdownload'",
        "    ],",
        "    key=lambda p: p.stat().st_mtime,",
        ") if _download_root.exists() else []",
        "",
        "_TEXT_EXTENSIONS = {\".csv\", \".tsv\", \".txt\", \".log\", \".md\", \".html\", \".xml\", \".ini\", \".yaml\", \".yml\", \".json\"}",
        "",
        "_downloads = []",
        "_download_contents = {}",
        "for _f in _raw_files:",
        "    _info = {",
        "        \"path\": str(_f.resolve()),",
        "        \"name\": _f.name,",
        "        \"suffix\": _f.suffix.lower(),",
        "        \"size_bytes\": _f.stat().st_size,",
        "    }",
        "    _downloads.append(_info)",
        "    if LF_AUTO_DOWNLOAD:",
        "        _content = lf_read_file(_f, max_size_mb=10)",
        "        if _content is not None:",
        "            _download_contents[_f.name] = _content",
        "",
        "_result = {",
        "    \"downloads\": [d[\"path\"] for d in _downloads],",
        "    \"download_details\": _downloads,",
        "    \"download_contents\": _download_contents,",
        "    \"structured_output\": LF_OUTPUT,",
        "    \"artifacts\": LF_ARTIFACTS,",
        "    \"meta\": {",
        "        \"download_dir\": str(LF_DOWNLOAD_DIR),",
        "        \"artifacts_dir\": str(LF_ARTIFACTS_DIR),",
        "        \"headless\": LF_HEADLESS,",
        "        \"timeout_seconds\": LF_TIMEOUT_SECONDS,",
        "        \"auto_download\": LF_AUTO_DOWNLOAD,",
        "        \"browser_channel\": LF_BROWSER_CHANNEL,",
        "    },",
        "}",
        "print(\"###JSON_OUTPUT###\")",
        "print(json.dumps(_result, ensure_ascii=False))",
        "print(\"###JSON_OUTPUT_END###\")",
        "'''",
        "",
        "    runtime_script_path.write_text(",
        '        bootstrap + "\\n\\n" + auto_patch + "\\n\\n" + rendered_script + "\\n\\n" + footer,',
        "        encoding='utf-8',",
        "    )",
        "",
        "    env = os.environ.copy()",
        "    env['PYTHONIOENCODING'] = 'utf-8'",
        "    process = subprocess.run(",
        "        [sys.executable, str(runtime_script_path)],",
        "        capture_output=True,",
        "        text=True,",
        "        encoding='utf-8',",
        "        cwd=str(artifacts_dir),",
        "        env=env,",
        "        timeout=timeout_seconds,",
        "    )",
        "",
        "    payload, script_log = _parse_json_payload(process.stdout or '')",
        "    if process.returncode != 0:",
        "        error_message = (process.stderr or script_log or process.stdout or '').strip()",
        '        raise RuntimeError(error_message or "Playwright 脚本执行失败")',
        "",
        "    if payload is None:",
        '        raise RuntimeError("Playwright 脚本未输出标准 JSON 结果")',
        "",
        "    result = {**input_data, **payload}",
        "    if script_log:",
        "        result['script_stdout'] = script_log",
        "    return result",
        "",
    ]
    return "\n".join(lines)


def build_playwright_wrapper_source(script_path, param_names: List[str]) -> str:
    """兼容旧版自定义节点资产路径的包装执行器"""
    from pathlib import Path

    script_path = Path(script_path)
    script_source = ""
    if script_path.exists():
        script_source = script_path.read_text(encoding="utf-8")
    return build_playwright_inline_wrapper_source(script_source, param_names)

# -- auto register extensions --
def _pw_bootstrap_hook(config):
    script_source = config.get('script_source', '')
    param_names = extract_playwright_params(script_source)
    return build_playwright_inline_wrapper_source(script_source, param_names)

from .node_extension_registries import schema_builders, bootstrap_hooks
schema_builders.register('playwright_script', build_playwright_config_schema)
bootstrap_hooks.register('playwright_script', _pw_bootstrap_hook)
