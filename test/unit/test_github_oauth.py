import json
import unittest
from unittest.mock import patch

from src.core.github_oauth import GitHubOAuth


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status = status

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestGitHubOAuth(unittest.TestCase):
    @patch("src.core.github_oauth.time.sleep", return_value=None)
    @patch("src.core.github_oauth.webbrowser.open", return_value=True)
    @patch("src.core.github_oauth.urllib.request.urlopen")
    def test_authorize_device_flow_success(self, mock_urlopen, _mock_browser, _mock_sleep):
        prompt_calls = []
        mock_urlopen.side_effect = [
            _FakeResponse({
                "device_code": "device-code-1",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 1,
            }),
            _FakeResponse({
                "error": "authorization_pending",
                "error_description": "The authorization request is still pending.",
            }),
            _FakeResponse({"access_token": "gho_test_token"}),
            _FakeResponse({"login": "octocat"}),
        ]

        oauth = GitHubOAuth()
        success, token, username = oauth.authorize(
            timeout=30,
            on_user_code=lambda code, uri: prompt_calls.append((code, uri)),
        )

        self.assertTrue(success)
        self.assertEqual(token, "gho_test_token")
        self.assertEqual(username, "octocat")
        self.assertEqual(prompt_calls, [("ABCD-EFGH", "https://github.com/login/device")])

    @patch("src.core.github_oauth.webbrowser.open", return_value=True)
    @patch("src.core.github_oauth.urllib.request.urlopen")
    def test_authorize_device_flow_disabled(self, mock_urlopen, _mock_browser):
        mock_urlopen.side_effect = [
            _FakeResponse({
                "device_code": "device-code-1",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 1,
            }),
            _FakeResponse({"error": "device_flow_disabled"}),
        ]

        oauth = GitHubOAuth()
        success, token, message = oauth.authorize(timeout=5)

        self.assertFalse(success)
        self.assertEqual(token, "")
        self.assertIn("Device Flow", message)

    @patch("src.core.github_oauth.webbrowser.open", return_value=True)
    @patch("src.core.github_oauth.urllib.request.urlopen")
    def test_authorize_incorrect_client_credentials(self, mock_urlopen, _mock_browser):
        mock_urlopen.side_effect = [
            _FakeResponse({
                "device_code": "device-code-1",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 1,
            }),
            _FakeResponse({"error": "incorrect_client_credentials"}),
        ]

        oauth = GitHubOAuth()
        success, token, message = oauth.authorize(timeout=5)

        self.assertFalse(success)
        self.assertEqual(token, "")
        self.assertIn("client_id", message)


if __name__ == "__main__":
    unittest.main()
