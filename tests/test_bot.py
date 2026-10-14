import copy
import tempfile
import unittest
from pathlib import Path

from route_bot.bot import RouteBot, chunks, point_url
from route_bot.content import load_route
from route_bot.storage import ProgressStore
from route_bot.telegram_api import BotAPIError


ROUTE_FILE = Path(__file__).resolve().parents[1] / "content" / "route.json"


class FakeAPI:
    def __init__(self):
        self.messages = []
        self.photos = []
        self.callbacks = []
        self.fail_photo = False

    def send_message(self, chat_id, text, keyboard=None):
        self.messages.append((chat_id, text, keyboard))

    def send_photo(self, chat_id, path, caption):
        if self.fail_photo:
            raise BotAPIError("unavailable")
        self.photos.append((chat_id, path, caption))

    def answer_callback(self, callback_id, text=""):
        self.callbacks.append(callback_id)


def callback(user_id, action):
    return {"callback_query": {"id": "sample", "from": {"id": user_id},
            "message": {"chat": {"id": user_id, "type": "private"}}, "data": action}}


class BotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "progress.sqlite3"
        self.store = ProgressStore(self.db)
        self.api = FakeAPI()
        self.route = load_route(ROUTE_FILE, True)
        self.bot = RouteBot(self.api, self.route, self.store)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_content_and_navigation(self):
        self.assertEqual(len(self.bot.stops), 10)
        self.bot.show_list(1)
        buttons = [button["callback_data"] for row in self.api.messages[-1][2]
                   for button in row if "callback_data" in button]
        self.assertIn("stop:0", buttons)
        self.assertIn("stop:9", buttons)
        self.bot.show_stop(1, 1, 0)
        first = [button["text"] for row in self.api.messages[-1][2] for button in row]
        self.assertIn("Далее", first)
        self.assertNotIn("Назад", first)
        self.bot.show_stop(1, 1, 9)
        last = [button["text"] for row in self.api.messages[-2][2] for button in row]
        self.assertIn("Назад", last)
        self.assertNotIn("Далее", last)
        self.assertIn("Финальная викторина", [button["text"] for row in self.api.messages[-1][2] for button in row])

    def test_two_users_and_restart(self):
        self.bot.show_stop(1, 101, 3)
        self.bot.show_stop(2, 202, 8)
        self.store.close()
        self.store = ProgressStore(self.db)
        self.bot = RouteBot(self.api, self.route, self.store)
        self.assertEqual(self.store.get(101)["last_stop_id"], "stop-04")
        self.assertEqual(self.store.get(202)["last_stop_id"], "stop-09")
        self.bot.continue_route(1, 101)
        self.assertIn("4. " + self.route["stops"][3]["title"], self.api.messages[-1][1])
        self.bot.start_route(1, 101)
        self.assertEqual(self.store.get(101)["last_stop_id"], "stop-01")
        self.assertEqual(self.store.get(202)["last_stop_id"], "stop-09")

    def test_long_text_and_photo_fallback(self):
        self.route["stops"][0]["description"] = "Слово " * 1500
        self.route["stops"][0]["_photo_path"] = Path(self.tmp.name) / "sample.jpg"
        self.route["stops"][0]["_photo_path"].write_bytes(b"fake")
        self.api.fail_photo = True
        self.bot.show_stop(1, 1, 0)
        combined = "".join(message[1] for message in self.api.messages)
        self.assertIn("Слово " * 1500, combined)
        self.assertIn("Фото временно недоступно", combined)
        self.assertTrue(all(len(message[1]) <= 3500 for message in self.api.messages))
        self.assertIsNotNone(self.api.messages[-1][2])
        self.assertEqual("".join(chunks("a" * 9000)), "a" * 9000)

    def test_quiz_duplicate_answer_and_result(self):
        self.bot.start_quiz(1, 101)
        run = self.store.get(101)["quiz_run"]
        for index, question in enumerate(self.route["quiz"]):
            choice = question["correct_index"]
            self.bot.handle_update(callback(101, f"answer:{run}:{index}:{choice}"))
            self.bot.handle_update(callback(101, f"answer:{run}:{index}:{choice}"))
            self.assertEqual(self.store.get(101)["quiz_score"], index + 1)
        self.assertEqual(self.store.get(101)["quiz_index"], 5)
        self.assertFalse(self.store.get(101)["quiz_active"])
        self.assertTrue(any("Результат: 5 из 5" in msg[1] for msg in self.api.messages))
        self.bot.repeat_quiz(1, 101)
        self.bot.handle_update(callback(101, f"answer:{run}:0:0"))
        self.assertEqual(self.store.get(101)["quiz_score"], 0)

    def test_unknown_message_and_map_url(self):
        self.bot.handle_update({"message": {"chat": {"id": 1, "type": "private"},
                                "from": {"id": 1}, "text": "непонятно"}})
        self.assertIn("главном меню", self.api.messages[-2][1])
        stop = copy.copy(self.route["stops"][0])
        self.assertEqual(point_url(stop), stop["map_point_url"])
        stop["map_point_url"] = ""
        stop["latitude"], stop["longitude"] = 55.75, 37.61
        self.assertEqual(point_url(stop), "https://www.google.com/maps/search/?api=1&query=55.75%2C37.61")

    def test_imported_materials_and_map_image(self):
        self.assertEqual(self.route["title"], "Москва в движении: от конки до метро")
        self.assertEqual([s["content_status"] for s in self.route["stops"]].count("complete"), 10)
        self.assertFalse(self.route["is_placeholder"])
        self.assertTrue(all(s["_photo_path"].is_file() for s in self.route["stops"]))
        self.assertTrue(all(s["task"] and s["task_answer"] for s in self.route["stops"]))
        self.assertTrue(all("[ТЕХНИЧЕСКАЯ ЗАГЛУШКА]" not in s["description"] + s["look_for"] for s in self.route["stops"]))
        self.assertTrue(all("[ТЕХНИЧЕСКАЯ ЗАГЛУШКА]" not in q["question"] + q["explanation"] for q in self.route["quiz"]))
        self.bot.show_stop(1, 1, 0)
        self.assertTrue(self.api.photos)
        self.assertEqual(self.api.photos[-1][1], self.route["stops"][0]["_photo_path"])
        heading = "1. " + self.route["stops"][0]["title"]
        self.assertEqual(self.api.photos[-1][2], heading)
        self.assertTrue(self.api.messages[0][1].startswith(heading + "\n"))
        self.bot.show_map(1)
        self.assertEqual(self.api.photos[-1][1], self.route["_map_image_path"])
        self.assertTrue(self.route["_map_image_path"].is_file())
        map_buttons = [item for row in self.api.messages[-1][2] for item in row]
        self.assertIn({"text": "Открыть карту", "url": self.route["map_url"]}, map_buttons)
        self.bot.show_task_answer(1, 0)
        self.assertIn("Чтобы помочь", self.api.messages[-1][1])

    def test_start_sends_map_then_welcome(self):
        update = {"message": {"chat": {"id": 1, "type": "private"},
                              "from": {"id": 1}, "text": "/start"}}
        self.bot.handle_update(update)
        self.assertEqual(self.api.photos[-1][1], self.route["_map_image_path"])
        self.assertIn("10 остановок", self.api.photos[-1][2])
        self.assertTrue(self.api.messages[-1][1].startswith(self.route["title"]))
        self.assertNotIn("Техническая версия", self.api.messages[-1][1])
        self.assertIn("Карта маршрута", [item["text"] for row in self.api.messages[-1][2] for item in row])
        self.api.fail_photo = True
        self.bot.handle_update(update)
        self.assertEqual(len(self.api.photos), 1)
        self.assertTrue(self.api.messages[-1][1].startswith(self.route["title"]))

    def test_all_stops_send_matching_photo_and_text_headings(self):
        for index, stop in enumerate(self.route["stops"]):
            before_messages = len(self.api.messages)
            before_photos = len(self.api.photos)
            self.bot.show_stop(1, 1, index)
            heading = f"{index + 1}. {stop['title']}"
            self.assertEqual(len(self.api.photos), before_photos + 1)
            self.assertEqual(self.api.photos[-1][1], stop["_photo_path"])
            self.assertEqual(self.api.photos[-1][2], heading)
            text_parts = [item[1] for item in self.api.messages[before_messages:]]
            self.assertTrue(text_parts[0].startswith(heading + "\n"))
            self.assertIn(stop["description"], "".join(text_parts))
            self.assertIn(stop["look_for"], "".join(text_parts))
            self.assertIn(stop["photo_credit"], "".join(text_parts))

    def test_offset_persists(self):
        self.store.set_offset(123)
        self.store.close()
        self.store = ProgressStore(self.db)
        self.assertEqual(self.store.get_offset(), 123)


if __name__ == "__main__":
    unittest.main()
