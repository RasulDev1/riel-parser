"""Проверка критериев поиска. Запуск из папки desktop: python tests/test_criteria.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from avito_client import Listing  # noqa: E402
from criteria import build_search_url, matches, parse_title  # noqa: E402

assert parse_title("2-к. квартира, 54,3 м², 5/9 эт.") == {"area": 54.3, "floor": 5, "floors_total": 9, "rooms": 2}
assert parse_title("Квартира-студия, 25 м², 1/17 эт.")["rooms"] == 0
assert parse_title("Комната 18 м² в 3-к., 2/5 эт.")["rooms"] == 1
assert parse_title("Дом 150 м², 2-этажный")["floors_total"] == 2

c = {"rooms": ["1", "2"], "price_max": 15_000_000, "area_min": 40, "not_last_floor": True,
     "districts": "Хамовники, Арбат", "exclude_words": "доля"}
assert build_search_url(c) == "https://www.avito.ru/moskva/kvartiry/prodam?pmax=15000000&user=1&s=104"


def L(title, price=14_000_000, addr="ул. Льва Толстого, Хамовники", desc=""):
    return Listing(id="1", title=title, url="", price=price, address=addr, description=desc)


assert matches(L("2-к. квартира, 54,3 м², 5/9 эт."), c) == (True, "")
assert matches(L("2-к. квартира, 54,3 м², 9/9 эт."), c)[1] == "последний этаж"
assert matches(L("3-к. квартира, 74 м², 5/9 эт."), c)[1] == "комнаты"
assert matches(L("2-к. квартира, 35 м², 5/9 эт."), c)[1] == "площадь"
assert matches(L("2-к. квартира, 54 м², 5/9 эт.", addr="Митино"), c)[1] == "район"
assert matches(L("2-к. квартира, 54 м², 5/9 эт.", desc="Продаётся доля 1/2"), c)[1] == "слово «доля»"
assert matches(L("2-к. квартира, 54 м², 5/9 эт.", price=16_000_000), c)[1] == "цена"
print("✓ Критерии работают")
