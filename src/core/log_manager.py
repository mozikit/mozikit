"""
日志管理器
提供统一的日志记录功能，支持同时输出到控制台和文件
"""
import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_initialized = False
_log_dir = None

LOG_FORMAT = "[%(asctime)s][%(levelname)s][%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_ENCODING = "utf-8"
LOG_LEVEL = logging.DEBUG
CONSOLE_LEVEL = logging.INFO
FILE_LEVEL = logging.INFO
RETENTION_DAYS = 30


def _get_log_dir() -> Path:
    """获取日志文件存储目录"""
    if getattr(sys, "frozen", False):
        appdata = os.environ.get("APPDATA")
        if not appdata:
            appdata = str(Path.home() / "AppData" / "Roaming")
        log_dir = Path(appdata) / "Mozikit" / "logs"
    else:
        log_dir = Path(os.getcwd()) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def init_logging(level: int = None) -> Path:
    """
    初始化全局日志系统

    Args:
        level: 日志级别，默认为 DEBUG

    Returns:
        日志文件目录路径
    """
    global _initialized, _log_dir

    if _initialized:
        return _log_dir

    _log_dir = _get_log_dir()
    root_logger = logging.getLogger()
    root_logger.setLevel(level or LOG_LEVEL)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(CONSOLE_LEVEL)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    log_file = _log_dir / "mozikit.log"
    file_handler = TimedRotatingFileHandler(
        str(log_file),
        when="midnight",
        interval=1,
        backupCount=RETENTION_DAYS,
        encoding=LOG_ENCODING,
    )
    file_handler.suffix = "%Y-%m-%d.log"
    file_handler.setLevel(FILE_LEVEL)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    _initialized = True
    root_logger.info("日志系统已初始化，日志目录: %s", _log_dir)
    return _log_dir


def get_logger(name: str = None) -> logging.Logger:
    """
    获取命名日志记录器

    Args:
        name: 日志记录器名称，通常使用模块名

    Returns:
        Logger 实例
    """
    if not _initialized:
        init_logging()
    return logging.getLogger(name)


def get_log_dir() -> Path:
    """获取当前日志目录"""
    return _log_dir or _get_log_dir()
