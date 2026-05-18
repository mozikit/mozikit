"""
安全凭证存储模块
使用操作系统密钥链（Windows Credential Manager / macOS Keychain / Linux Secret Service）
安全存储 API 密钥、OAuth Token 等敏感凭证。

优先级：
1. keyring 库（操作系统密钥链）—— 最安全
2. 改进的本地加密（PBKDF2 + AES-CTR via hashlib）—— keyring 不可用时的降级方案

迁移策略：
- 读取时：先尝试 keyring，再尝试旧 XOR 解密（兼容迁移），最后尝试明文
- 写入时：优先使用 keyring，不可用时使用改进的本地加密
"""
import base64
import hashlib
import hmac
import os
import struct
from typing import Optional

from src.core.log_manager import get_logger

logger = get_logger("credential_store")

# ── keyring 可用性检测 ──

_keyring_available: Optional[bool] = None


def _check_keyring() -> bool:
    """检测 keyring 库是否可用"""
    global _keyring_available
    if _keyring_available is not None:
        return _keyring_available
    try:
        import keyring  # noqa: F401
        # 尝试获取后端，确保不仅仅是 import 成功
        backend = keyring.get_keyring()
        if backend and hasattr(backend, 'priority') and backend.priority < 0:
            # priority < 0 表示是不可用的后端（如 PlaintextKeyring）
            _keyring_available = False
            logger.info("keyring 后端不可用（priority=%s），将使用本地加密", getattr(backend, 'priority', 'unknown'))
        else:
            _keyring_available = True
            logger.info("keyring 可用，后端: %s", type(backend).__name__)
    except Exception as e:
        _keyring_available = False
        logger.info("keyring 不可用（%s），将使用本地加密", e)
    return _keyring_available


# ── keyring 操作 ──

KEYRING_SERVICE = "LocalFlow"


def _keyring_get(key: str) -> Optional[str]:
    """从操作系统密钥链读取凭证"""
    if not _check_keyring():
        return None
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, key)
    except Exception as e:
        logger.warning("从 keyring 读取 %s 失败: %s", key, e)
        return None


def _keyring_set(key: str, value: str) -> bool:
    """将凭证写入操作系统密钥链"""
    if not _check_keyring():
        return False
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, key, value)
        return True
    except Exception as e:
        logger.warning("写入 keyring %s 失败: %s", key, e)
        return False


def _keyring_delete(key: str) -> bool:
    """从操作系统密钥链删除凭证"""
    if not _check_keyring():
        return False
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, key)
        return True
    except keyring.errors.PasswordDeleteError:
        return True  # 已删除或不存在
    except Exception:
        return False


# ── 改进的本地加密（降级方案） ──
# 使用 PBKDF2-HMAC-SHA256 派生密钥 + SHA-256 CTR 模式流密码 + HMAC 完整性校验
# 格式: base64(salt[16] + iv[16] + ciphertext[N] + hmac[32])

_LOCAL_ENC_MARKER = "$lf2$"  # 前缀标识新加密格式


def _derive_key(salt: bytes, info: str = "LocalFlow-credential-key") -> bytes:
    """使用 PBKDF2 从机器特定信息派生 32 字节密钥"""
    import getpass
    import socket

    raw = (socket.gethostname() + getpass.getuser()).encode("utf-8")
    return hashlib.pbkdf2_hmac(
        "sha256",
        raw,
        salt,
        iterations=200_000,  # OWASP 推荐 >= 600k，桌面场景用 200k 平衡安全与性能
        dklen=32,
    )


def _local_encrypt(plain_text: str) -> str:
    """改进的本地加密：PBKDF2 + SHA-256 CTR + HMAC"""
    if not plain_text:
        return ""

    salt = os.urandom(16)
    iv = os.urandom(16)
    key = _derive_key(salt)

    # SHA-256 CTR 模式流密码：使用 SHA-256(counter) 生成密钥流
    data = plain_text.encode("utf-8")
    keystream = b""
    counter = 0
    remaining = len(data)
    enc_key = hmac.new(key, b"encryption", hashlib.sha256).digest()  # 子密钥
    while remaining > 0:
        block_input = iv + struct.pack(">Q", counter)
        block = hmac.new(enc_key, block_input, hashlib.sha256).digest()
        take = min(32, remaining)
        keystream += block[:take]
        counter += 1
        remaining -= take

    ciphertext = bytes(a ^ b for a, b in zip(data, keystream))

    # HMAC 完整性校验
    auth_key = hmac.new(key, b"authentication", hashlib.sha256).digest()
    mac = hmac.new(auth_key, salt + iv + ciphertext, hashlib.sha256).digest()

    payload = salt + iv + ciphertext + mac
    return _LOCAL_ENC_MARKER + base64.b64encode(payload).decode("utf-8")


def _local_decrypt(cipher_text: str) -> Optional[str]:
    """改进的本地解密，返回 None 表示解密失败"""
    if not cipher_text:
        return None

    # 检查是否为新格式
    if not cipher_text.startswith(_LOCAL_ENC_MARKER):
        return None

    try:
        payload = base64.b64decode(cipher_text[len(_LOCAL_ENC_MARKER):])
    except Exception:
        return None

    if len(payload) < 16 + 16 + 32:  # salt + iv + hmac
        return None

    salt = payload[:16]
    iv = payload[16:32]
    mac = payload[-32:]
    ciphertext = payload[32:-32]

    # 验证 HMAC
    key = _derive_key(salt)
    auth_key = hmac.new(key, b"authentication", hashlib.sha256).digest()
    expected_mac = hmac.new(auth_key, salt + iv + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected_mac):
        logger.warning("本地加密数据 HMAC 校验失败，数据可能被篡改")
        return None

    # 解密
    enc_key = hmac.new(key, b"encryption", hashlib.sha256).digest()
    keystream = b""
    counter = 0
    remaining = len(ciphertext)
    while remaining > 0:
        block_input = iv + struct.pack(">Q", counter)
        block = hmac.new(enc_key, block_input, hashlib.sha256).digest()
        take = min(32, remaining)
        keystream += block[:take]
        counter += 1
        remaining -= take

    plaintext_bytes = bytes(a ^ b for a, b in zip(ciphertext, keystream))
    try:
        return plaintext_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None


# ── 旧 XOR 解密（仅用于迁移） ──

def _legacy_xor_decrypt(cipher_text: str) -> Optional[str]:
    """兼容旧版 XOR 解密，仅用于从旧格式迁移"""
    if not cipher_text:
        return None

    # 跳过新格式
    if cipher_text.startswith(_LOCAL_ENC_MARKER):
        return None

    try:
        import getpass
        import socket

        raw = (socket.gethostname() + getpass.getuser()).encode("utf-8")
        digest = hashlib.sha256(raw).digest()
        key = digest[:16]

        xored = base64.b64decode(cipher_text)
        data = bytes(b ^ key[i % len(key)] for i, b in enumerate(xored))
        return data.decode("utf-8")
    except Exception:
        return None


# ── 公开 API ──

def store_credential(key: str, value: str) -> str:
    """安全存储凭证

    优先使用操作系统密钥链，不可用时使用改进的本地加密。
    返回应写入 config.json 的值（占位符或本地加密值）。

    Args:
        key: 凭证键名（如 "ai_api_key", "github_token"）
        value: 凭证明文值

    Returns:
        应写入 config.json 的值：
        - keyring 可用时: "$keyring:{key}$" 占位符
        - keyring 不可用时: "$lf2$..." 本地加密值
    """
    if not value:
        return ""

    # 优先 keyring
    if _keyring_set(key, value):
        return f"$keyring:{key}$"

    # 降级到本地加密
    encrypted = _local_encrypt(value)
    if encrypted:
        return encrypted

    logger.error("无法安全存储凭证 %s", key)
    # 最后降级：返回明文（不应发生）
    return value


def retrieve_credential(key: str, config_value: str = "", skip_legacy: bool = False) -> str:
    """安全读取凭证

    读取优先级：
    1. 操作系统密钥链（config_value 为 $keyring:...$ 占位符时）
    2. 新本地加密格式（$lf2$ 前缀）
    3. 旧 XOR 加密格式（兼容迁移，读取后自动升级到 keyring/新加密）
    4. 明文（兼容旧数据，读取后自动升级）

    Args:
        key: 凭证键名
        config_value: config.json 中存储的值（可能是占位符、加密值或旧格式值）
        skip_legacy: 若为 True，跳过步骤 3-4（旧格式迁移），仅支持新格式

    Returns:
        凭证明文值
    """
    # 1. 尝试 keyring
    value = _keyring_get(key)
    if value:
        return value

    if not config_value:
        return ""

    # 2. 尝试新本地加密格式
    if config_value.startswith(_LOCAL_ENC_MARKER):
        decrypted = _local_decrypt(config_value)
        if decrypted:
            # 迁移到 keyring
            if _keyring_set(key, decrypted):
                logger.info("凭证 %s 已从本地加密迁移至系统密钥链", key)
            return decrypted
        logger.warning("凭证 %s 本地解密失败", key)
        return ""

    # 3. keyring 占位符但 keyring 中没有数据（可能换了机器）
    if config_value.startswith("$keyring:"):
        logger.warning("凭证 %s 的 keyring 占位符存在但密钥链中无数据", key)
        return ""

    if skip_legacy:
        logger.info("凭证 %s: 跳过旧格式兼容（credential_store_version >= 2），密钥链也不可用，返回空", key)
        return ""

    # 4. 尝试旧 XOR 格式（兼容迁移）
    legacy_value = _legacy_xor_decrypt(config_value)
    if legacy_value:
        # 迁移到 keyring 或新本地加密
        if _keyring_set(key, legacy_value):
            logger.info("凭证 %s 已从旧 XOR 格式迁移至系统密钥链", key)
        else:
            logger.info("凭证 %s 已从旧 XOR 格式读取（keyring 不可用）", key)
        return legacy_value

    # 5. 视为明文（兼容旧数据或用户直接编辑的配置）
    if config_value and len(config_value) < 200:
        logger.info("凭证 %s 为明文存储，将迁移至安全存储", key)
        _keyring_set(key, config_value)  # 尝试迁移，失败也无所谓
        return config_value

    return ""


def delete_credential(key: str) -> bool:
    """删除安全存储的凭证

    Args:
        key: 凭证键名

    Returns:
        是否删除成功
    """
    _keyring_delete(key)
    return True
