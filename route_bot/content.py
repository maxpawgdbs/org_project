"""Load and validate author-provided route material."""

import json
import math
from pathlib import Path
from urllib.parse import urlparse


STOP_FIELDS = (
    "id", "order", "title", "address", "latitude", "longitude", "photo",
    "photo_credit", "description", "look_for", "task", "next_transition", "sources",
)
ROUTE_FIELDS = (
    "title", "introduction", "audience", "duration", "transport", "start_point",
    "end_point", "map_url", "final_text", "authors", "quiz", "stops",
)


def _url(value):
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _local_file(base, relative, label):
    if not isinstance(relative, str):
        raise ValueError(f"{label} must be a path string")
    if not relative:
        return None
    file_path = (base / relative).resolve()
    if not file_path.is_relative_to(base):
        raise ValueError(f"{label} escapes content folder")
    return file_path


def load_route(filename, allow_placeholders=False):
    path = Path(filename).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = set(ROUTE_FIELDS) - data.keys()
    if missing:
        raise ValueError(f"Missing route fields: {', '.join(sorted(missing))}")
    if data.get("is_placeholder") and not allow_placeholders:
        raise ValueError("Placeholder content requires ALLOW_PLACEHOLDERS=1")
    if not data.get("is_placeholder") and "[ТЕХНИЧЕСКАЯ ЗАГЛУШКА]" in json.dumps(data, ensure_ascii=False):
        raise ValueError("Replace all technical placeholders before production launch")
    if not isinstance(data["stops"], list) or len(data["stops"]) < 10:
        raise ValueError("At least 10 stops are required")
    if not isinstance(data["quiz"], list) or len(data["quiz"]) != 5:
        raise ValueError("Exactly 5 quiz questions are required")
    for key in ("title", "introduction", "audience", "duration", "start_point", "end_point", "final_text"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise ValueError(f"Route field {key} must be nonempty text")
    if not isinstance(data["transport"], list) or not data["transport"] or not all(isinstance(x, str) and x.strip() for x in data["transport"]):
        raise ValueError("transport must be a nonempty list of strings")
    if not isinstance(data["authors"], list) or not data["authors"] or not all(isinstance(x, str) and x.strip() for x in data["authors"]):
        raise ValueError("authors must be a nonempty list of strings")
    if not isinstance(data["map_url"], str) or (data["map_url"] and not _url(data["map_url"])):
        raise ValueError("map_url must be an HTTPS/HTTP URL or empty for a placeholder")
    if not data.get("is_placeholder") and not data["map_url"]:
        raise ValueError("map_url is required for production content")
    data["_map_image_path"] = _local_file(path.parent, data.get("map_image", ""), "map_image")
    if not isinstance(data.get("map_note", ""), str):
        raise ValueError("map_note must be text")

    ids = set()
    orders = set()
    for stop in data["stops"]:
        missing = set(STOP_FIELDS) - stop.keys()
        if missing:
            raise ValueError(f"Missing stop fields: {', '.join(sorted(missing))}")
        if not isinstance(stop["id"], str) or not stop["id"] or stop["id"] in ids:
            raise ValueError("Stop IDs must be unique nonempty strings")
        ids.add(stop["id"])
        if type(stop["order"]) is not int or stop["order"] in orders:
            raise ValueError("Stop order must be a unique integer")
        orders.add(stop["order"])
        for key in ("title", "address", "description", "look_for"):
            if not isinstance(stop[key], str) or not stop[key].strip():
                raise ValueError(f"Stop {stop['id']}: {key} must be nonempty text")
        for key in ("photo", "photo_credit", "task", "next_transition"):
            if not isinstance(stop[key], str):
                raise ValueError(f"Stop {stop['id']}: {key} must be text")
        lat, lon = stop["latitude"], stop["longitude"]
        if (lat is None or lon is None) and not data.get("is_placeholder"):
            raise ValueError(f"Stop {stop['id']}: coordinates are required")
        if lat is not None and (type(lat) not in (int, float) or not math.isfinite(lat) or not -90 <= lat <= 90):
            raise ValueError(f"Stop {stop['id']}: invalid latitude")
        if lon is not None and (type(lon) not in (int, float) or not math.isfinite(lon) or not -180 <= lon <= 180):
            raise ValueError(f"Stop {stop['id']}: invalid longitude")
        if bool(lat is None) != bool(lon is None):
            raise ValueError(f"Stop {stop['id']}: both coordinates must be supplied")
        if not isinstance(stop["sources"], list):
            raise ValueError(f"Stop {stop['id']}: sources must be a list")
        for source in stop["sources"]:
            if not isinstance(source, dict) or not isinstance(source.get("title"), str) or not _url(source.get("url", "")):
                raise ValueError(f"Stop {stop['id']}: invalid source")
        stop["_photo_path"] = _local_file(path.parent, stop["photo"], f"Stop {stop['id']}: photo")
        for key in ("photo_url", "map_point_url"):
            value = stop.get(key, "")
            if not isinstance(value, str) or (value and not _url(value)):
                raise ValueError(f"Stop {stop['id']}: {key} must be a URL or empty")
        for key in ("visit_info", "task_answer", "task_explanation"):
            if not isinstance(stop.get(key, ""), str):
                raise ValueError(f"Stop {stop['id']}: {key} must be text")
        if not data.get("is_placeholder"):
            if not stop["photo"] and not stop.get("photo_url"):
                raise ValueError(f"Stop {stop['id']}: photo or photo_url is required")
            if not stop["sources"]:
                raise ValueError(f"Stop {stop['id']}: at least one source is required")
    data["stops"].sort(key=lambda stop: stop["order"])
    if orders != set(range(1, len(data["stops"]) + 1)):
        raise ValueError("Stop order must be consecutive from 1")

    for i, question in enumerate(data["quiz"], 1):
        if not isinstance(question, dict) or not isinstance(question.get("question"), str) or not question["question"].strip():
            raise ValueError(f"Quiz question {i} is missing")
        answers = question.get("options")
        if not isinstance(answers, list) or not 2 <= len(answers) <= 8 or not all(isinstance(x, str) and x.strip() for x in answers):
            raise ValueError(f"Quiz question {i} needs 2-8 answer options")
        if type(question.get("correct_index")) is not int or not 0 <= question["correct_index"] < len(answers):
            raise ValueError(f"Quiz question {i} has invalid correct_index")
        if not isinstance(question.get("explanation"), str) or not question["explanation"].strip():
            raise ValueError(f"Quiz question {i} needs an explanation")
    return data
