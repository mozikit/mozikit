"""
代码安全审查模块
提供共享的代码安全扫描、风险评级和文件完整性校验功能
供 GitHub 节点下载、AI 节点生成、官方节点更新等场景统一使用
"""
import hashlib
import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class SafetyReviewResult:
    """代码安全审查结果"""

    risk_level: str  # "high", "medium", "low", "safe"
    high_risks: List[str] = field(default_factory=list)
    medium_risks: List[str] = field(default_factory=list)
    low_risks: List[str] = field(default_factory=list)

    @property
    def has_risks(self) -> bool:
        return bool(self.high_risks or self.medium_risks or self.low_risks)

    def all_risks(self) -> List[str]:
        return self.high_risks + self.medium_risks + self.low_risks


# ── 高风险模式：可直接执行系统命令或任意代码 ──

_HIGH_RISK_PATTERNS = [
    (r'\bos\.system\b', '调用了 os.system（执行系统命令）'),
    (r'\bos\.popen\b', '调用了 os.popen（执行系统命令）'),
    (r'\bsubprocess\.(call|run|Popen)\b', '调用了 subprocess 命令执行函数'),
    (r'\bexec\s*\(', '调用了 exec()（动态执行代码）'),
    (r'\beval\s*\(', '调用了 eval()（动态执行代码）'),
    (r'\b__import__\s*\(', '调用了 __import__()（动态导入）'),
    (r'\bctypes\b', '导入了 ctypes（可调用C函数，绕过安全限制）'),
    (r'\bpickle\.loads?\b', '调用了 pickle 反序列化（可执行任意代码）'),
    (r'\bos\.remove\b', '调用了 os.remove（删除文件）'),
    (r'\bshutil\.rmtree\b', '调用了 shutil.rmtree（递归删除目录）'),
]

# ── 中风险模式：可能涉及文件写入、网络访问等 ──

_MEDIUM_RISK_PATTERNS = [
    (r'\bopen\s*\([^)]*,\s*[\'"]w[\'"]', '使用 open() 写模式打开文件'),
    (r'\bopen\s*\([^)]*,\s*[\'"]a[\'"]', '使用 open() 追加模式打开文件'),
    (r'\bsocket\b', '导入了 socket（网络访问）'),
    (r'\bos\.environ\b', '访问了 os.environ（环境变量操作）'),
    (r'\bos\.getcwd\b', '调用了 os.getcwd（获取工作目录）'),
    (r'\bos\.listdir\b', '调用了 os.listdir（列出目录内容）'),
    (r'\bos\.path\.join\b', '调用了 os.path.join（路径拼接，可能用于敏感路径）'),
    (r'\bshutil\.copy\b', '调用了 shutil.copy（复制文件）'),
    (r'\bshutil\.move\b', '调用了 shutil.move（移动文件）'),
]

# ── 低风险模式：仅导入或间接使用 ──

_LOW_RISK_PATTERNS = [
    (r'\bimport\s+os\b', '导入了 os 模块'),
    (r'\bimport\s+subprocess\b', '导入了 subprocess 模块'),
    (r'\bimport\s+shutil\b', '导入了 shutil 模块'),
    (r'\bimport\s+sys\b', '导入了 sys 模块'),
    (r'\bsys\.modules\b', '访问了 sys.modules（模块操作）'),
    (r'\bcompile\s*\(', '调用了 compile()（编译代码对象）'),
]

# ── 危险路径模式 ──

_DANGEROUS_PATH_PATTERNS = [
    (r'[\'"](?:/etc/|/etc\\)', '访问敏感系统路径 /etc/'),
    (r'[\'"](?:C:\\Windows\\|C:/Windows/)', '访问敏感系统路径 C:\\Windows\\'),
    (r'[\'"]~/\.ssh/', '访问敏感路径 ~/.ssh/'),
]


def review_code_safety(source_code: str) -> SafetyReviewResult:
    """对源代码进行静态安全审查，返回风险评级和风险列表"""
    high_risks = []
    medium_risks = []
    low_risks = []

    for pattern, description in _HIGH_RISK_PATTERNS:
        if re.search(pattern, source_code):
            high_risks.append(description)

    for pattern, description in _MEDIUM_RISK_PATTERNS:
        if re.search(pattern, source_code):
            medium_risks.append(description)

    for pattern, description in _LOW_RISK_PATTERNS:
        if re.search(pattern, source_code):
            low_risks.append(description)

    for pattern, description in _DANGEROUS_PATH_PATTERNS:
        if re.search(pattern, source_code):
            high_risks.append(description)

    if high_risks:
        risk_level = "high"
    elif medium_risks:
        risk_level = "medium"
    elif low_risks:
        risk_level = "low"
    else:
        risk_level = "safe"

    return SafetyReviewResult(
        risk_level=risk_level,
        high_risks=high_risks,
        medium_risks=medium_risks,
        low_risks=low_risks,
    )


def safety_review_to_warning(result: SafetyReviewResult) -> dict:
    """将安全审查结果转为 safety_warning 元数据格式

    Returns:
        {"risk_level": str, "risks": [str]}
    """
    return {
        "risk_level": result.risk_level,
        "risks": result.all_risks(),
    }


def compute_content_hash(content: str) -> str:
    """计算文本内容的 SHA-256 哈希值

    Args:
        content: 文本内容

    Returns:
        SHA-256 哈希的十六进制字符串
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def compute_file_hash(file_path: str) -> str:
    """计算文件的 SHA-256 哈希值

    Args:
        file_path: 文件路径

    Returns:
        SHA-256 哈希的十六进制字符串
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()
