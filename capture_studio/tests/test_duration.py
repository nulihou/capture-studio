import unittest

from capture_studio.duration import estimate_seconds, planned_seconds


class PlannedSeconds(unittest.TestCase):
    def test_presets(self):
        self.assertEqual(planned_seconds({"duration": "60 秒短检"}), 60)
        self.assertEqual(planned_seconds({"duration": "10 分钟关口"}), 650)
        self.assertIsNone(planned_seconds({"duration": "手动停止"}))

    def test_custom_clock(self):
        self.assertEqual(planned_seconds({
            "duration": "自定义", "custom_hours": "0", "custom_minutes": "15", "custom_seconds": "30",
        }), 930)
        self.assertEqual(planned_seconds({
            "duration": "自定义", "custom_hours": 2, "custom_minutes": 0, "custom_seconds": 0,
        }), 7200)

    def test_custom_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            planned_seconds({"duration": "自定义", "custom_minutes": "0", "custom_seconds": "9"})
        with self.assertRaises(ValueError):
            planned_seconds({"duration": "自定义", "custom_hours": "2", "custom_seconds": "1"})

    def test_estimate_uses_advisory_budget_for_manual(self):
        self.assertEqual(estimate_seconds({"duration": "手动停止"}), 600)
        self.assertEqual(estimate_seconds({"duration": "自定义", "custom_minutes": "3"}), 180)
