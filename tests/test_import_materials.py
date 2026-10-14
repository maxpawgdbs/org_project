import json
import unittest
from pathlib import Path

from scripts.import_materials import build_route


ROOT = Path(__file__).resolve().parents[1]


class ImportTests(unittest.TestCase):
    def test_workbook_has_one_complete_card_and_ten_planned_stops(self):
        previous = json.loads((ROOT / "content" / "route.json").read_text(encoding="utf-8"))
        route = build_route(ROOT / "Moskva_v_dvizhenii_obrazec_01.xlsx", previous)
        self.assertEqual(len(route["stops"]), 10)
        self.assertEqual(sum(s["content_status"] == "complete" for s in route["stops"]), 1)
        self.assertIn("В 1872 году", route["stops"][0]["description"])
        self.assertIn("[ТЕХНИЧЕСКАЯ ЗАГЛУШКА]", route["stops"][1]["description"])
        self.assertTrue(all(s["latitude"] and s["longitude"] for s in route["stops"]))
        self.assertEqual(route["title"], "Москва в движении: от конки до метро")


if __name__ == "__main__":
    unittest.main()
