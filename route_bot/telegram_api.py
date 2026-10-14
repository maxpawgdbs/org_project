"""Small Bot API client with no third-party runtime dependencies."""

import json
import mimetypes
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class BotAPIError(Exception):
    pass


class TelegramAPI:
    def __init__(self, token):
        self._base = f"https://api.telegram.org/bot{token}/"

    def call(self, method, payload=None, photo=None):
        url = self._base + method
        if photo is None:
            body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
            content_type = "application/json"
        else:
            boundary = "----RouteBot" + uuid.uuid4().hex
            chunks = []
            for key, value in (payload or {}).items():
                chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode("utf-8"))
            path = Path(photo)
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"photo{path.suffix.lower()}\"\r\nContent-Type: {mime}\r\n\r\n".encode("utf-8"))
            chunks.append(path.read_bytes())
            chunks.append(f"\r\n--{boundary}--\r\n".encode("ascii"))
            body = b"".join(chunks)
            content_type = f"multipart/form-data; boundary={boundary}"
        request = Request(url, body, {"Content-Type": content_type}, method="POST")
        try:
            with urlopen(request, timeout=50 if method == "getUpdates" else 25) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise BotAPIError(f"Telegram API HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError) as exc:
            raise BotAPIError(f"Telegram API transport error: {type(exc).__name__}") from None
        if not result.get("ok"):
            # Do not log Telegram's response text: it may contain user input.
            raise BotAPIError(f"Telegram API method {method} failed")
        return result["result"]

    def send_message(self, chat_id, text, keyboard=None):
        payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if keyboard:
            payload["reply_markup"] = {"inline_keyboard": keyboard}
        return self.call("sendMessage", payload)

    def send_photo(self, chat_id, path, caption):
        if isinstance(path, str) and path.startswith(("https://", "http://")):
            return self.call("sendPhoto", {"chat_id": chat_id, "caption": caption, "photo": path})
        return self.call("sendPhoto", {"chat_id": chat_id, "caption": caption}, photo=path)

    def answer_callback(self, callback_id, text=""):
        return self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    def get_updates(self, offset):
        # Keep long polling below common proxy timeouts (a 35-second wait failed here).
        payload = {"timeout": 20, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        return self.call("getUpdates", payload)
