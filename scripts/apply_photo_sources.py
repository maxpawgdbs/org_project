"""Attach downloaded Commons photos and attribution from the photo manifest."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT / "content" / "route.json"
MANIFEST_FILE = ROOT / "content" / "photo_sources.json"


def main():
    route = json.loads(ROUTE_FILE.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    if len(route["stops"]) != len(manifest):
        raise ValueError("Photo manifest must cover every stop")
    for stop, photo in zip(route["stops"], manifest):
        if stop["order"] != photo["stop"]:
            raise ValueError("Photo manifest order does not match route")
        stop["photo"] = photo["file"].removeprefix("content/")
        stop["photo_url"] = photo["thumbnail_url"]
        stop["photo_credit"] = f"Фото: {photo['artist']} / Wikimedia Commons, {photo['license']}. Уменьшенная копия."
        deduplicated = []
        known = set()
        for source in stop["sources"]:
            if source["title"] in {"Страница фотографии", "Лицензия фотографии"}:
                continue
            normalized = source["url"].rstrip("/")
            if normalized not in known:
                deduplicated.append(source)
                known.add(normalized)
        stop["sources"] = deduplicated
        for title, url in (("Страница фотографии", photo["commons_page"]),
                           ("Лицензия фотографии", photo["license_url"])):
            if url.rstrip("/") not in known:
                stop["sources"].append({"title": title, "url": url})
                known.add(url.rstrip("/"))
    ROUTE_FILE.write_text(json.dumps(route, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
