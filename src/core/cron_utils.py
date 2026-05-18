"""
Cron 表达式工具 — 无 PySide6 依赖
提供解析、校验、匹配、下一次执行时间计算等功能。
"""
from datetime import datetime, timedelta
from typing import List, Tuple

from src.core.exceptions import ErrorCode, LocalFlowError


class CronUtils:
    """Cron 表达式工具集"""

    CRON_MAP = {
        "minutely": "*/1 * * * *",
        "hourly": "0 * * * *",
        "daily": "0 0 * * *",
        "weekly": "0 0 * * 0",
        "monthly": "0 0 1 * *",
    }

    @staticmethod
    def parse_cron(cron_expr: str) -> tuple:
        """解析Cron表达式，返回(分,时,日,月,周)"""
        normalized = CronUtils.normalize_cron(cron_expr)
        parts = normalized.split()
        if len(parts) != 5:
            raise LocalFlowError(ErrorCode.INVALID_CRON_EXPRESSION, f"无效的 Cron 表达式: {normalized}")
        return tuple(p for p in parts)

    @staticmethod
    def normalize_cron(cron_expr: str) -> str:
        """标准化 Cron 表达式空白"""
        normalized = " ".join(str(cron_expr or "").split())
        if not normalized:
            raise LocalFlowError(ErrorCode.INVALID_CRON_EXPRESSION, "Cron 表达式不能为空")
        return normalized

    @staticmethod
    def _parse_field_parts(
        expr: str,
        min_value: int,
        max_value: int,
        *,
        allow_sunday_seven: bool = False,
    ) -> List[Tuple[int, int, int]]:
        """解析并校验单个 Cron 字段"""
        expr = (expr or "").strip()
        if not expr:
            raise LocalFlowError(ErrorCode.INVALID_CRON_EXPRESSION, "Cron 字段不能为空")

        def parse_value(token: str) -> int:
            try:
                number = int(token)
            except ValueError as exc:
                raise LocalFlowError(ErrorCode.INVALID_CRON_EXPRESSION, f"无效的 Cron 字段值: {token}") from exc
            if allow_sunday_seven and number == 7:
                number = 0
            return number

        parsed_parts = []
        for part in expr.split(","):
            part = part.strip()
            if not part:
                raise LocalFlowError(ErrorCode.INVALID_CRON_EXPRESSION, f"无效的 Cron 字段: {expr}")

            step = 1
            base = part
            if "/" in part:
                base, step_text = part.split("/", 1)
                if "/" in step_text or not step_text:
                    raise LocalFlowError(ErrorCode.INVALID_CRON_EXPRESSION, f"无效的 Cron 步长: {expr}")
                try:
                    step = int(step_text)
                except ValueError as exc:
                    raise LocalFlowError(ErrorCode.INVALID_CRON_EXPRESSION, f"无效的 Cron 步长: {expr}") from exc
                if step <= 0:
                    raise LocalFlowError(ErrorCode.INVALID_CRON_EXPRESSION, f"无效的 Cron 步长: {expr}")

            if base == "*":
                start = min_value
                end = max_value
            elif "-" in base:
                start_text, end_text = base.split("-", 1)
                start = parse_value(start_text)
                end = parse_value(end_text)
            else:
                start = parse_value(base)
                end = parse_value(base)

            if start < min_value or end > max_value or start > end:
                raise LocalFlowError(ErrorCode.INVALID_CRON_EXPRESSION, f"无效的 Cron 字段范围: {expr}")

            parsed_parts.append((start, end, step))

        return parsed_parts

    @staticmethod
    def _matches_field(
        value: int,
        expr: str,
        min_value: int,
        max_value: int,
        *,
        allow_sunday_seven: bool = False,
    ) -> bool:
        """判断单个字段是否匹配 Cron 表达式"""
        for start, end, step in CronUtils._parse_field_parts(
            expr,
            min_value,
            max_value,
            allow_sunday_seven=allow_sunday_seven,
        ):
            if start <= value <= end and (value - start) % step == 0:
                return True
        return False

    @staticmethod
    def validate_cron(cron_expr: str) -> str:
        """校验 Cron 表达式并返回标准化结果"""
        minute, hour, day, month, dow = CronUtils.parse_cron(cron_expr)
        CronUtils._parse_field_parts(minute, 0, 59)
        CronUtils._parse_field_parts(hour, 0, 23)
        CronUtils._parse_field_parts(day, 1, 31)
        CronUtils._parse_field_parts(month, 1, 12)
        CronUtils._parse_field_parts(dow, 0, 6, allow_sunday_seven=True)
        return f"{minute} {hour} {day} {month} {dow}"

    @staticmethod
    def format_next_run(cron_expr: str, from_time: datetime = None) -> datetime:
        """计算下一次执行时间"""
        if from_time is None:
            from_time = datetime.now()

        minute, hour, day, month, dow = CronUtils.parse_cron(cron_expr)
        next_time = from_time.replace(second=0, microsecond=0) + timedelta(minutes=1)

        for _ in range(365 * 24 * 60):
            current_minute = next_time.minute
            current_hour = next_time.hour
            current_day = next_time.day
            current_month = next_time.month
            current_dow = next_time.isoweekday() % 7

            match = True
            if not CronUtils._matches_field(current_minute, minute, 0, 59):
                match = False
            if match and not CronUtils._matches_field(current_hour, hour, 0, 23):
                match = False
            if match and not CronUtils._matches_field(current_day, day, 1, 31):
                match = False
            if match and not CronUtils._matches_field(current_month, month, 1, 12):
                match = False
            if match and not CronUtils._matches_field(
                current_dow, dow, 0, 6, allow_sunday_seven=True
            ):
                match = False

            if match:
                return next_time

            next_time += timedelta(minutes=1)

        return from_time + timedelta(days=365)
