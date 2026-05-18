"""
Python 语法高亮器
为 QPlainTextEdit 提供 Python 代码语法高亮支持
"""
import re

from PySide6.QtCore import QRegularExpression, QRegularExpressionMatchIterator
from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
)


class PythonSyntaxHighlighter(QSyntaxHighlighter):
    """Python 语法高亮器"""

    # Python 关键字
    KEYWORDS = [
        "and", "as", "assert", "async", "await", "break", "class", "continue",
        "def", "del", "elif", "else", "except", "finally", "for", "from",
        "global", "if", "import", "in", "is", "lambda", "nonlocal", "not",
        "or", "pass", "raise", "return", "try", "while", "with", "yield",
        "True", "False", "None",
    ]

    # Python 内置函数
    BUILTINS = [
        "abs", "all", "any", "ascii", "bin", "bool", "breakpoint", "bytearray",
        "bytes", "callable", "chr", "classmethod", "compile", "complex",
        "delattr", "dict", "dir", "divmod", "enumerate", "eval", "exec",
        "filter", "float", "format", "frozenset", "getattr", "globals",
        "hasattr", "hash", "help", "hex", "id", "input", "int", "isinstance",
        "issubclass", "iter", "len", "list", "locals", "map", "max",
        "memoryview", "min", "next", "object", "oct", "open", "ord", "pow",
        "print", "property", "range", "repr", "reversed", "round", "set",
        "setattr", "slice", "sorted", "staticmethod", "str", "sum", "super",
        "tuple", "type", "vars", "zip", "__import__",
    ]

    def __init__(self, parent=None, colors: dict | None = None):
        super().__init__(parent)
        self._colors = colors or self._get_default_colors()
        self._setup_formats()
        self._setup_rules()

    def _get_default_colors(self) -> dict:
        """获取默认颜色配置"""
        return {
            "keyword": "#c678dd",      # 紫色 - 关键字
            "builtin": "#61afef",      # 蓝色 - 内置函数
            "string": "#98c379",       # 绿色 - 字符串
            "comment": "#5c6370",      # 灰色 - 注释
            "number": "#d19a66",       # 橙色 - 数字
            "decorator": "#e5c07b",    # 黄色 - 装饰器
            "class_name": "#e5c07b",   # 黄色 - 类名
            "function_name": "#61afef", # 蓝色 - 函数名
        }

    def _setup_formats(self):
        """设置文本格式"""
        # 关键字格式
        self.keyword_format = QTextCharFormat()
        self.keyword_format.setForeground(QColor(self._colors["keyword"]))
        self.keyword_format.setFontWeight(QFont.Weight.Bold)

        # 内置函数格式
        self.builtin_format = QTextCharFormat()
        self.builtin_format.setForeground(QColor(self._colors["builtin"]))

        # 字符串格式
        self.string_format = QTextCharFormat()
        self.string_format.setForeground(QColor(self._colors["string"]))

        # 注释格式
        self.comment_format = QTextCharFormat()
        self.comment_format.setForeground(QColor(self._colors["comment"]))
        self.comment_format.setFontItalic(True)

        # 数字格式
        self.number_format = QTextCharFormat()
        self.number_format.setForeground(QColor(self._colors["number"]))

        # 装饰器格式
        self.decorator_format = QTextCharFormat()
        self.decorator_format.setForeground(QColor(self._colors["decorator"]))

        # 类名格式
        self.class_name_format = QTextCharFormat()
        self.class_name_format.setForeground(QColor(self._colors["class_name"]))

        # 函数名格式
        self.function_name_format = QTextCharFormat()
        self.function_name_format.setForeground(QColor(self._colors["function_name"]))

    def _setup_rules(self):
        """设置高亮规则"""
        self.rules = []

        # 关键字规则
        keyword_pattern = r"\b(" + "|".join(re.escape(k) for k in self.KEYWORDS) + r")\b"
        self.rules.append((QRegularExpression(keyword_pattern), self.keyword_format))

        # 内置函数规则
        builtin_pattern = r"\b(" + "|".join(re.escape(b) for b in self.BUILTINS) + r")\b"
        self.rules.append((QRegularExpression(builtin_pattern), self.builtin_format))

        # 装饰器规则
        self.rules.append((
            QRegularExpression(r"@\w+(?:\.\w+)*"),
            self.decorator_format
        ))

        # 类定义规则 (class 后面的名称)
        self.rules.append((
            QRegularExpression(r"\bclass\s+(\w+)"),
            self.class_name_format
        ))

        # 函数定义规则 (def 后面的名称)
        self.rules.append((
            QRegularExpression(r"\bdef\s+(\w+)"),
            self.function_name_format
        ))

        # 数字规则 (整数、浮点数、十六进制、八进制、二进制)
        number_pattern = r"\b(?:0[xX][0-9a-fA-F]+|0[oO]?[0-7]+|0[bB][01]+|\d+\.?\d*(?:[eE][+-]?\d+)?)\b"
        self.rules.append((QRegularExpression(number_pattern), self.number_format))

        # 双引号字符串规则
        self.rules.append((
            QRegularExpression(r'"[^"\\]*(\\.[^"\\]*)*"'),
            self.string_format
        ))

        # 单引号字符串规则
        self.rules.append((
            QRegularExpression(r"'[^'\\]*(\\.[^'\\]*)*'"),
            self.string_format
        ))

        # 三引号字符串规则 (多行字符串)
        self.tri_single = (QRegularExpression(r"'''"), self.string_format)
        self.tri_double = (QRegularExpression(r'"""'), self.string_format)

        # 单行注释规则
        self.rules.append((
            QRegularExpression(r"#[^\n]*"),
            self.comment_format
        ))

    def highlightBlock(self, text: str):
        """高亮文本块"""
        # 应用基本规则
        for pattern, format_obj in self.rules:
            iterator: QRegularExpressionMatchIterator = pattern.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                # 如果是类或函数定义，只高亮捕获组（名称部分）
                if pattern.pattern().startswith(r"\bclass\s+") or \
                   pattern.pattern().startswith(r"\bdef\s+"):
                    if match.lastCapturedIndex() >= 1:
                        start = match.capturedStart(1)
                        length = match.capturedLength(1)
                    else:
                        continue
                else:
                    start = match.capturedStart()
                    length = match.capturedLength()
                self.setFormat(start, length, format_obj)

        # 处理多行字符串
        self._match_multiline(text, *self.tri_single)
        self._match_multiline(text, *self.tri_double)

    def _match_multiline(self, text: str, delimiter: QRegularExpression, format_obj: QTextCharFormat):
        """匹配多行字符串（三引号）"""
        # 获取当前块的状态
        state = self.previousBlockState()

        # 0 = 普通状态, 1 = 在三单引号内, 2 = 在三双引号内
        if state == -1:
            state = 0

        start_index = 0
        add = 0

        # 如果之前在多行字符串内
        if state == 1 and delimiter == self.tri_single[0]:
            start_index = 0
            add = 0
        elif state == 2 and delimiter == self.tri_double[0]:
            start_index = 0
            add = 0
        elif state == 0:
            # 查找起始分隔符
            match = delimiter.match(text)
            if match.hasMatch():
                start_index = match.capturedStart()
                add = match.capturedLength()
            else:
                return

        while start_index >= 0:
            # 查找结束分隔符
            match = delimiter.match(text, start_index + add)
            if match.hasMatch():
                end_index = match.capturedEnd()
                length = end_index - start_index
                self.setFormat(start_index, length, format_obj)
                start_index = -1  # 结束查找
                state = 0  # 回到普通状态
            else:
                # 没有找到结束符，高亮到行尾
                self.setFormat(start_index, len(text) - start_index, format_obj)
                # 设置状态表示在多行字符串内
                if delimiter == self.tri_single[0]:
                    state = 1
                else:
                    state = 2
                break

        self.setCurrentBlockState(state)
