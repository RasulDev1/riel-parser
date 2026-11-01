"""
Офлайн-тест всего цикла без обращения к Авито и Telegram.
Запуск из папки cli:  python tests/test_offline.py
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import avito_client  # noqa: E402
import main  # noqa: E402


def item(i, title, price, desc, addr="ул. Ленина, 1"):
    return {"id": i, "title": title, "urlPath": f"/moskva/kvartiry/x_{i}", "description": desc,
            "priceDetailed": {"value": price, "string": f"{price:,} ₽".replace(",", " ")},
            "geo": {"formattedAddress": addr, "geoReferences": [{"content": "Хамовники"}]}}


def search_page(items):
    state = {"data": {"catalog": {"items": items}}}
    return f'<html><script type="mime/invalid" data-mfe-state="true">{json.dumps(state, ensure_ascii=False)}</script></html>'


def initial_data_page(items):
    state = {"catalog": {"items": items}, "padding": "x" * 300}
    return f'<html><script>window.__initialData__ = "{quote(json.dumps(state))}";\nwindow.__x = 1</script></html>'


LONG = "Продаю светлую квартиру в тихом центре, рядом парк и метро, без обременений, один собственник. "
PAGES = {}
PAGES["item_1"] = '<div data-marker="seller-info/name">Пётр</div><div data-marker="seller-info/label">Частное лицо</div><a href="/user/aaa/profile">профиль</a><div data-marker="item-view/x"></div>'
PAGES["item_2"] = '<div data-marker="seller-info/name">ЭлитСтрой</div><div>Агентство</div><a href="/user/bbb/profile">профиль</a><div data-marker="item-view/x"></div>'
PAGES["item_3"] = '<div data-marker="seller-info/name">Ольга</div><div>Частное лицо</div><a href="/user/ccc/profile">профиль</a><div data-marker="item-view/x"></div>'
PAGES["profile_aaa"] = "<h1>Пётр</h1><p>Частное лицо</p><p>1 объявление</p>"
PAGES["profile_ccc"] = "<h1>Ольга</h1><p>Частное лицо</p><p>7 объявлений</p>"


def run():
    tmp = Path(tempfile.mkdtemp())
    main.DB_PATH = tmp / "history.db"
    main.CONFIG_PATH = tmp / "config.json"
    main.CONFIG_PATH.write_text(json.dumps({**main.CONFIG_TEMPLATE, "global_check_interval_seconds": 10,
                                            "targets_to_watch": [{"client_name": "Иван 1к", "avito_url": "https://m.avito.ru/moskva/kvartiry/prodam?pmax=9000000&p=3"}]},
                                           ensure_ascii=False), encoding="utf-8")
    sent = []
    state = {"search": search_page([item(1, "1-к. квартира, 35 м², 3/9 эт.", 8_500_000, "старое")])}

    async def fake_get(self, url, referer=None):
        if "/kvartiry/prodam" in url:
            assert "s=104" in url and "p=3" not in url and url.startswith("https://www.avito.ru"), url
            return state["search"]
        if "/x_" in url:
            return PAGES[f"item_{url.rsplit('_', 1)[1]}"]
        if "/user/" in url:
            return PAGES.get(f"profile_{url.split('/user/')[1].split('/')[0]}", "")
        return ""

    async def fake_send(self, text):
        sent.append(text)
        return True

    async def no_sleep(*_a, **_k):
        return None

    avito_client.AvitoClient._get = fake_get
    main.Telegram.send = fake_send
    main.asyncio.sleep = no_sleep
    avito_client.asyncio.sleep = no_sleep

    async def cycle():
        m = main.Monitor(main.load_config())
        await m.run_once()
        await m.close()

    # 1) первый запуск: только запоминаем текущие объявления
    asyncio.run(cycle())
    assert sent == [], sent

    # 2) появились новые: 1 — частник, 2 — агентство, 3 — много объявлений, 4 — дубль текста 1
    state["search"] = initial_data_page([
        item(1, "1-к. квартира, 35 м², 3/9 эт.", 8_500_000, "старое"),
        item(10, "Квартира-студия, 25 м², 2/5 эт.", 7_000_000, LONG * 3),
        item(2, "1-к. квартира, 40 м², 5/9 эт.", 8_900_000, "Агентское " + LONG),
        item(3, "1-к. квартира, 38 м², 7/9 эт.", 8_800_000, "Ещё " + LONG),
        item(4, "Квартира-студия, 25 м², 2/5 эт.", 7_000_000, LONG * 3),
    ])
    PAGES["item_10"] = PAGES["item_1"]
    PAGES["item_4"] = PAGES["item_1"]
    asyncio.run(cycle())
    assert len(sent) == 1, sent
    msg = sent[0]
    assert "Иван 1к" in msg and "7 000 000 ₽" in msg and "https://www.avito.ru/moskva/kvartiry/x_10" in msg
    assert "Хамовники" in msg and "Частное лицо" in msg

    rows = dict(main.History(main.DB_PATH).db.execute("SELECT id, status FROM listings").fetchall())
    assert rows == {"1": "current", "10": "sent", "2": "agent", "3": "agent", "4": "duplicate"}, rows

    # 3) повторный проход: ничего нового
    asyncio.run(cycle())
    assert len(sent) == 1
    print(msg)
    print("\n✓ Офлайн-тест пройден:", rows)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run()
