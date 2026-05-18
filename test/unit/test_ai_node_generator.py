import unittest

from src.core.ai_node_generator import (
    AINodeGenerationError,
    AINodeGenerationService,
)


class TestAINodeGenerationService(unittest.TestCase):
    def setUp(self):
        self.ai_settings = {
            "base_url": "https://example.com/v1",
            "api_key": "test-key",
            "model": "test-model",
            "timeout_seconds": 30,
            "temperature": 0.2,
        }
        self.spec = {
            "name": "HTTP 请求节点",
            "description": "发送 HTTP 请求并返回响应数据",
            "input_spec": "input_data 包含 url 和 method",
            "output_spec": "返回 status_code 和 body",
        }

    def test_build_endpoint_accepts_v1_and_chat_path(self):
        service = AINodeGenerationService(self.ai_settings)
        self.assertEqual(
            service._build_endpoint("https://example.com/v1"),
            "https://example.com/v1/chat/completions",
        )
        self.assertEqual(
            service._build_endpoint("https://example.com/custom/chat/completions"),
            "https://example.com/custom/chat/completions",
        )

    def test_parse_generation_payload_supports_code_fence(self):
        service = AINodeGenerationService(self.ai_settings)
        payload = service._parse_generation_payload(
            """```json
{"description":"desc","source_code":"def execute(self, input_data):\\n    return {}","config_schema":{},"dependencies":[]}
```"""
        )
        self.assertEqual(payload["description"], "desc")

    def test_generate_node_returns_structured_result(self):
        service = AINodeGenerationService(self.ai_settings)
        service._request_completion = lambda payload: {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"name":"HTTP 请求节点","description":"desc","category":"AI 生成",'
                            '"version":"1.0.0","dependencies":["requests"],'
                            '"config_schema":{"url":{"type":"string","label":"URL"}},'
                            '"source_code":"def execute(self, input_data):\\n    return {\\"ok\\": True}"}'
                        )
                    }
                }
            ]
        }

        result = service.generate_node(self.spec)
        self.assertEqual(result.name, "HTTP 请求节点")
        self.assertEqual(result.dependencies, ["requests"])
        self.assertIn("url", result.config_schema)
        self.assertIn("def execute(self, input_data)", result.source_code)

    def test_generate_node_rejects_invalid_payload(self):
        service = AINodeGenerationService(self.ai_settings)
        service._request_completion = lambda payload: {
            "choices": [{"message": {"content": '{"description":"desc","source_code":"print(1)","config_schema":{},"dependencies":[]}'}}]
        }

        with self.assertRaises(AINodeGenerationError):
            service.generate_node(self.spec)


if __name__ == "__main__":
    unittest.main()
