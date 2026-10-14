"""Convert the author's current workbook into the route JSON used by the bot.

The workbook explicitly contains one complete stop and nine planning rows. The
conversion keeps those nine rows visibly incomplete; it never invents missing
historical cards, photos, or quiz questions.
"""

import argparse
import json
import re
import shutil
from pathlib import Path

from .xlsx_reader import read_xlsx


URL = re.compile(r"https?://[^\s<>]+")
PLACEHOLDER = "[ТЕХНИЧЕСКАЯ ЗАГЛУШКА]"


def columns(row):
    return {re.match(r"[A-Z]+", key).group(): value for key, value in row.items()}


def source_list(text, default_title):
    sources = []
    for part in re.split(r"\n\s*\n", text or ""):
        previous = ""
        for line in part.splitlines():
            matches = list(URL.finditer(line))
            if not matches:
                previous = line.strip() or previous
                continue
            for number, match in enumerate(matches, 1):
                url = match.group().rstrip(".,;)")
                prefix = line[:match.start()].strip(" :—–")
                title = prefix or previous or default_title
                if len(matches) > 1 and not prefix:
                    title += f" {number}"
                sources.append({"title": title, "url": url})
    return sources


def unique_sources(*groups):
    result = []
    seen = set()
    for group in groups:
        for item in group:
            if item["url"] not in seen:
                result.append(item)
                seen.add(item["url"])
    return result


def nonempty(*parts):
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def build_route(workbook, previous=None, map_image=""):
    previous = previous or {}
    sheets = read_xlsx(workbook)
    general = {key: value for row in sheets["Общие материалы"] for key, value in row.items()}
    general_by_name = {general[f"A{i}"]: general.get(f"B{i}", "")
                       for i in range(1, 100) if f"A{i}" in general}
    plans = {int(row["A"].strip()): row for row in map(columns, sheets["План маршрута"])
             if row.get("A", "").strip().isdigit()}
    details = {int(row["A"].strip()): row for row in map(columns, sheets["Остановки"])
               if row.get("A", "").strip().isdigit()}
    stops = []
    for number, plan in sorted(plans.items()):
        detail = details.get(number, {})
        complete = bool(detail.get("I"))
        description = (detail["I"] if complete else nonempty(
            f"{PLACEHOLDER} Полная карточка остановки ещё не передана автором.",
            "Из авторского плана:\n" + plan.get("D", "")))
        look_for = (nonempty("Интересная деталь: " + detail.get("J", ""),
                             "Наблюдение на месте: " + detail.get("K", ""))
                    if complete else f"{PLACEHOLDER} Деталь для наблюдения будет добавлена автором.")
        transition = ""
        if number < max(plans):
            transition = (nonempty(detail.get("P", ""), detail.get("Q", ""), detail.get("R", ""))
                          if complete else nonempty(plan.get("F", ""), plan.get("G", "")))
        if complete:
            sources = unique_sources(
                source_list(detail.get("AG", ""), "Исторический источник"),
                source_list(detail.get("AI", ""), "Источник перехода"),
                source_list(detail.get("AJ", ""), "Источник координат"),
                [{"title": "Страница фотографии", "url": detail["Z"]}] if detail.get("Z") else [],
                [{"title": "Лицензия фотографии", "url": detail["AC"]}] if detail.get("AC") else [],
            )
        else:
            sources = unique_sources(
                source_list(plan.get("H", ""), "Исторический источник"),
                source_list(plan.get("I", ""), "Условия доступа"),
                source_list(plan.get("O", ""), "Источник координат"),
            )
        stop = {
            "id": f"stop-{number:02d}",
            "order": number,
            "title": detail.get("B") or plan["B"],
            "address": detail.get("D") or plan["C"],
            "latitude": float(detail.get("F") or plan["K"]),
            "longitude": float(detail.get("G") or plan["L"]),
            "map_point_url": detail.get("H") or plan.get("M", ""),
            "photo": detail.get("V", ""),
            "photo_url": detail.get("AA", ""),
            "photo_credit": detail.get("AR", ""),
            "description": description,
            "look_for": look_for,
            "task": detail.get("L", ""),
            "task_answer": detail.get("M", ""),
            "task_explanation": detail.get("N", ""),
            "visit_info": (nonempty(detail.get("E", ""), detail.get("T", ""), detail.get("U", ""))
                           if complete else plan.get("E", "")),
            "next_transition": transition,
            "sources": sources,
            "content_status": "complete" if complete else "plan_only",
        }
        stops.append(stop)
    route = {
        "is_placeholder": True,
        "title": general_by_name["Название маршрута"],
        "introduction": general_by_name["Вступление для бота"],
        "audience": general_by_name["Целевая аудитория"],
        "duration": general_by_name["Длительность и перемещения"],
        "transport": ["Пешком", "Метро (Сокольническая линия)"],
        "start_point": general_by_name["Начальная точка"],
        "end_point": general_by_name["Конечная точка"],
        "map_url": previous.get("map_url", ""),
        "map_image": map_image or previous.get("map_image", ""),
        "map_note": general_by_name["Как читать карту"] + "\n\n© OpenStreetMap contributors",
        "final_text": general_by_name["Итоговый текст для бота"],
        "authors": previous.get("authors", [f"{PLACEHOLDER} Имена авторов не указаны в книге"]),
        "stops": stops,
        "quiz": previous.get("quiz") or [
            {"question": f"{PLACEHOLDER} Вопрос {i}",
             "options": ["Вариант А", "Вариант Б"], "correct_index": 0,
             "explanation": f"{PLACEHOLDER} Пояснение {i}."}
            for i in range(1, 6)
        ],
    }
    return route


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--output", type=Path, default=Path("content/route.json"))
    parser.add_argument("--map-image", type=Path)
    args = parser.parse_args()
    previous = json.loads(args.output.read_text(encoding="utf-8")) if args.output.is_file() else {}
    map_image = ""
    if args.map_image:
        target = args.output.parent / "photos" / "route_map.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        if args.map_image.resolve() != target.resolve():
            shutil.copy2(args.map_image, target)
        map_image = "photos/route_map.png"
    route = build_route(args.workbook, previous, map_image)
    args.output.write_text(json.dumps(route, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    complete = sum(stop["content_status"] == "complete" for stop in route["stops"])
    print(f"Imported {len(route['stops'])} stops ({complete} complete), map image: {bool(route['map_image'])}")


if __name__ == "__main__":
    main()
