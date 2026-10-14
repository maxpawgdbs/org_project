import json
import unittest
from pathlib import Path

from scripts.import_materials import build_route


ROOT = Path(__file__).resolve().parents[1]


class ImportTests(unittest.TestCase):
    def test_reimport_preserves_completed_cards(self):
        previous = json.loads((ROOT / "content" / "route.json").read_text(encoding="utf-8"))
        route = build_route(ROOT / "Moskva_v_dvizhenii_obrazec_01.xlsx", previous)
        self.assertEqual(len(route["stops"]), 10)
        self.assertEqual(sum(s["content_status"] == "complete" for s in route["stops"]), 10)
        self.assertIn("В 1872 году", route["stops"][0]["description"])
        self.assertEqual(route["stops"][1]["description"], previous["stops"][1]["description"])
        self.assertEqual(route["stops"][1]["photo"], previous["stops"][1]["photo"])
        self.assertTrue(all(s["latitude"] and s["longitude"] for s in route["stops"]))
        self.assertEqual(route["title"], "Москва в движении: от конки до метро")
        self.assertEqual(route["map_url"], previous["map_url"])
        self.assertEqual(route["quiz"], previous["quiz"])
        self.assertIn("Это приблизительная оценка", route["duration"])
        self.assertFalse(route["is_placeholder"])


if __name__ == "__main__":
    unittest.main()
