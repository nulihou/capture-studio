import unittest
from capture_studio.frame_rates import FrameRates


class FrameRateTests(unittest.TestCase):
    def test_measures_counts_not_requested_fps(self):
        clock = [0.0]
        rates = FrameRates(clock=lambda: clock[0])
        for index in range(1,61):
            clock[0] = index/10
            rates.tick()
            if index % 2 == 0:
                rates.tick(source=False)
        status = rates.status()
        self.assertEqual(status['source_fps'],10)
        self.assertEqual(status['preview_fps'],5)
        self.assertEqual(status['source_buffers_total'],60)
        clock[0] = 10
        self.assertEqual(rates.status()['source_fps'],0)

    def test_startup_has_no_misleading_rate(self):
        rates = FrameRates(clock=lambda: 0)
        rates.tick()
        self.assertIsNone(rates.status()['source_fps'])
