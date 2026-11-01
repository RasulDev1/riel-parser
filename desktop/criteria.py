"""
Критерии поиска, которые риелтор задаёт прямо в приложении.

Авито принимает в адресе только город, категорию, тип сделки, цену и «частные/компании».
Комнаты, площадь, этажи и район в адресе у Авито закодированы внутренними id,
поэтому их проверяем сами по заголовку и адресу каждого объявления.
Для мониторинга этого хватает: проверяется первая страница, отсортированная
по дате, а новые объявления всегда оказываются наверху.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlencode

from avito_client import Listing

# Слаг города — так, как он написан в адресе avito.ru/<слаг>/...
CITIES: list[tuple[str, str]] = [
    ("moskva", "Москва"),
    ("moskovskaya_oblast", "Московская область"),
    ("sankt-peterburg", "Санкт-Петербург"),
    ("leningradskaya_oblast", "Ленинградская область"),
    ("mahachkala", "Махачкала"),
    ("kaspiysk", "Каспийск"),
    ("derbent", "Дербент"),
    ("respublika_dagestan", "Республика Дагестан"),
    ("novosibirsk", "Новосибирск"),
    ("ekaterinburg", "Екатеринбург"),
    ("kazan", "Казань"),
    ("nizhniy_novgorod", "Нижний Новгород"),
    ("chelyabinsk", "Челябинск"),
    ("samara", "Самара"),
    ("ufa", "Уфа"),
    ("rostov-na-donu", "Ростов-на-Дону"),
    ("krasnodar", "Краснодар"),
    ("sochi", "Сочи"),
    ("omsk", "Омск"),
    ("voronezh", "Воронеж"),
    ("perm", "Пермь"),
    ("volgograd", "Волгоград"),
    ("krasnoyarsk", "Красноярск"),
    ("saratov", "Саратов"),
    ("tyumen", "Тюмень"),
    ("kaliningrad", "Калининград"),
    ("stavropol", "Ставрополь"),
    ("pyatigorsk", "Пятигорск"),
]

CATEGORIES: list[tuple[str, str]] = [
    ("kvartiry", "Квартиры"),
    ("komnaty", "Комнаты"),
    ("doma_dachi_kottedzhi", "Дома, дачи, коттеджи"),
    ("zemelnye_uchastki", "Земельные участки"),
    ("kommercheskaya_nedvizhimost", "Коммерческая"),
]

DEALS: list[tuple[str, str]] = [
    ("prodam", "Купить"),
    ("sdam/na_dlitelnyy_srok", "Снять надолго"),
    ("sdam/posutochno", "Снять посуточно"),
]

ROOM_OPTIONS = ["studio", "1", "2", "3", "4+"]

DEFAULT_CRITERIA: dict[str, Any] = {
    "city": "moskva",
    "category": "kvartiry",
    "deal": "prodam",
    "rooms": [],
    "price_min": None,
    "price_max": None,
    "area_min": None,
    "area_max": None,
    "floor_min": None,
    "floor_max": None,
    "floors_total_min": None,
    "floors_total_max": None,
    "not_first_floor": False,
    "not_last_floor": False,
    "districts": "",
    "exclude_words": "доля, аукцион, апартаменты",
    "private_only": True,
}


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _words(s: Any) -> list[str]:
    return [w.strip().lower() for w in re.split(r"[,;\n]", str(s or "")) if w.strip()]


def normalize(c: dict[str, Any] | None) -> dict[str, Any]:
    c = {**DEFAULT_CRITERIA, **(c or {})}
    c["city"] = re.sub(r"[^a-z0-9_\-]", "", str(c["city"]).strip().lower()) or "moskva"
    if c["category"] not in dict(CATEGORIES):
        c["category"] = "kvartiry"
    if c["deal"] not in dict(DEALS):
        c["deal"] = "prodam"
    c["rooms"] = [r for r in (c.get("rooms") or []) if r in ROOM_OPTIONS]
    for k in ("price_min", "price_max", "area_min", "area_max", "floor_min", "floor_max",
              "floors_total_min", "floors_total_max"):
        c[k] = _num(c.get(k))
    for k in ("not_first_floor", "not_last_floor", "private_only"):
        c[k] = bool(c.get(k))
    c["districts"] = str(c.get("districts") or "")
    c["exclude_words"] = str(c.get("exclude_words") or "")
    return c


def build_search_url(c: dict[str, Any]) -> str:
    c = normalize(c)
    deal = c["deal"]
    if c["category"] in ("zemelnye_uchastki", "kommercheskaya_nedvizhimost") and deal.startswith("sdam/"):
        deal = "sdam"  # у участков и коммерции нет деления на «надолго/посуточно»
    params: dict[str, str] = {}
    if c["price_min"]:
        params["pmin"] = str(int(c["price_min"]))
    if c["price_max"]:
        params["pmax"] = str(int(c["price_max"]))
    if c["private_only"]:
        params["user"] = "1"  # только частные лица
    params["s"] = "104"  # сначала новые
    return f"https://www.avito.ru/{c['city']}/{c['category']}/{deal}?{urlencode(params)}"


def criteria_key(c: dict[str, Any]) -> str:
    """Ключ для «первого запуска»: если критерии поменялись, текущая выдача снова станет базой."""
    blob = json.dumps(normalize(c), sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


# ----------------------------------------------------------------------------
# Разбор заголовка
# ----------------------------------------------------------------------------

_AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*м²")
_FLOOR_RE = re.compile(r"(\d+)\s*/\s*(\d+)\s*эт")
_FLOORS_HOUSE_RE = re.compile(r"(\d+)\s*-?\s*этаж", re.IGNORECASE)
_ROOMS_RE = re.compile(r"(\d+)\s*-\s*к\b|(\d+)-комн", re.IGNORECASE)


def parse_title(title: str) -> dict[str, Any]:
    """«2-к. квартира, 54,3 м², 5/9 эт.» → площадь, этаж, этажность, комнаты (0 = студия)."""
    area = _AREA_RE.search(title)
    floor = _FLOOR_RE.search(title)
    rooms_m = _ROOMS_RE.search(title)
    rooms: int | None
    if re.match(r"\s*Комната", title, re.IGNORECASE):
        rooms = 1  # «Комната 18 м² в 3-к.» — продаётся одна комната
    elif re.search(r"студи|свободн\w* планир", title, re.IGNORECASE):
        rooms = 0
    elif rooms_m:
        rooms = int(rooms_m.group(1) or rooms_m.group(2))
    else:
        rooms = None
    total = int(floor.group(2)) if floor else None
    if total is None:
        house = _FLOORS_HOUSE_RE.search(title)  # «Дом 120 м², 2-этажный»
        total = int(house.group(1)) if house else None
    return {
        "area": float(area.group(1).replace(",", ".")) if area else None,
        "floor": int(floor.group(1)) if floor else None,
        "floors_total": total,
        "rooms": rooms,
    }


def _in_range(v: float | None, lo: float | None, hi: float | None) -> bool:
    if lo is None and hi is None:
        return True
    if v is None:
        return False
    return (lo is None or v >= lo) and (hi is None or v <= hi)


def matches(item: Listing, c: dict[str, Any]) -> tuple[bool, str]:
    """Подходит ли объявление под критерии. Возвращает (да/нет, почему нет)."""
    c = normalize(c)
    t = parse_title(item.title)

    if not _in_range(item.price, c["price_min"], c["price_max"]):
        return False, "цена"
    if c["rooms"] and c["category"] == "kvartiry":
        r = t["rooms"]
        ok = r is not None and (
            (r == 0 and "studio" in c["rooms"])
            or (r >= 4 and "4+" in c["rooms"])
            or (1 <= r <= 3 and str(r) in c["rooms"])
        )
        if not ok:
            return False, "комнаты"
    if not _in_range(t["area"], c["area_min"], c["area_max"]):
        return False, "площадь"
    if not _in_range(t["floor"], c["floor_min"], c["floor_max"]):
        return False, "этаж"
    if not _in_range(t["floors_total"], c["floors_total_min"], c["floors_total_max"]):
        return False, "этажность"
    if c["not_first_floor"] and t["floor"] == 1:
        return False, "первый этаж"
    if c["not_last_floor"] and t["floor"] is not None and t["floor"] == t["floors_total"]:
        return False, "последний этаж"

    text = f"{item.title} {item.address}".lower()
    districts = _words(c["districts"])
    if districts and not any(d in text for d in districts):
        return False, "район"
    full = f"{text} {item.description}".lower()
    for w in _words(c["exclude_words"]):
        if w in full:
            return False, f"слово «{w}»"
    return True, ""


def describe(c: dict[str, Any]) -> str:
    """Короткое описание для журнала: «Москва · Квартиры · Купить · 1, 2-к · до 12 млн»."""
    c = normalize(c)
    parts = [dict(CITIES).get(c["city"], c["city"]), dict(CATEGORIES)[c["category"]], dict(DEALS)[c["deal"]]]
    if c["rooms"]:
        parts.append(", ".join("студия" if r == "studio" else r for r in c["rooms"]) + " комн.")
    if c["price_min"] or c["price_max"]:
        lo = f"от {int(c['price_min']):,}".replace(",", " ") if c["price_min"] else ""
        hi = f"до {int(c['price_max']):,}".replace(",", " ") if c["price_max"] else ""
        parts.append(f"{lo} {hi} ₽".strip())
    return " · ".join(parts)
