"""
api_request 节点单元测试

测试 HTTP 请求节点的 execute() 函数，包括成功请求、错误处理、
URL 模板替换等场景。使用 unittest.mock 模拟网络调用，不依赖真实网络。
"""
import json
import os
import sys
import unittest
import warnings
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

# 从节点源码加载 execute 函数
_NODE_PY_PATH = os.path.join(
    PROJECT_ROOT, ".tmp", "localflow-public-nodes", "api_request", "node.py"
)


def _load_execute():
    """加载 api_request 节点的 execute 函数"""
    with open(_NODE_PY_PATH, "r", encoding="utf-8") as f:
        source = f.read()
    exec_globals = {}
    exec(source, exec_globals)
    return exec_globals["execute"]


execute = _load_execute()


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
                "User-Agent": "LocalFlow",
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
        self.assertEqual(h.get("user-agent"), "LocalFlow")


if __name__ == "__main__":
    unittest.main()
