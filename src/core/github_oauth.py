"""
GitHub OAuth Device Flow

GitHub OAuth Apps 的 Web Application Flow 即使配合 PKCE，
在令牌交换阶段仍然要求 client_secret。

桌面应用属于 public client，更适合使用 GitHub 官方支持的
Device Flow，它只需要 client_id，不需要 client_secret。
"""
import json
import time
import urllib.parse
import urllib.error
import urllib.request
import webbrowser
from typing import Callable, Optional, Tuple

GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_BASE = "https://api.github.com"
GITHUB_DEVICE_VERIFY_URL = "https://github.com/login/device"

CLIENT_ID = "Ov23liDrGTYVGSy9Vl9J"
DEFAULT_SCOPES = "repo,read:user,user:email"
DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

PromptCallback = Callable[[str, str], None]


class GitHubOAuth:
    def __init__(self, client_id: str = None):
        self.client_id = client_id or CLIENT_ID

    def authorize(
        self,
        timeout: int = 900,
        on_user_code: Optional[PromptCallback] = None,
    ) -> Tuple[bool, str, str]:
        """
        启动 GitHub Device Flow 授权流程

        Returns:
            (success, access_token, username_or_error)
        """
        success, device_data = self._request_device_code()
        if not success:
            return False, "", device_data

        device_code = device_data["device_code"]
        user_code = device_data["user_code"]
        verification_uri = device_data.get("verification_uri", GITHUB_DEVICE_VERIFY_URL)
        expires_in = int(device_data.get("expires_in", 900))
        interval = max(1, int(device_data.get("interval", 5)))
        deadline = time.monotonic() + min(timeout, expires_in)

        if on_user_code:
            on_user_code(user_code, verification_uri)

        try:
            webbrowser.open(verification_uri)
        except Exception:
            pass

        success, token = self._poll_for_token(device_code, interval, deadline)
        if not success:
            return False, "", token

        username = self._get_username(token)
        if not username:
            return False, "", "已获取访问令牌，但获取 GitHub 用户名失败"

        return True, token, username

    def _request_device_code(self) -> Tuple[bool, dict | str]:
        data = urllib.parse.urlencode({
            "client_id": self.client_id,
            "scope": DEFAULT_SCOPES,
        }).encode("utf-8")

        req = urllib.request.Request(GITHUB_DEVICE_CODE_URL, data=data)
        req.add_header("Accept", "application/json")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                if body.get("device_code") and body.get("user_code"):
                    return True, body
                return False, self._format_request_error(body)
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8"))
            except Exception:
                body = {}
            if body:
                return False, self._format_request_error(body)
            return False, f"HTTP {e.code}"
        except Exception as e:
            return False, str(e)

    def _poll_for_token(self, device_code: str, interval: int, deadline: float) -> Tuple[bool, str]:
        current_interval = interval

        while time.monotonic() < deadline:
            success, token_or_error, error_code, next_interval = self._exchange_device_token(device_code)
            if success:
                return True, token_or_error

            if error_code == "authorization_pending":
                time.sleep(current_interval)
                continue

            if error_code == "slow_down":
                current_interval = max(current_interval + 5, next_interval or 0)
                time.sleep(current_interval)
                continue

            if error_code in {"expired_token", "token_expired"}:
                return False, "GitHub 设备验证码已过期，请重试登录"

            if error_code == "access_denied":
                return False, "GitHub 授权被取消"

            if error_code == "device_flow_disabled":
                return False, "当前 GitHub OAuth App 未启用 Device Flow，请先在 GitHub 应用设置中开启"

            if error_code == "incorrect_client_credentials":
                return False, "GitHub 返回 incorrect_client_credentials。Device Flow 只接受 client_id，请检查应用配置和 client_id 是否正确"

            if error_code == "incorrect_device_code":
                return False, "GitHub 返回 incorrect_device_code，请重试登录"

            return False, token_or_error

        return False, "GitHub 授权超时，请重试登录"

    def _exchange_device_token(self, device_code: str) -> Tuple[bool, str, str, int]:
        data = urllib.parse.urlencode({
            "client_id": self.client_id,
            "device_code": device_code,
            "grant_type": DEVICE_GRANT_TYPE,
        }).encode("utf-8")

        req = urllib.request.Request(GITHUB_TOKEN_URL, data=data)
        req.add_header("Accept", "application/json")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                token = body.get("access_token", "")
                if token:
                    return True, token, "", 0
                error = body.get("error", "未知错误")
                return False, body.get("error_description", error), error, int(body.get("interval", 0) or 0)
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8"))
            except Exception:
                body = {}
            error = body.get("error", f"HTTP {e.code}")
            return False, body.get("error_description", error), error, int(body.get("interval", 0) or 0)
        except Exception as e:
            return False, str(e), "", 0

    @staticmethod
    def _format_request_error(body: dict) -> str:
        error = body.get("error", "")
        if error == "device_flow_disabled":
            return "当前 GitHub OAuth App 未启用 Device Flow，请先在 GitHub 应用设置中开启"
        if error == "incorrect_client_credentials":
            return "GitHub 返回 incorrect_client_credentials，请检查应用配置和 client_id 是否正确"
        return body.get("error_description", error or "获取设备验证码失败")

    @staticmethod
    def _get_username(token: str) -> str:
        req = urllib.request.Request(f"{GITHUB_API_BASE}/user")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("login", "")
        except Exception:
            return ""
