"""Generate the final Telegram deep-link QR after BotFather assigns a username."""

import os
import re
from pathlib import Path

from route_bot.config import load_local_env


def main():
    load_local_env()
    username = os.environ.get("BOT_USERNAME", "").lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        raise SystemExit("Set BOT_USERNAME to the public username from BotFather")
    try:
        import qrcode
    except ImportError:
        raise SystemExit("Install QR tools: python -m pip install -r requirements-tools.txt") from None
    url = f"https://t.me/{username}"
    output = Path("deliverables")
    output.mkdir(exist_ok=True)
    qrcode.make(url).save(output / "bot_qr.png")
    (output / "bot_link.txt").write_text(url + "\n", encoding="utf-8")
    print(f"Created {output / 'bot_qr.png'} and {output / 'bot_link.txt'}")


if __name__ == "__main__":
    main()
