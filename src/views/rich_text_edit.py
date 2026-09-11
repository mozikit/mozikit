"""Schema-driven Qt rich text editor."""

from PySide6.QtGui import QTextCharFormat, QTextListFormat
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QPushButton, QTextEdit, QVBoxLayout, QWidget


class RichTextEditWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        actions = (("B", self.toggle_bold), ("I", self.toggle_italic),
                   ("U", self.toggle_underline), ("H1", lambda: self.heading(1)),
                   ("H2", lambda: self.heading(2)), ("•", self.bullet_list),
                   ("1.", self.numbered_list), ("Link", self.insert_link),
                   ("清除格式", self.clear_format))
        for label, callback in actions:
            button = QPushButton(label)
            button.setMaximumHeight(26)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.editor = QTextEdit()
        self.editor.setAcceptRichText(True)
        layout.addWidget(self.editor)

    def _format(self, **values):
        fmt = QTextCharFormat()
        if "weight" in values:
            fmt.setFontWeight(values["weight"])
        if "italic" in values:
            fmt.setFontItalic(values["italic"])
        if "underline" in values:
            fmt.setFontUnderline(values["underline"])
        self.editor.mergeCurrentCharFormat(fmt)

    def toggle_bold(self):
        self._format(weight=QTextCharFormat.FontWeight.Bold)

    def toggle_italic(self):
        self._format(italic=True)

    def toggle_underline(self):
        self._format(underline=True)

    def heading(self, level):
        fmt = QTextCharFormat()
        fmt.setFontPointSize(20 if level == 1 else 16)
        self.editor.mergeCurrentCharFormat(fmt)

    def bullet_list(self):
        self.editor.textCursor().createList(QTextListFormat.Style.ListDisc)

    def numbered_list(self):
        self.editor.textCursor().createList(QTextListFormat.Style.ListDecimal)

    def insert_link(self):
        url, ok = QInputDialog.getText(self, "插入超链接", "URL:")
        if ok and url.strip():
            fmt = QTextCharFormat()
            fmt.setAnchor(True)
            fmt.setAnchorHref(url.strip())
            self.editor.mergeCurrentCharFormat(fmt)

    def clear_format(self):
        self.editor.setCurrentCharFormat(QTextCharFormat())

    def setHtml(self, value):
        self.editor.setHtml(value)

    def toHtml(self):
        return self.editor.toHtml()

    def setPlaceholderText(self, value):
        self.editor.setPlaceholderText(value)
