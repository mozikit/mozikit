"""
AI 自定义节点生成服务
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List
from urllib import error, request

from src.core.code_safety import SafetyReviewResult, review_code_safety
from src.core.exceptions import ErrorCode, LocalFlowError


class AINodeGenerationError(LocalFlowError):
    """AI 节点生成异常"""


@dataclass
class GeneratedNodeResult:
    """AI 生成结果"""

    name: str
    description: str
    source_code: str
    config_schema: Dict[str, Any]
    dependencies: List[str]
    category: str = "AI 生成"
    version: str = "1.0.0"
    safety_review: SafetyReviewResult = None


class AINodeGenerationService:
    """OpenAI 兼容接口节点生成服务"""

    def __init__(self, ai_settings: dict):
        self.ai_settings = ai_settings or {}

    def generate_node(self, spec: dict) -> GeneratedNodeResult:
        """根据需求生成节点定义"""
        self._validate_settings()

        payload = {
            "model": self.ai_settings["model"],
            "temperature": float(self.ai_settings.get("temperature", 0.2)),
            "messages": [
                {"role": "system", "content": self._build_system_prompt()},
                {"role": "user", "content": self._build_user_prompt(spec)},
            ],
        }

        response_data = self._request_completion(payload)
        content = self._extract_message_content(response_data)
        result_data = self._parse_generation_payload(content)
        self._validate_result(result_data)

        source_code = result_data["source_code"].strip()
        safety_review = review_code_safety(source_code)

        return GeneratedNodeResult(
            name=result_data.get("name", spec.get("name", "")).strip(),
            description=result_data["description"].strip(),
            source_code=source_code,
            config_schema=result_data.get("config_schema", {}),
            dependencies=result_data.get("dependencies", []),
            category=result_data.get("category", "AI 生成").strip() or "AI 生成",
            version=result_data.get("version", "1.0.0").strip() or "1.0.0",
            safety_review=safety_review,
        )

    def _validate_settings(self):
        missing_fields = [
            field for field in ("base_url", "api_key", "model")
            if not str(self.ai_settings.get(field, "")).strip()
        ]
        if missing_fields:
            raise AINodeGenerationError(
                ErrorCode.AI_CONFIG_INCOMPLETE,
                f"AI 配置不完整，缺少: {', '.join(missing_fields)}"
            )

    def _request_completion(self, payload: dict) -> dict:
        endpoint = self._build_endpoint(self.ai_settings["base_url"])
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.ai_settings['api_key']}",
            },
            method="POST",
        )

        timeout = int(self.ai_settings.get("timeout_seconds", 60) or 60)

        try:
            with request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore")
            message = error_body or str(exc)
            raise AINodeGenerationError(ErrorCode.AI_API_FAILED, f"AI 接口调用失败: HTTP {exc.code} {message}") from exc
        except error.URLError as exc:
            raise AINodeGenerationError(ErrorCode.AI_CONNECTION_FAILED, f"AI 接口连接失败: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise AINodeGenerationError(ErrorCode.AI_INVALID_RESPONSE, "AI 接口返回了无法解析的 JSON") from exc

    def _build_endpoint(self, base_url: str) -> str:
        normalized = base_url.rstrip("/")
        if normalized.endswith("/chat/completions"):
            return normalized
        if normalized.endswith("/v1"):
            return f"{normalized}/chat/completions"
        return f"{normalized}/v1/chat/completions"

    def _build_system_prompt(self) -> str:
        return (
            "你是 LocalFlow 的节点生成器。"
            "你必须输出一个 JSON 对象，不能输出 Markdown、解释文字或代码块围栏。"
            "JSON 必须包含字段: name, description, category, version, dependencies, config_schema, source_code。"
            "source_code 必须定义函数 def execute(self, input_data): 并返回 dict。"
            "该函数只能使用 self.config 读取配置，使用 input_data 读取上游输入。"
            "config_schema 必须是对象，键为配置项名称，值结构至少包含 type 和 label。"
            "type 只能使用 string、text、enum、int、float、bool、json。"
            "dependencies 必须是 pip 依赖字符串数组，没有依赖时返回空数组。"
            "生成代码时优先使用 Python 标准库，避免不必要依赖。"
        )

    def _build_user_prompt(self, spec: dict) -> str:
        prompt_payload = {
            "name": spec.get("name", ""),
            "description": spec.get("description", ""),
            "input_spec": spec.get("input_spec", ""),
            "output_spec": spec.get("output_spec", ""),
            "constraints": spec.get("constraints", ""),
            "example_input": spec.get("example_input", ""),
            "example_output": spec.get("example_output", ""),
        }
        return json.dumps(prompt_payload, ensure_ascii=False, indent=2)

    def _extract_message_content(self, response_data: dict) -> str:
        try:
            content = response_data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AINodeGenerationError(ErrorCode.AI_INVALID_RESPONSE, "AI 接口返回格式不符合 OpenAI 兼容协议") from exc

        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            text = "".join(text_parts).strip()
            if text:
                return text

        raise AINodeGenerationError(ErrorCode.AI_INVALID_RESPONSE, "AI 接口未返回可解析的文本内容")

    def _parse_generation_payload(self, content: str) -> dict:
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError as exc:
                    raise AINodeGenerationError(ErrorCode.AI_INVALID_RESPONSE, "AI 返回内容不是合法 JSON") from exc
            raise AINodeGenerationError(ErrorCode.AI_INVALID_RESPONSE, "AI 返回内容不是合法 JSON")

    def _validate_result(self, result_data: dict):
        if not isinstance(result_data, dict):
            raise AINodeGenerationError(ErrorCode.AI_INVALID_RESPONSE, "AI 返回内容必须是 JSON 对象")

        required_fields = ["description", "source_code", "config_schema", "dependencies"]
        missing = [field for field in required_fields if field not in result_data]
        if missing:
            raise AINodeGenerationError(ErrorCode.AI_INVALID_RESPONSE, f"AI 返回缺少字段: {', '.join(missing)}")

        if not isinstance(result_data["config_schema"], dict):
            raise AINodeGenerationError(ErrorCode.AI_INVALID_RESPONSE, "config_schema 必须是对象")

        if not isinstance(result_data["dependencies"], list):
            raise AINodeGenerationError(ErrorCode.AI_INVALID_RESPONSE, "dependencies 必须是数组")

        if not all(isinstance(dep, str) for dep in result_data["dependencies"]):
            raise AINodeGenerationError(ErrorCode.AI_INVALID_RESPONSE, "dependencies 必须是字符串数组")

        source_code = result_data["source_code"]
        if "def execute(self, input_data" not in source_code:
            raise AINodeGenerationError(ErrorCode.AI_GENERATION_FAILED, "生成代码缺少 execute(self, input_data) 函数")

        if "return" not in source_code:
            raise AINodeGenerationError(ErrorCode.AI_GENERATION_FAILED, "生成代码缺少返回值")
