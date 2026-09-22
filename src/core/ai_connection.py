"""AI connection probe shared by CLI and the settings worker."""
import json
import requests as _requests
from .log_manager import get_logger
logger = get_logger("ai_connection")


def check_ai_connection(base_url, api_key, model, timeout=30):
    try:
        missing = []
        if not base_url:
            missing.append("接口地址")
        if not api_key:
            missing.append("API 密钥")
        if not model:
            missing.append("模型")
        if missing:
            msg = f"配置不完整，缺少: {'、'.join(missing)}"
            logger.warning("AI 连接测试失败: %s", msg)
            return (False, msg)

        from urllib.parse import urlparse

        parsed = urlparse(base_url)
        if not parsed.scheme or parsed.scheme not in ("http", "https"):
            msg = "接口地址格式无效，需以 http:// 或 https:// 开头"
            logger.warning("AI 连接测试失败: %s (base_url=%s)", msg, base_url)
            return (False, msg)

        normalized = base_url.rstrip("/")
        if normalized.endswith("/chat/completions"):
            endpoint = normalized
        elif normalized.endswith("/v1"):
            endpoint = f"{normalized}/chat/completions"
        else:
            endpoint = f"{normalized}/v1/chat/completions"

        logger.info(
            "AI 连接测试: endpoint=%s, model=%s, timeout=%ds",
            endpoint,
            model,
            timeout,
        )

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 5,
            "stream": False,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        resp = _requests.post(
            endpoint, json=payload, headers=headers, timeout=timeout
        )

        logger.debug(
            "AI 连接测试响应: status=%d, len=%d",
            resp.status_code,
            len(resp.content),
        )

        if resp.status_code == 200:
            try:
                body = resp.json()
            except (ValueError, json.JSONDecodeError):
                text = resp.text.strip()
                if text.startswith("data:"):
                    body = None
                    for line in text.splitlines():
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            body = json.loads(data_str)
                            break
                        except (ValueError, json.JSONDecodeError):
                            continue
                    else:
                        msg = "响应为 SSE 流式格式，但未能解析出有效数据"
                        logger.error(
                            "AI 连接测试: %s, body=%.200s", msg, text[:200]
                        )
                        return (False, msg)
                else:
                    msg = "响应解析失败: 非 JSON 格式"
                    logger.error("AI 连接测试: %s, body=%.200s", msg, text[:200])
                    return (False, msg)
            if not isinstance(body, dict):
                return False, "响应解析失败: 未返回 JSON 对象"
            model_used = body.get("model", model)
            usage = body.get("usage", {})
            logger.info("AI 连接测试成功: model=%s, usage=%s", model_used, usage)
            return (True, f"连接成功 (模型: {model_used})")
        elif resp.status_code == 401:
            logger.warning("AI 连接测试: 认证失败 (401)")
            return (False, "认证失败，请检查 API 密钥是否正确")
        elif resp.status_code == 403:
            logger.warning("AI 连接测试: 权限不足 (403)")
            return (False, "权限不足，API 密钥可能无权访问该模型")
        elif resp.status_code == 404:
            logger.warning("AI 连接测试: 端点未找到 (404), endpoint=%s", endpoint)
            return (
                False, "接口地址未找到 (404)，请检查接口地址和模型名称是否正确"
            )
        elif resp.status_code == 429:
            logger.warning("AI 连接测试: 请求过于频繁 (429)")
            return (False, "请求过于频繁 (429)，请稍后重试")
        elif resp.status_code >= 500:
            logger.error("AI 连接测试: 服务端错误 (%d)", resp.status_code)
            return (
                False, f"服务端错误 ({resp.status_code})，请稍后重试"
            )
        else:
            try:
                err_body = resp.json()
                err_msg = err_body.get("error", {}).get("message", resp.text[:200])
            except Exception:
                err_msg = resp.text[:200]
            logger.warning(
                "AI 连接测试: HTTP %d, error=%s", resp.status_code, err_msg
            )
            return (False, f"HTTP {resp.status_code}: {err_msg}")

    except _requests.exceptions.SSLError as e:
        logger.error("AI 连接测试: SSL 错误: %s", e)
        return (False, f"SSL 证书错误，请检查接口地址是否正确")
    except _requests.exceptions.ConnectionError as e:
        logger.error("AI 连接测试: 连接失败: %s", e)
        return (False, "连接失败，请检查接口地址是否可达")
    except _requests.exceptions.Timeout:
        logger.warning("AI 连接测试: 请求超时 (%ds)", timeout)
        return (
            False, f"请求超时 ({timeout}s)，请检查网络或增大超时时间"
        )
    except _requests.exceptions.TooManyRedirects:
        logger.error("AI 连接测试: 重定向过多")
        return (False, "重定向过多，请检查接口地址")
    except Exception as e:
        logger.exception("AI 连接测试: 未知异常")
        return (False, f"未知错误: {e}")
