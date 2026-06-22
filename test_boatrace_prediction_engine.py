import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import boatrace_prediction_engine as engine


class PredictionEngineTests(unittest.TestCase):
    def test_racer_rows_ignore_start_counts(self):
        text = """1着率
今期 85.2%\n(27) 20.0%\n(20) 6.7%\n(15) 41.7%\n(12) 25.0%\n(24) 0.0%\n(11)
直近\n6ヶ月 78.1%\n(32) 26.3%\n(19) 14.3%\n(21) 21.1%\n(19) 25.0%\n(24) 0.0%\n(7)
2連対率
今期 92.5%\n(27) 45.0%\n(20) 33.3%\n(15) 66.6%\n(12) 37.5%\n(24) 0.0%\n(11)
直近\n6ヶ月 81.3%\n(32) 52.6%\n(19) 52.4%\n(21) 52.6%\n(19) 45.8%\n(24) 0.0%\n(7)
3連対率
今期 100.0%\n(27) 70.0%\n(20) 53.3%\n(15) 83.3%\n(12) 75.0%\n(24) 9.1%\n(11)
直近\n6ヶ月 90.6%\n(32) 84.2%\n(19) 66.7%\n(21) 68.4%\n(19) 58.3%\n(24) 0.0%\n(7)"""
        parsed = engine.parse_racer(text)
        self.assertEqual(parsed["win1"]["今期"], [85.2, 20.0, 6.7, 41.7, 25.0, 0.0])
        self.assertEqual(parsed["ren3"]["直近6ヶ月"], [90.6, 84.2, 66.7, 68.4, 58.3, 0.0])

    def test_kimari_nige_simulation_has_second_third_and_deme(self):
        text = """逃げシミュレーション
1着 逃げ 逃がし2着率
81.0% 75.9% 41.2% 42.9% 46.2% 22.7% 0.0%
逃がし3着率
35.3% 14.3% 23.1% 40.9% 20.0%
逃げ逃し出目確率
1-2 1-3 1-4 1-5 1-6
20.4% 21.3% 22.9% 11.3% 0.0%"""
        sim = engine.parse_kimari(text)["nige_sim"]
        self.assertEqual(sim["win1"], 81.0)
        self.assertEqual(sim["second"], [41.2, 42.9, 46.2, 22.7, 0.0])
        self.assertEqual(sim["third"], [35.3, 14.3, 23.1, 40.9, 20.0])
        self.assertEqual(sim["deme"], [20.4, 21.3, 22.9, 11.3, 0.0])

    def test_boatcast_tenji_fallback(self):
        # 周回、回り足、直線、展示の順で1艇ずつ並ぶ形式。
        text = """0.0 36.84 6.17 7.40 6.91\n0.0 37.23 6.67 7.40 6.95\n0.0 37.47 6.30 7.30 6.90\n0.0 37.47 6.13 7.53 7.00\n0.5 37.70 6.47 7.31 6.90\n0.0 37.30 6.27 7.37 6.92"""
        parsed = engine.parse_tenji(text)
        self.assertEqual(parsed["解析形式"], "BOATCAST")
        self.assertEqual(parsed["boats"][0]["tenji"], 6.91)
        self.assertEqual(parsed["boats"][4]["mawari"], 6.47)

    def test_incomplete_racer_is_warning_not_failure(self):
        payload = engine.build_payload(
            "大村", "向かい風1m",
            {"tenji": "進入 1 2 3 4 5 6\n展示 6.94 6.94 6.84 6.91 6.90 6.95\n周回 37.17 37.23 36.83 37.13 36.77 37.37\n周り足 6.40 6.37 6.10 6.40 6.03 6.40", "racer": "1着率 今期 85.2%"},
        )
        self.assertTrue(payload["解析警告"])
        self.assertEqual(len(engine.evaluate(payload)["順位"]), 6)


if __name__ == "__main__":
    unittest.main()
