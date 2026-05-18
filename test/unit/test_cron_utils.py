"""
CronUtils 单元测试 — 无 PySide6 依赖
"""
import os
import sys
import unittest
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.core.cron_utils import CronUtils
from src.core.exceptions import LocalFlowError


class TestCronUtilsParseCron(unittest.TestCase):
    """Cron 表达式解析"""

    def test_parse_standard_expression(self):
        parts = CronUtils.parse_cron("*/15 * * * 1-5")
        self.assertEqual(parts, ("*/15", "*", "*", "*", "1-5"))

    def test_parse_normalizes_whitespace(self):
        parts = CronUtils.parse_cron("  0    8  *  *  1,3,5  ")
        self.assertEqual(parts, ("0", "8", "*", "*", "1,3,5"))

    def test_parse_rejects_empty(self):
        with self.assertRaises(LocalFlowError):
            CronUtils.parse_cron("")

    def test_parse_rejects_wrong_field_count(self):
        with self.assertRaises(LocalFlowError):
            CronUtils.parse_cron("0 0 * *")


class TestCronUtilsValidateCron(unittest.TestCase):
    """Cron 表达式校验"""

    def test_validates_and_normalizes(self):
        normalized = CronUtils.validate_cron("  */15   *  *  *  1-5  ")
        self.assertEqual(normalized, "*/15 * * * 1-5")

    def test_rejects_invalid_field_count(self):
        with self.assertRaisesRegex(LocalFlowError, "无效的 Cron"):
            CronUtils.validate_cron("0 0 * *")

    def test_rejects_invalid_hour_range(self):
        with self.assertRaisesRegex(LocalFlowError, "无效的 Cron 字段范围"):
            CronUtils.validate_cron("0 24 * * *")

    def test_rejects_invalid_minute_range(self):
        with self.assertRaisesRegex(LocalFlowError, "无效的 Cron 字段范围"):
            CronUtils.validate_cron("60 * * * *")

    def test_rejects_invalid_day_range(self):
        with self.assertRaisesRegex(LocalFlowError, "无效的 Cron 字段范围"):
            CronUtils.validate_cron("0 0 32 * *")

    def test_accepts_sunday_as_7(self):
        """周日可以用 0 或 7 表示（validate 保留原始值，format_next_run 处理转换）"""
        normalized = CronUtils.validate_cron("0 0 * * 7")
        self.assertEqual(normalized, "0 0 * * 7")

    def test_accepts_step_expressions(self):
        normalized = CronUtils.validate_cron("*/10 */2 * * *")
        self.assertEqual(normalized, "*/10 */2 * * *")

    def test_accepts_list_expressions(self):
        normalized = CronUtils.validate_cron("0,30 9-17 * * 1-5")
        self.assertEqual(normalized, "0,30 9-17 * * 1-5")

    def test_rejects_negative_step(self):
        with self.assertRaisesRegex(LocalFlowError, "步长"):
            CronUtils.validate_cron("*/-5 * * * *")

    def test_rejects_empty_expression(self):
        with self.assertRaises(LocalFlowError):
            CronUtils.validate_cron("   ")

    def test_accepts_large_step_values(self):
        """*/100 应被接受（虽然实际可匹配的分钟很少）"""
        normalized = CronUtils.validate_cron("*/100 * * * *")
        self.assertEqual(normalized, "*/100 * * * *")

    def test_accepts_double_digit_minute_list(self):
        """多值列表 5,10,15"""
        normalized = CronUtils.validate_cron("5,10,15 * * * *")
        self.assertEqual(normalized, "5,10,15 * * * *")


class TestCronUtilsFormatNextRun(unittest.TestCase):
    """下一次执行时间计算"""

    def test_minutely(self):
        """每分钟"""
        next_run = CronUtils.format_next_run(
            "*/1 * * * *", datetime(2026, 4, 25, 18, 27, 30)
        )
        self.assertEqual(next_run, datetime(2026, 4, 25, 18, 28, 0))

    def test_every_5_minutes_from_start(self):
        """每5分钟，从整点开始"""
        next_run = CronUtils.format_next_run(
            "*/5 * * * *", datetime(2026, 4, 25, 18, 1, 0)
        )
        # 18:01 → 下一个 5 的倍数是 18:05
        self.assertEqual(next_run, datetime(2026, 4, 25, 18, 5, 0))

    def test_every_5_minutes_near_boundary(self):
        """每5分钟，接近边界"""
        next_run = CronUtils.format_next_run(
            "*/5 * * * *", datetime(2026, 4, 25, 18, 58, 0)
        )
        # 18:58 → 19:00
        self.assertEqual(next_run, datetime(2026, 4, 25, 19, 0, 0))

    def test_hourly(self):
        """每小时"""
        next_run = CronUtils.format_next_run(
            "0 * * * *", datetime(2026, 4, 25, 18, 27, 30)
        )
        self.assertEqual(next_run, datetime(2026, 4, 25, 19, 0, 0))

    def test_daily_at_midnight(self):
        """每天午夜"""
        next_run = CronUtils.format_next_run(
            "0 0 * * *", datetime(2026, 4, 25, 18, 27, 30)
        )
        self.assertEqual(next_run, datetime(2026, 4, 26, 0, 0, 0))

    def test_daily_at_specific_time(self):
        """每天特定时间"""
        next_run = CronUtils.format_next_run(
            "30 8 * * *", datetime(2026, 4, 25, 18, 27, 30)
        )
        self.assertEqual(next_run, datetime(2026, 4, 26, 8, 30, 0))

    def test_weekly_on_sunday(self):
        """每周日"""
        next_run = CronUtils.format_next_run(
            "0 0 * * 0", datetime(2026, 4, 25, 18, 27, 30)
        )
        # 2026-04-25 是周六，下一个周日是 04-26
        self.assertEqual(next_run, datetime(2026, 4, 26, 0, 0, 0))

    def test_weekly_on_monday(self):
        """每周一"""
        next_run = CronUtils.format_next_run(
            "0 0 * * 1", datetime(2026, 4, 25, 18, 27, 30)
        )
        # 2026-04-25 是周六，下一个周一是 04-27
        self.assertEqual(next_run, datetime(2026, 4, 27, 0, 0, 0))

    def test_monthly_on_first(self):
        """每月1号"""
        next_run = CronUtils.format_next_run(
            "0 0 1 * *", datetime(2026, 4, 25, 18, 27, 30)
        )
        self.assertEqual(next_run, datetime(2026, 5, 1, 0, 0, 0))

    def test_monthly_on_15th(self):
        """每月15号"""
        next_run = CronUtils.format_next_run(
            "0 0 15 * *", datetime(2026, 4, 25, 18, 27, 30)
        )
        self.assertEqual(next_run, datetime(2026, 5, 15, 0, 0, 0))

    def test_weekday_only(self):
        """工作日（周一至周五）"""
        # 2026-04-25 是周六，下一个周一是 04-27
        next_run = CronUtils.format_next_run(
            "0 9 * * 1-5", datetime(2026, 4, 25, 18, 27, 30)
        )
        self.assertEqual(next_run, datetime(2026, 4, 27, 9, 0, 0))

    def test_specific_hours_and_minutes(self):
        """特定小时和分钟的组合"""
        next_run = CronUtils.format_next_run(
            "30 14 * * *", datetime(2026, 4, 25, 13, 0, 0)
        )
        self.assertEqual(next_run, datetime(2026, 4, 25, 14, 30, 0))

    def test_current_minute_matches_immediately(self):
        """当前分钟恰好匹配时应跳到下一分钟"""
        next_run = CronUtils.format_next_run(
            "*/5 * * * *", datetime(2026, 4, 25, 18, 5, 0)
        )
        self.assertEqual(next_run, datetime(2026, 4, 25, 18, 10, 0))

    def test_edge_case_end_of_month(self):
        """月末边界"""
        next_run = CronUtils.format_next_run(
            "0 0 1 * *", datetime(2026, 1, 31, 12, 0, 0)
        )
        self.assertEqual(next_run, datetime(2026, 2, 1, 0, 0, 0))

    def test_edge_case_end_of_year(self):
        """年末边界"""
        next_run = CronUtils.format_next_run(
            "0 0 1 * *", datetime(2026, 12, 31, 12, 0, 0)
        )
        self.assertEqual(next_run, datetime(2027, 1, 1, 0, 0, 0))


class TestCronUtilsFormatNextRunEdgeCases(unittest.TestCase):
    """format_next_run 边界情况"""

    def test_default_from_time_is_datetime_now(self):
        """不传 from_time 应使用当前时间（不抛异常）"""
        result = CronUtils.format_next_run("0 0 * * *")
        self.assertIsInstance(result, datetime)

    def test_step_near_hour_boundary(self):
        """*/15 在 14:58 应跳到 15:00"""
        next_run = CronUtils.format_next_run(
            "*/15 * * * *", datetime(2026, 4, 25, 14, 58, 0)
        )
        self.assertEqual(next_run, datetime(2026, 4, 25, 15, 0, 0))

    def test_step_near_midnight_boundary(self):
        """*/30 在 23:45 应跳到 00:00"""
        next_run = CronUtils.format_next_run(
            "*/30 * * * *", datetime(2026, 4, 25, 23, 45, 0)
        )
        self.assertEqual(next_run, datetime(2026, 4, 26, 0, 0, 0))

    def test_specific_minute_across_hour(self):
        """每小时的第 05 分，23:05 → 第二天 00:05"""
        next_run = CronUtils.format_next_run(
            "5 * * * *", datetime(2026, 4, 25, 23, 6, 0)
        )
        self.assertEqual(next_run, datetime(2026, 4, 26, 0, 5, 0))

    def test_weekly_across_year_boundary(self):
        """跨年的每周执行"""
        next_run = CronUtils.format_next_run(
            "0 0 * * 1", datetime(2026, 12, 31, 12, 0, 0)
        )
        # 2026-12-31 是周四，下一个周一是 2027-01-04
        self.assertEqual(next_run, datetime(2027, 1, 4, 0, 0, 0))

    def test_daily_leap_year_feb_28(self):
        """闰年 2 月 28 日运行每日任务"""
        next_run = CronUtils.format_next_run(
            "0 0 * * *", datetime(2028, 2, 28, 12, 0, 0)
        )
        self.assertEqual(next_run, datetime(2028, 2, 29, 0, 0, 0))

    def test_complex_expression_weekday_and_hour(self):
        """工作日特定小时: 0,30 9-17 * * 1-5"""
        # 周六 17:30 → 下周一 09:00
        next_run = CronUtils.format_next_run(
            "0,30 9-17 * * 1-5", datetime(2026, 4, 25, 17, 30, 0)
        )
        # 2026-04-25 是周六
        self.assertEqual(next_run, datetime(2026, 4, 27, 9, 0, 0))

    def test_complex_expression_with_step(self):
        """复杂步长表达式: 1-59/2 * * * *（每2分钟）"""
        next_run = CronUtils.format_next_run(
            "1-59/2 * * * *", datetime(2026, 4, 25, 18, 0, 0)
        )
        # 从 18:00 开始，下一个符合 1-59/2 的是 18:01
        self.assertEqual(next_run, datetime(2026, 4, 25, 18, 1, 0))


class TestCronUtilsCRON_MAP(unittest.TestCase):
    """预设 Cron 快捷方式"""

    def test_minutely(self):
        self.assertEqual(CronUtils.CRON_MAP["minutely"], "*/1 * * * *")

    def test_hourly(self):
        self.assertEqual(CronUtils.CRON_MAP["hourly"], "0 * * * *")

    def test_daily(self):
        self.assertEqual(CronUtils.CRON_MAP["daily"], "0 0 * * *")

    def test_weekly(self):
        self.assertEqual(CronUtils.CRON_MAP["weekly"], "0 0 * * 0")

    def test_monthly(self):
        self.assertEqual(CronUtils.CRON_MAP["monthly"], "0 0 1 * *")


class TestCronUtilsNormalizeCron(unittest.TestCase):
    """Cron 表达式标准化"""

    def test_strips_extra_whitespace(self):
        self.assertEqual(CronUtils.normalize_cron("  */5   *  *  *  *  "), "*/5 * * * *")

    def test_raises_on_empty(self):
        with self.assertRaises(LocalFlowError):
            CronUtils.normalize_cron("")

    def test_tabs_in_expression(self):
        """含制表符的表达式应被标准化"""
        self.assertEqual(
            CronUtils.normalize_cron("0\t0 * * *"), "0 0 * * *"
        )

    def test_mixed_whitespace(self):
        """混合空白字符"""
        self.assertEqual(
            CronUtils.normalize_cron("  0  \t 0  \n  *  *  *  "), "0 0 * * *"
        )


if __name__ == "__main__":
    unittest.main()
