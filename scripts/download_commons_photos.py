"""Download licensed Wikimedia Commons thumbnails for the ten route stops."""

import html
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path


FILES = [
    "Белорусский вокзал. декабрь 2024.jpg",
    "Moscow MiusskoeTramDepot 1687.jpg",
    "Moscow, Obraztsova 11 garage from Novosuchevsky Aug 2008 02.JPG",
    "Moscow, Triumfalnaya Square immediately after the 2016 reconstruction (31391621615).jpg",
    "Tverskaya13 Moscow 06-2015.jpg",
    "7244. Bolshoy Kamenny Bridge across the Moskva River.jpg",
    "Moscow GES-2 014 7211.jpg",
    "Metro MSK Line1 Kropotkinskaya.jpg",
    "Biblioteka imeni Lenina subway 1.jpg",
    "MosMetro Okhotny Ryad img1 asv2018-01.jpg",
]
ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "MoscowRouteBot/1.0 (educational route; https://github.com/maxpawgdbs/org_project)"


def get_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def plain(value):
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def main():
    photos = ROOT / "content" / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index, filename in enumerate(FILES, 1):
        title = "File:" + filename
        params = urllib.parse.urlencode({
            "action": "query", "format": "json", "titles": title,
            "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 1280,
        })
        data = get_json("https://commons.wikimedia.org/w/api.php?" + params)
        page = next(iter(data["query"]["pages"].values()))
        if "missing" in page or not page.get("imageinfo"):
            raise ValueError(f"Commons file missing: {title}")
        info = page["imageinfo"][0]
        metadata = info["extmetadata"]
        license_name = plain(metadata["LicenseShortName"]["value"])
        artist = plain(metadata.get("Artist", {}).get("value", ""))
        if index == 1:
            # Commons includes a bilingual usage note in this Artist field.
            artist = "Kotofey2016 / Википедия"
        elif index == 8:
            # The file page requests this attribution form.
            artist = "Алексей Фёдоров"
        page_url = info["descriptionurl"]
        photo_url = info.get("thumburl", info["url"])
        request = urllib.request.Request(photo_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.headers.get_content_type() != "image/jpeg":
                raise ValueError(f"Unexpected image format: {title}")
            image = response.read()
        if not image.startswith(b"\xff\xd8") or not image.endswith(b"\xff\xd9"):
            raise ValueError(f"Invalid JPEG: {title}")
        target = photos / f"{index:02}.jpg"
        target.write_bytes(image)
        manifest.append({"stop": index, "file": str(target.relative_to(ROOT)).replace("\\", "/"),
                         "commons_page": page_url, "artist": artist, "license": license_name,
                         "license_url": plain(metadata.get("LicenseUrl", {}).get("value", "")),
                         "thumbnail_url": photo_url})
        print(f"{index:02}: {len(image)} bytes, {license_name}, {artist[:80]}")
    (ROOT / "content" / "photo_sources.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
