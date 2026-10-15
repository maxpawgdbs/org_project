"""Route interaction and long polling."""

import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import quote

from .content import load_route
from .config import load_local_env
from .storage import ProgressStore
from .telegram_api import BotAPIError, TelegramAPI


MAX_MESSAGE = 2000  # Safe even if emoji count as two UTF-16 units.
MAX_PHOTO_CAPTION = 1024  # Telegram Bot API limit, measured in UTF-16 units.
LOG = logging.getLogger("route_bot")


def chunks(text, limit=MAX_MESSAGE):
    """Split long text without losing any characters."""
    while len(text) > limit:
        boundary = text.rfind("\n", 0, limit + 1)
        if boundary < limit // 2:
            boundary = text.rfind(" ", 0, limit + 1)
        if boundary < limit // 2:
            boundary = limit
        yield text[:boundary]
        text = text[boundary:]
    if text:
        yield text


def photo_caption(heading, description):
    """Keep the complete description with its photo whenever Telegram permits."""
    caption = f"{heading}\n\n{description}"
    if len(caption.encode("utf-16-le")) // 2 <= MAX_PHOTO_CAPTION:
        return caption, ""
    # Future content may be longer: send the overflow as text, never truncate it.
    prefix = f"{heading}\n\n"
    available = MAX_PHOTO_CAPTION - len(prefix.encode("utf-16-le")) // 2
    units = 0
    boundary = 0
    for char in description:
        size = len(char.encode("utf-16-le")) // 2
        if units + size > available:
            break
        units += size
        boundary += 1
    split = description.rfind("\n\n", 0, boundary + 1)
    if split < boundary // 2:
        split = description.rfind(" ", 0, boundary + 1)
    if split < boundary // 2:
        split = boundary
    return prefix + description[:split], description[split:]


def button(label, action=None, url=None):
    result = {"text": label}
    if url:
        result["url"] = url
    else:
        result["callback_data"] = action
    return result


def point_url(stop):
    if stop.get("map_point_url"):
        return stop["map_point_url"]
    if stop["latitude"] is None:
        return None
    coords = f"{stop['latitude']},{stop['longitude']}"
    return "https://www.google.com/maps/search/?api=1&query=" + quote(coords, safe="")


class RouteBot:
    def __init__(self, api, route, store):
        self.api = api
        self.route = route
        self.store = store
        self.stops = route["stops"]
        self.stop_ids = {stop["id"]: i for i, stop in enumerate(self.stops)}

    def send(self, chat_id, message, keyboard=None):
        parts = list(chunks(message)) or [" "]
        for i, part in enumerate(parts):
            self.api.send_message(chat_id, part, keyboard if i == len(parts) - 1 else None)

    def main_menu(self, chat_id, user_id):
        progress = self.store.get(user_id)
        rows = [[button("Начать маршрут", "start")]]
        if progress:
            rows.append([button("Продолжить маршрут", "continue")])
        rows.extend([
            [button("Все остановки", "list:0")],
            [button("Карта маршрута", "map")],
            [button("О проекте и источники", "about")],
        ])
        if progress:
            rows.append([button("Начать маршрут заново", "start")])
        self.send(chat_id, f"{self.route['title']}\n\n{self.route['introduction']}", rows)

    def show_start_map(self, chat_id):
        """Show the ten-stop overview before the /start welcome and menu."""
        map_image = self.route.get("_map_image_path")
        if map_image and map_image.is_file():
            try:
                self.api.send_photo(chat_id, map_image, f"Карта маршрута: {len(self.stops)} остановок")
            except (BotAPIError, OSError) as exc:
                LOG.warning("Route map image unavailable: %s", type(exc).__name__)

    def start_route(self, chat_id, user_id):
        self.store.start(user_id, self.stops[0]["id"])
        r = self.route
        intro = (f"{r['title']}\n\nОстановок: {len(self.stops)}\n"
                 f"Продолжительность: {r['duration']}\n"
                 f"Как передвигаться: {', '.join(r['transport'])}\n"
                 f"Начало: {r['start_point']}\nКонец: {r['end_point']}")
        self.send(chat_id, intro, [[button("Открыть первую остановку", "stop:0")], [button("Главное меню", "menu")]])

    def continue_route(self, chat_id, user_id):
        progress = self.store.get(user_id)
        if not progress:
            self.start_route(chat_id, user_id)
            return
        self.show_stop(chat_id, user_id, self.stop_ids.get(progress["last_stop_id"], 0))

    def show_list(self, chat_id, page=0):
        per_page = 15
        page = max(0, min(page, (len(self.stops) - 1) // per_page))
        start = page * per_page
        rows = [[button(f"{i + 1}. {stop['title'][:48]}", f"stop:{i}")]
                for i, stop in enumerate(self.stops[start:start + per_page], start)]
        paging = []
        if page:
            paging.append(button("← Предыдущие", f"list:{page - 1}"))
        if start + per_page < len(self.stops):
            paging.append(button("Следующие →", f"list:{page + 1}"))
        if paging:
            rows.append(paging)
        rows.append([button("Главное меню", "menu")])
        self.send(chat_id, f"Все остановки ({len(self.stops)}):", rows)

    def show_stop(self, chat_id, user_id, index):
        if not 0 <= index < len(self.stops):
            self.main_menu(chat_id, user_id)
            return
        stop = self.stops[index]
        self.store.visit(user_id, stop["id"])
        photo_path = stop["_photo_path"]
        photo_ok = False
        heading = f"{index + 1}. {stop['title']}"
        caption, remaining_description = photo_caption(heading, stop["description"])
        if photo_path and photo_path.is_file():
            try:
                self.api.send_photo(chat_id, photo_path, caption)
                photo_ok = True
            except (BotAPIError, OSError) as exc:
                LOG.warning("Photo unavailable: %s", type(exc).__name__)
        if not photo_ok and stop.get("photo_url"):
            try:
                self.api.send_photo(chat_id, stop["photo_url"], caption)
                photo_ok = True
            except BotAPIError as exc:
                LOG.warning("Remote photo unavailable: %s", type(exc).__name__)
        lines = []
        if photo_ok:
            if remaining_description:
                lines.extend([remaining_description.strip(), ""])
        else:
            lines.extend([heading, "", stop["description"], ""])
        lines.extend(["На что обратить внимание:", stop["look_for"]])
        if stop["task"]:
            lines.extend(["", "Вопрос или задание:", stop["task"]])
        lines.extend(["", "Адрес:", stop["address"]])
        if stop.get("visit_info"):
            lines.extend(["", "Место осмотра и доступ:", stop["visit_info"]])
        if stop["photo_credit"]:
            lines.extend(["", stop["photo_credit"]])
        if not photo_ok:
            lines.extend(["", "Фото временно недоступно."])
        if index + 1 < len(self.stops) and stop["next_transition"]:
            lines.extend(["", "Переход к следующей остановке:", stop["next_transition"]])
        rows = []
        location = point_url(stop)
        if location:
            rows.append([button("Открыть точку на карте", url=location)])
        rows.append([button("Источники", f"sources:{index}")])
        if stop.get("task_answer"):
            rows.append([button("Ответ на задание", f"task_answer:{index}")])
        navigation = []
        if index > 0:
            navigation.append(button("Назад", f"stop:{index - 1}"))
        if index + 1 < len(self.stops):
            navigation.append(button("Далее", f"stop:{index + 1}"))
        if navigation:
            rows.append(navigation)
        rows.extend([[button("Все остановки", "list:0")], [button("Главное меню", "menu")]])
        self.send(chat_id, "\n".join(lines), rows)
        if index == len(self.stops) - 1:
            self.show_finish(chat_id)

    def show_sources(self, chat_id, index):
        if not 0 <= index < len(self.stops):
            return
        stop = self.stops[index]
        lines = [f"Источники: {index + 1}. {stop['title']}"]
        if stop["sources"]:
            for item in stop["sources"]:
                lines.append(f"\n{item['title']}\n{item['url']}")
        else:
            lines.append("\nИсточники пока не переданы автором.")
        if stop["photo_credit"]:
            lines.append("\n" + stop["photo_credit"])
        self.send(chat_id, "".join(lines), [[button("К остановке", f"stop:{index}")], [button("Главное меню", "menu")]])

    def show_map(self, chat_id):
        map_image = self.route.get("_map_image_path")
        if map_image and map_image.is_file():
            try:
                self.api.send_photo(chat_id, map_image, f"Карта маршрута: {len(self.stops)} остановок")
            except (BotAPIError, OSError) as exc:
                LOG.warning("Route map image unavailable: %s", type(exc).__name__)
        note = self.route.get("map_note") or "Общая карта маршрута."
        if self.route["map_url"]:
            self.send(chat_id, note, [[button("Открыть карту", url=self.route["map_url"])], [button("Главное меню", "menu")]])
        else:
            self.send(chat_id, note + "\n\nСсылка на общую интерактивную карту пока не передана. Карты отдельных точек доступны в карточках остановок.", [[button("Главное меню", "menu")]])

    def show_task_answer(self, chat_id, index):
        if not 0 <= index < len(self.stops):
            return
        stop = self.stops[index]
        if not stop.get("task_answer"):
            return
        message = "Ответ: " + stop["task_answer"]
        if stop.get("task_explanation"):
            message += "\n\n" + stop["task_explanation"]
        self.send(chat_id, message, [[button("К остановке", f"stop:{index}")], [button("Главное меню", "menu")]])

    def show_about(self, chat_id):
        lines = ["О проекте", "", self.route["title"], "",
                 "Аудитория: " + self.route["audience"],
                 "Авторы: " + ", ".join(self.route["authors"]), "", "Источники по остановкам:"]
        for i, stop in enumerate(self.stops, 1):
            lines.append(f"\n{i}. {stop['title']}")
            for source in stop["sources"]:
                lines.append(f"{source['title']}: {source['url']}")
        self.send(chat_id, "\n".join(lines), [[button("Главное меню", "menu")]])

    def show_finish(self, chat_id):
        self.send(chat_id, self.route["final_text"], [[button("Финальная викторина", "quiz")], [button("Главное меню", "menu")]])

    def start_quiz(self, chat_id, user_id):
        progress = self.store.get(user_id)
        if not progress or not progress["quiz_active"]:
            self.store.start_quiz(user_id, self.stops[-1]["id"])
        self.show_question(chat_id, user_id)

    def repeat_quiz(self, chat_id, user_id):
        self.store.start_quiz(user_id, self.stops[-1]["id"])
        self.show_question(chat_id, user_id)

    def show_question(self, chat_id, user_id):
        progress = self.store.get(user_id)
        if not progress or not progress["quiz_active"]:
            self.show_finish(chat_id)
            return
        index = progress["quiz_index"]
        question = self.route["quiz"][index]
        rows = [[button(option if len(option) <= 60 else f"Ответ {i + 1}",
                        f"answer:{progress['quiz_run']}:{index}:{i}")]
                for i, option in enumerate(question["options"])]
        rows.append([button("Главное меню", "menu")])
        options = "\n".join(f"{i + 1}. {option}" for i, option in enumerate(question["options"]))
        self.send(chat_id, f"Вопрос {index + 1} из 5\n\n{question['question']}\n\n{options}", rows)

    def answer(self, chat_id, user_id, quiz_run, index, choice):
        if not 0 <= index < 5 or not 0 <= choice < len(self.route["quiz"][index]["options"]):
            self.main_menu(chat_id, user_id)
            return
        question = self.route["quiz"][index]
        result = self.store.answer(user_id, quiz_run, index, choice == question["correct_index"], 5)
        if result is None:
            self.send(chat_id, "Этот вопрос уже пройден. Продолжите викторину из меню.", [[button("Главное меню", "menu")]])
            return
        feedback = ("Верно!" if choice == question["correct_index"] else "Неверно.")
        feedback += f"\nПравильный ответ: {question['options'][question['correct_index']]}\n{question['explanation']}"
        if result["quiz_active"]:
            rows = [[button("Следующий вопрос", "quiz_next")], [button("Главное меню", "menu")]]
        else:
            feedback += f"\n\nРезультат: {result['quiz_score']} из 5."
            rows = [[button("Повторить викторину", "quiz_repeat")], [button("Главное меню", "menu")]]
        self.send(chat_id, feedback, rows)

    def handle_update(self, update):
        if "callback_query" in update:
            query = update["callback_query"]
            try:
                self.api.answer_callback(query["id"])
            except BotAPIError:
                LOG.warning("Callback acknowledgement failed")
            message = query.get("message") or {}
            if message.get("chat", {}).get("type") != "private":
                return
            chat_id = message["chat"]["id"]
            user_id = query["from"]["id"]
            action = query.get("data", "")
        elif "message" in update:
            message = update["message"]
            if message.get("chat", {}).get("type") != "private":
                return
            chat_id = message["chat"]["id"]
            user_id = message["from"]["id"]
            if message.get("text", "").split(maxsplit=1)[0:1] == ["/start"]:
                self.show_start_map(chat_id)
                self.main_menu(chat_id, user_id)
            else:
                self.send(chat_id, "Выберите действие в главном меню.")
                self.main_menu(chat_id, user_id)
            return
        else:
            return

        if action == "menu":
            self.main_menu(chat_id, user_id)
        elif action == "start":
            self.start_route(chat_id, user_id)
        elif action == "continue":
            self.continue_route(chat_id, user_id)
        elif action == "map":
            self.show_map(chat_id)
        elif action == "about":
            self.show_about(chat_id)
        elif action == "finish":
            self.show_finish(chat_id)
        elif action == "quiz":
            self.start_quiz(chat_id, user_id)
        elif action == "quiz_repeat":
            self.repeat_quiz(chat_id, user_id)
        elif action == "quiz_next":
            self.show_question(chat_id, user_id)
        elif action.startswith("list:"):
            self.show_list(chat_id, _number(action.split(":", 1)[1]))
        elif action.startswith("stop:"):
            self.show_stop(chat_id, user_id, _number(action.split(":", 1)[1]))
        elif action.startswith("sources:"):
            self.show_sources(chat_id, _number(action.split(":", 1)[1]))
        elif action.startswith("task_answer:"):
            self.show_task_answer(chat_id, _number(action.split(":", 1)[1]))
        elif action.startswith("answer:"):
            parts = action.split(":")
            if len(parts) == 4:
                self.answer(chat_id, user_id, _number(parts[1]), _number(parts[2]), _number(parts[3]))
        else:
            self.main_menu(chat_id, user_id)


def _number(value):
    try:
        return int(value)
    except ValueError:
        return -1


def configure_logging(filename):
    Path(filename).parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(filename, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)


def main():
    load_local_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in the environment")
    base = Path(__file__).resolve().parent.parent
    route_file = os.environ.get("ROUTE_FILE", str(base / "content" / "route.json"))
    db_file = os.environ.get("DATABASE_FILE", str(base / "data" / "progress.sqlite3"))
    log_file = os.environ.get("LOG_FILE", str(base / "data" / "bot.log"))
    configure_logging(log_file)
    route = load_route(route_file, os.environ.get("ALLOW_PLACEHOLDERS") == "1")
    store = ProgressStore(db_file)
    bot = RouteBot(TelegramAPI(token), route, store)
    LOG.info("Bot started")
    try:
        while True:
            try:
                for update in bot.api.get_updates(store.get_offset()):
                    try:
                        bot.handle_update(update)
                    except Exception as exc:
                        # Avoid exception strings and tracebacks: Bot API URLs contain the token.
                        LOG.error("Update handling failed: %s", type(exc).__name__)
                    store.set_offset(update["update_id"] + 1)
            except BotAPIError as exc:
                LOG.error("Polling failed: %s", type(exc).__name__)
                time.sleep(3)
    except KeyboardInterrupt:
        LOG.info("Bot stopped")
    finally:
        store.close()


if __name__ == "__main__":
    main()
