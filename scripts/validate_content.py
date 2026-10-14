"""Validate content without starting Telegram polling."""

import argparse
from route_bot.content import load_route


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file", nargs="?", default="content/route.json")
    parser.add_argument("--allow-placeholders", action="store_true")
    args = parser.parse_args()
    route = load_route(args.file, args.allow_placeholders)
    print(f"OK: {len(route['stops'])} stops, {len(route['quiz'])} quiz questions")
    missing = [stop["id"] for stop in route["stops"]
               if stop["_photo_path"] and not stop["_photo_path"].is_file()]
    if missing:
        print("Local photo files currently missing: " + ", ".join(missing))
        no_fallback = [stop["id"] for stop in route["stops"]
                       if stop["id"] in missing and not stop.get("photo_url")]
        if no_fallback and not route.get("is_placeholder"):
            raise SystemExit(1)
    map_image = route.get("_map_image_path")
    if map_image and not map_image.is_file():
        print("Map image currently missing: " + str(map_image))
        if not route.get("is_placeholder"):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
