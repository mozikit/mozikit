"""
api_request 节点单元测试

测试 HTTP 请求节点的 execute() 函数，包括成功请求、错误处理、
URL 模板替换等场景。使用 unittest.mock 模拟网络调用，不依赖真实网络。

测试所需的 node.py 源码在 pytest fixture 中通过 tmp_path 动态创建，
不依赖仓库中未提交的手工文件。
"""
import json
import unittest
import warnings
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError

import pytest

# ── api_request/node.py 源码 ──────────────────────────────
# 在 conftest.py 的 api_request_execute fixture 中被写入 tmp_path 并加载。
# 该节点属于 mozikit-official-nodes 独立仓库，此处提供 fixture 版本
# 供单元测试验证节点协议与行为。
_API_REQUEST_NODE_SOURCE = r"""
import json as _json
import urllib.request as _ur
from urllib.error import HTTPError as _HTTPError, URLError as _URLError


def execute(node_shim, input_data):
    config = dict(getattr(node_shim, 'config', {}))
    input_data = input_data or {}

    # input_data 覆盖 config 中对应的字段
    for key in ('method', 'url', 'headers', 'body', 'timeout'):
        if key in input_data:
            config[key] = input_data[key]

    url = config.get('url', '')
    method = config.get('method', 'GET').upper()
    headers_raw = config.get('headers', '{}')
    body = config.get('body', '')
    timeout = config.get('timeout', 30)

    # URL 模板替换 {{var}} → input_data[var]
    for key, value in input_data.items():
        url = url.replace('{{' + key + '}}', str(value))

    if not url:
        return {'status_code': 0, 'response_body': '', 'response_text': '',
                'error': '\u672a\u6307\u5b9a URL'}

    # 解析 headers JSON 字符串
    if isinstance(headers_raw, str):
        try:
            headers = _json.loads(headers_raw)
        except _json.JSONDecodeError:
            headers = {}
    else:
        headers = dict(headers_raw) if headers_raw else {}

    # 有 body 且无 Content-Type 时自动添加
    if body:
        has_ct = any(k.lower() == 'content-type' for k in headers)
        if not has_ct:
            headers['Content-Type'] = 'application/json'

    req = _ur.Request(url, method=method)
    for k, v in headers.items():
        req.add_header(k, v)

    data = body.encode('utf-8') if body else None

    try:
        if data is not None:
            resp = _ur.urlopen(req, data=data, timeout=timeout)
        else:
            resp = _ur.urlopen(req, timeout=timeout)

        status_code = resp.status
        response_text = resp.read().decode('utf-8')

        ct = (resp.headers.get('Content-Type', '') or '').lower()
        if 'application/json' in ct:
            try:
                response_body = _json.loads(response_text)
            except (_json.JSONDecodeError, ValueError):
                response_body = response_text
        else:
            response_body = response_text

        return {
            'status_code': status_code,
            'response_body': response_body,
            'response_text': response_text,
            'error': '',
        }
    except _HTTPError as e:
        status_code = e.code
        error_msg = 'HTTP {}: {}'.format(e.code, e.reason)
        try:
            body_bytes = e.read()
            body_text = body_bytes.decode('utf-8') if body_bytes else ''
        except Exception:
            body_text = ''
        try:
            response_body = _json.loads(body_text) if body_text else ''
        except (_json.JSONDecodeError, ValueError):
            response_body = body_text
        return {
            'status_code': status_code,
            'response_body': response_body,
            'response_text': body_text,
            'error': error_msg,
        }
    except _URLError as e:
        return {
            'status_code': 0,
            'response_body': '',
            'response_text': '',
            'error': '\u8bf7\u6c42\u5931\u8d25: {}'.format(e.reason),
        }
"""


@pytest.fixture(scope="module")
def api_request_execute(tmp_path_factory):
    """在临时目录中创建 api_request/node.py 并返回 execute 函数。

    模块级作用域——每个测试模块只创建一次，避免重复 I/O。
    """
    tmp_path = tmp_path_factory.mktemp("api_request_node")
    node_dir = tmp_path / "api_request"
    node_dir.mkdir(parents=True, exist_ok=True)
    node_py = node_dir / "node.py"
    node_py.write_text(_API_REQUEST_NODE_SOURCE, encoding="utf-8")

    exec_globals = {}
    exec(compile(node_py.read_text(encoding="utf-8"), str(node_py), "exec"), exec_globals)
    return exec_globals["execute"]


@pytest.fixture(autouse=True)
def _inject_execute(api_request_execute, request):
    """将 execute 注入模块全局变量，供 TestCase 的 test_* 方法使用。

    使用 autouse 确保每个测试方法执行前 execute 已就绪。
    """
    request.module.execute = api_request_execute


class NodeShim:
    """模拟节点执行时的 NodeShim，仅保留 config 属性"""
    def __init__(self, config: dict):
        self.config = config


class TestApiRequestNode(unittest.TestCase):
    """api_request 节点 — execute 函数单元测试"""

    def setUp(self):
        # Python 3.14+ 对未关闭的 HTTPError.fp 报 ResourceWarning
        warnings.filterwarnings("ignore", category=ResourceWarning, message=".*HTTPError.*")

    # ── 辅助方法 ──────────────────────────────────────

    def _make_http_response(self, status=200, headers=None, body="{}"):
        """创建一个模拟的 HTTP 响应对象"""
        mock_resp = MagicMock()
        mock_resp.status = status
        mock_resp.headers = headers or {"Content-Type": "application/json"}
        mock_resp.read.return_value = body.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None
        return mock_resp

    def _make_http_error(self, code, reason, body=""):
        """创建一个模拟 HTTPError（可用作 urlopen 的 side_effect）"""
        import io
        from http.client import HTTPMessage
        hdrs = HTTPMessage()
        fp = io.BytesIO(body.encode("utf-8"))
        return HTTPError(
            url="http://error.example.com",
            code=code,
            msg=reason,
            hdrs=hdrs,
            fp=fp,
        )

    # ── 正常请求 ──────────────────────────────────────

    @patch("urllib.request.urlopen")
    def test_get_request_returns_json(self, mock_urlopen):
        """GET 请求应正确解析 JSON 响应"""
        mock_urlopen.return_value = self._make_http_response(
            200,
            {"Content-Type": "application/json"},
            json.dumps({"userId": 1, "title": "test"}),
        )

        shim = NodeShim({
            "method": "GET",
            "url": "https://api.example.com/data",
            "headers": "{}",
            "timeout": 30,
        })
        result = execute(shim, {})

        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["response_body"]["title"], "test")
        self.assertEqual(result["error"], "")
        mock_urlopen.assert_called_once()
        args, kwargs = mock_urlopen.call_args
        self.assertEqual(args[0].method, "GET")
        self.assertEqual(args[0].full_url, "https://api.example.com/data")

    @patch("urllib.request.urlopen")
    def test_post_request_sends_body(self, mock_urlopen):
        """POST 请求应发送请求体并设置 Content-Type"""
        mock_urlopen.return_value = self._make_http_response(
            201,
            {"Content-Type": "application/json"},
            json.dumps({"id": 101}),
        )

        shim = NodeShim({
            "method": "POST",
            "url": "https://api.example.com/create",
            "headers": "{\"Authorization\": \"Bearer tok_xxx\"}",
            "body": json.dumps({"name": "test"}),
            "timeout": 15,
        })
        result = execute(shim, {})

        self.assertEqual(result["status_code"], 201)
        self.assertEqual(result["error"], "")

        args, kwargs = mock_urlopen.call_args
        req = args[0]
        self.assertEqual(req.method, "POST")
        # headers 经过 add_header 的 capitalize()，key 大小写可能变化
        h = {k.lower(): v for k, v in req.headers.items()}
        self.assertEqual(h.get("authorization"), "Bearer tok_xxx")
        # data 作为 keyword 参数传给 urlopen，不在 req.data 上
        self.assertIsNotNone(kwargs.get("data"))

    @patch("urllib.request.urlopen")
    def test_put_without_content_type_auto_adds(self, mock_urlopen):
        """PUT 请求未指定 Content-Type 时应自动添加"""
        mock_urlopen.return_value = self._make_http_response(200)

        shim = NodeShim({
            "method": "PUT",
            "url": "https://api.example.com/update",
            "headers": "{}",
            "body": "{\"key\": \"value\"}",
            "timeout": 30,
        })
        result = execute(shim, {})

        self.assertEqual(result["status_code"], 200)
        args, kwargs = mock_urlopen.call_args
        req = args[0]
        h = {k.lower(): v for k, v in req.headers.items()}
        self.assertEqual(h.get("content-type"), "application/json")

    # ── 错误处理 ──────────────────────────────────────

    @patch("urllib.request.urlopen")
    def test_http_404_error(self, mock_urlopen):
        """HTTP 404 应返回错误信息和状态码"""
        mock_urlopen.side_effect = self._make_http_error(404, "Not Found", "not found body")

        shim = NodeShim({
            "method": "GET",
            "url": "https://api.example.com/notfound",
            "headers": "{}",
            "timeout": 10,
        })
        result = execute(shim, {})

        self.assertEqual(result["status_code"], 404)
        self.assertIn("Not Found", result["error"])

    @patch("urllib.request.urlopen")
    def test_http_401_unauthorized(self, mock_urlopen):
        """HTTP 401 应返回错误"""
        mock_urlopen.side_effect = self._make_http_error(401, "Unauthorized", '{"error":"invalid_token"}')

        shim = NodeShim({
            "method": "GET",
            "url": "https://api.example.com/secure",
            "headers": "{}",
            "timeout": 10,
        })
        result = execute(shim, {})

        self.assertEqual(result["status_code"], 401)
        self.assertIsInstance(result["response_body"], dict)

    @patch("urllib.request.urlopen")
    def test_network_error(self, mock_urlopen):
        """网络不可达时应返回友好错误消息"""
        mock_urlopen.side_effect = URLError(reason="Name or service not known")

        shim = NodeShim({
            "method": "GET",
            "url": "https://nonexistent.example.com/api",
            "timeout": 5,
        })
        result = execute(shim, {})

        self.assertEqual(result["status_code"], 0)
        self.assertIn("请求失败", result["error"])

    # ── 输入覆盖 ──────────────────────────────────────

    @patch("urllib.request.urlopen")
    def test_url_override_from_input_data(self, mock_urlopen):
        """input_data 中的 url 应覆盖 config 中的 url"""
        mock_urlopen.return_value = self._make_http_response(200, {}, "{}")

        shim = NodeShim({
            "method": "GET",
            "url": "https://default.example.com",
            "headers": "{}",
            "timeout": 30,
        })
        result = execute(shim, {"url": "https://override.example.com"})

        args, kwargs = mock_urlopen.call_args
        self.assertIn("override.example.com", args[0].full_url)

    @patch("urllib.request.urlopen")
    def test_method_override_from_input_data(self, mock_urlopen):
        """input_data 中的 method 应覆盖 config"""
        mock_urlopen.return_value = self._make_http_response(200)

        shim = NodeShim({
            "method": "GET",
            "url": "https://api.example.com/data",
            "headers": "{}",
            "timeout": 30,
        })
        execute(shim, {"method": "POST", "body": "{}"})

        args, kwargs = mock_urlopen.call_args
        self.assertEqual(args[0].method, "POST")

    @patch("urllib.request.urlopen")
    def test_url_template_substitution(self, mock_urlopen):
        """URL 中的 {{变量}} 应被 input_data 替换"""
        mock_urlopen.return_value = self._make_http_response(200, {}, "{}")

        shim = NodeShim({
            "method": "GET",
            "url": "https://api.github.com/users/{{username}}/repos",
            "headers": "{}",
            "timeout": 30,
        })
        result = execute(shim, {"username": "testuser"})

        args, kwargs = mock_urlopen.call_args
        self.assertIn("testuser", args[0].full_url)
        self.assertNotIn("{{username}}", args[0].full_url)

    # ── 边界情况 ──────────────────────────────────────

    def test_empty_url_returns_error(self):
        """URL 为空时应立即返回错误"""
        shim = NodeShim({
            "method": "GET",
            "url": "",
            "headers": "{}",
            "timeout": 30,
        })
        result = execute(shim, {})
        self.assertEqual(result["status_code"], 0)
        self.assertIn("未指定", result["error"])

    @patch("urllib.request.urlopen")
    def test_non_json_response_returns_raw_text(self, mock_urlopen):
        """非 JSON 响应应将 response_body 设为原始字符串"""
        mock_urlopen.return_value = self._make_http_response(200, {}, "plain text response")

        shim = NodeShim({
            "method": "GET",
            "url": "https://example.com/text",
            "headers": "{}",
            "timeout": 30,
        })
        result = execute(shim, {})

        self.assertEqual(result["response_body"], "plain text response")
        self.assertEqual(result["response_text"], "plain text response")

    @patch("urllib.request.urlopen")
    def test_custom_headers_from_config(self, mock_urlopen):
        """config 中的 headers 应正确设置请求头"""
        mock_urlopen.return_value = self._make_http_response(200, {}, "{}")

        shim = NodeShim({
            "method": "GET",
            "url": "https://api.example.com/data",
            "headers": json.dumps({
                "Accept": "application/vnd.github+json",
                "User-Agent": "Mozikit",
            }),
            "timeout": 30,
        })
        execute(shim, {})

        args, kwargs = mock_urlopen.call_args
        req = args[0]
        # headers 是 dict，key 经过 add_header 的 capitalize() 处理
        # 用小写比较确保跨 Python 版本兼容
        h = {k.lower(): v for k, v in req.headers.items()}
        self.assertEqual(h.get("accept"), "application/vnd.github+json")
        self.assertEqual(h.get("user-agent"), "Mozikit")


if __name__ == "__main__":
    unittest.main()
