import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from route_bot.telegram_api import BotAPIError, TelegramAPI


class TelegramAPITests(unittest.TestCase):
    def test_json_and_multipart_requests(self):
        requests = []

        def fake_urlopen(request, timeout):
            requests.append(request)
            return io.BytesIO(b'{"ok":true,"result":{"message_id":1}}')

        api = TelegramAPI("secret-test-token")
        with patch("route_bot.telegram_api.urlopen", fake_urlopen):
            api.send_message(1, "Привет")
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "photo.jpg"
                path.write_bytes(b"picture-bytes")
                api.send_photo(1, path, "Остановка", [[{"text": "Далее", "callback_data": "stop:1"}]])
        self.assertIn("Привет".encode("utf-8"), requests[0].data)
        self.assertIn(b"picture-bytes", requests[1].data)
        self.assertIn(b'name="photo"', requests[1].data)
        self.assertIn(b'name="reply_markup"', requests[1].data)
        self.assertIn("Далее".encode("utf-8"), requests[1].data)
        self.assertIn(b'"inline_keyboard"', requests[1].data)
        self.assertIn("multipart/form-data", requests[1].get_header("Content-type"))

    def test_photo_url_is_sent_as_json(self):
        requests = []

        def fake_urlopen(request, timeout):
            requests.append(request)
            return io.BytesIO(b'{"ok":true,"result":{"message_id":1}}')

        with patch("route_bot.telegram_api.urlopen", fake_urlopen):
            TelegramAPI("secret-test-token").send_photo(
                1, "https://example.org/photo.jpg", "Photo",
                [[{"text": "Map", "url": "https://example.org/map"}]])
        self.assertIn(b"https://example.org/photo.jpg", requests[0].data)
        self.assertIn(b'"inline_keyboard"', requests[0].data)
        self.assertIn("application/json", requests[0].get_header("Content-type"))

    def test_http_error_does_not_expose_token(self):
        def fail(request, timeout):
            raise HTTPError(request.full_url, 401, "Unauthorized", {}, None)

        api = TelegramAPI("secret-test-token")
        with patch("route_bot.telegram_api.urlopen", fail):
            with self.assertRaises(BotAPIError) as caught:
                api.send_message(1, "Hi")
        self.assertNotIn("secret-test-token", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
