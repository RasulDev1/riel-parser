"""
Работа с Авито: загрузка страниц с эмуляцией браузера и разбор объявлений.

Почему не «мобильное JSON API»: внутреннее API приложения Авито требует ключ,
вытащенный из приложения, часто меняется и за него банят быстрее всего.
Вместо этого берём обычную страницу выдачи, но не парсим HTML-вёрстку, а
достаём из неё встроенное JSON-состояние (то же, чем рендерится страница).
Запросы идут через curl_cffi с TLS-отпечатком настоящего Chrome, поэтому
Авито видит обычный браузер, а не python-скрипт.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import json
import logging
import random
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

log = logging.getLogger("avito")

AVITO = "https://www.avito.ru"

try:
    from curl_cffi.requests import AsyncSession  # type: ignore

    HAS_CURL_CFFI = True
except ImportError:  # запасной вариант без эмуляции TLS
    import httpx

    HAS_CURL_CFFI = False


class AvitoBlocked(Exception):
    """Авито показал капчу / заблокировал IP (403, 429, страница «Доступ ограничен»)."""


# ----------------------------------------------------------------------------
# Модели
# ----------------------------------------------------------------------------


@dataclass
class Listing:
    id: str
    title: str
    url: str
    price: int | None = None
    price_text: str = ""
    address: str = ""
    description: str = ""
    seller_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class SellerInfo:
    is_agency: bool = False
    active_count: int | None = None
    closed_count: int | None = None
    label: str = ""          # «Частное лицо», «Агентство» и т.п., если удалось найти
    profile_url: str | None = None
    checked: bool = False    # удалось ли вообще что-то узнать о продавце


# ----------------------------------------------------------------------------
# Ссылки
# ----------------------------------------------------------------------------


def normalize_search_url(url: str) -> str:
    """
    Приводит ссылку из браузера к виду, удобному для мониторинга:
    m.avito.ru -> www.avito.ru, сортировка «по дате» (s=104), первая страница.
    Все фильтры риелтора (цена, площадь, район и т.д.) сохраняются как есть.
    """
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url.lstrip("/")
    p = urlparse(url)
    host = "www.avito.ru" if p.netloc.endswith("avito.ru") else p.netloc
    params = dict(parse_qsl(p.query, keep_blank_values=True))
    params["s"] = "104"          # сначала новые
    params.pop("p", None)        # всегда первая страница
    params.pop("context", None)  # длинный трекинговый параметр, не нужен
    return urlunparse(("https", host, p.path, "", urlencode(params), ""))


def absolute(url_path: str | None) -> str | None:
    if not url_path:
        return None
    if url_path.startswith("http"):
        return url_path
    return AVITO + ("" if url_path.startswith("/") else "/") + url_path


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------

_BLOCK_MARKERS = re.compile(
    r"Доступ ограничен|проблема с IP|firewall-container|firewall-title|Вы робот|не робот",
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def is_block_page(page: str) -> bool:
    """
    Страница-заглушка Авито («Доступ ограничен», капча). Смотрим только заголовок
    и характерные блоки: слово captcha встречается и в скриптах обычных страниц,
    поэтому по нему одному страницу блокировкой не считаем.
    """
    if not page:
        return False
    title_m = _TITLE_RE.search(page[:50000])
    title = title_m.group(1) if title_m else ""
    if re.search(r"Доступ ограничен|не робот|Вы робот|captcha|Проверка", title, re.IGNORECASE):
        return True
    return bool(re.search(r"firewall-container|firewall-title|js-firewall", page[:200000]))


# 429 — слишком много запросов, 439/403 — Авито так отвечает на подозрение в боте
BLOCK_STATUSES = {401, 403, 429, 439}


class AvitoClient:
    def __init__(self, timeout: float = 25.0, cookies: str = "", page_loader: Callable[[str], str] | None = None):
        self._timeout = timeout
        # Загрузчик через встроенный браузер приложения (WebView2). Если задан, страницы
        # открываются как у обычного посетителя: со своими куками, JS и возможностью пройти капчу.
        self._page_loader = page_loader
        # Куки из своего браузера (строка заголовка Cookie). Помогают, если Авито
        # уже показал капчу: проходите её в браузере и вставляете куки в config.json
        self._cookies = cookies.strip()
        if HAS_CURL_CFFI:
            # impersonate="chrome" — TLS/HTTP2-отпечаток актуального Chrome
            self._session = AsyncSession(impersonate="chrome", timeout=timeout)
        else:
            log.warning("curl_cffi не установлен: работаю через httpx, риск капчи выше.")
            self._session = httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                    )
                },
            )
        self._warmed_up = False

    async def close(self) -> None:
        await self._session.close() if HAS_CURL_CFFI else await self._session.aclose()

    async def _get(self, url: str, referer: str | None = None) -> str:
        if self._page_loader is not None:
            text = await asyncio.to_thread(self._page_loader, url)
            if is_block_page(text):
                raise AvitoBlocked("капча в браузере")
            return text
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        if referer:
            headers["Referer"] = referer
        if self._cookies:
            headers["Cookie"] = self._cookies
        if HAS_CURL_CFFI:
            resp = await self._session.get(url, headers=headers, allow_redirects=True)
        else:
            resp = await self._session.get(url, headers=headers)
        status = resp.status_code
        text = resp.text
        if status in BLOCK_STATUSES or (status >= 400 and _BLOCK_MARKERS.search(text[:20000])) or is_block_page(text):
            raise AvitoBlocked(f"HTTP {status}")
        if status >= 400:
            raise RuntimeError(f"Авито ответил HTTP {status} на {url}")
        return text

    async def _warm_up(self) -> None:
        """Заходим на главную, чтобы получить куки, как обычный посетитель."""
        if self._warmed_up or self._page_loader is not None:
            return
        try:
            await self._get(AVITO + "/")
            await asyncio.sleep(random.uniform(1.0, 2.5))
        except AvitoBlocked:
            raise
        except Exception as e:  # главная не критична
            log.debug("Прогрев не удался: %s", e)
        self._warmed_up = True

    debug_dir = None  # куда сохранять страницу, если на ней не нашлось объявлений

    async def search(self, url: str) -> list[Listing]:
        await self._warm_up()
        page = await self._get(normalize_search_url(url), referer=AVITO + "/")
        items = parse_search_page(page)
        if not items:
            title_m = _TITLE_RE.search(page[:50000])
            log.warning(
                "   На странице не распознано ни одного объявления. Заголовок страницы: «%s», размер %s КБ.",
                _strip_tags(title_m.group(1)) if title_m else "нет",
                len(page) // 1024,
            )
            if self.debug_dir is not None:
                try:
                    path = self.debug_dir / "debug_last_page.html"
                    path.write_text(page, encoding="utf-8")
                    log.warning("   Сохранил страницу в %s — пришлите этот файл разработчику.", path)
                except OSError:
                    pass
        return items

    async def item_seller(self, listing: Listing) -> SellerInfo:
        """Открывает карточку объявления и достаёт данные о продавце."""
        item_html = await self._get(listing.url, referer=AVITO + "/")
        return parse_item_seller(item_html)

    async def fill_profile(self, info: SellerInfo, referer: str) -> None:
        """Открывает профиль продавца и дописывает число объявлений и тип профиля."""
        if not info.profile_url:
            return
        await asyncio.sleep(random.uniform(1.5, 3.5))
        try:
            merge_profile(info, await self._get(info.profile_url, referer=referer))
        except AvitoBlocked:
            raise
        except Exception as e:
            log.debug("Профиль %s не открылся: %s", info.profile_url, e)


# ----------------------------------------------------------------------------
# Извлечение встроенного JSON
# ----------------------------------------------------------------------------

_SCRIPT_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)
_INITIAL_DATA_RE = re.compile(r"window\.__initialData__\s*=\s*\"(.*?)\"\s*;?\s*(?:window|$)", re.DOTALL)


def _json_blobs(page: str) -> Iterator[Any]:
    """Все JSON-объекты, встроенные в страницу (разные версии вёрстки Авито)."""
    m = _INITIAL_DATA_RE.search(page)
    if m:
        try:
            yield json.loads(unquote(m.group(1)))
        except ValueError:
            pass
    for body in _SCRIPT_RE.findall(page):
        body = body.strip()
        if len(body) < 200:
            continue
        if body[0] in "{[":
            candidate = html_lib.unescape(body) if "&quot;" in body[:200] else body
            try:
                yield json.loads(candidate)
            except ValueError:
                continue


def _walk(node: Any) -> Iterator[Any]:
    stack = [node]
    while stack:
        cur = stack.pop()
        yield cur
        if isinstance(cur, dict):
            stack.extend(reversed(list(cur.values())))
        elif isinstance(cur, list):
            stack.extend(reversed(cur))


def _looks_like_item(d: Any) -> bool:
    return (
        isinstance(d, dict)
        and "id" in d
        and isinstance(d.get("title"), str)
        and isinstance(d.get("urlPath"), str)
    )


def _price(d: dict[str, Any]) -> tuple[int | None, str]:
    pd = d.get("priceDetailed") or {}
    value = pd.get("value") if isinstance(pd, dict) else None
    text = (pd.get("fullString") or pd.get("string") or "") if isinstance(pd, dict) else ""
    if value is None:
        value = d.get("price")
    try:
        value = int(float(value)) if value is not None else None
    except (TypeError, ValueError):
        value = _digits(str(value))
    if not text and value:
        text = f"{value:,} ₽".replace(",", " ")
    return value, text


def _address(d: dict[str, Any]) -> str:
    geo = d.get("geo") or {}
    parts: list[str] = []
    if isinstance(geo, dict):
        if geo.get("formattedAddress"):
            parts.append(str(geo["formattedAddress"]))
        for ref in geo.get("geoReferences") or []:
            if isinstance(ref, dict) and ref.get("content"):
                parts.append(str(ref["content"]))
    if not parts:
        loc = d.get("location") or {}
        if isinstance(loc, dict) and loc.get("name"):
            parts.append(str(loc["name"]))
        if d.get("address"):
            parts.append(str(d["address"]))
    return ", ".join(dict.fromkeys(parts))


def _digits(s: str) -> int | None:
    digits = re.sub(r"\D", "", s or "")
    return int(digits) if digits else None


def _item_from_json(d: dict[str, Any]) -> Listing:
    price, price_text = _price(d)
    seller_path = None
    for key in ("userLink", "sellerLink", "profileLink"):
        if isinstance(d.get(key), str):
            seller_path = d[key]
    return Listing(
        id=str(d["id"]),
        title=d["title"].strip(),
        url=absolute(d["urlPath"]) or "",
        price=price,
        price_text=price_text,
        address=_address(d),
        description=re.sub(r"\s+", " ", str(d.get("description") or "")).strip(),
        seller_url=absolute(seller_path),
        raw=d,
    )


# ----------------------------------------------------------------------------
# Страница выдачи
# ----------------------------------------------------------------------------


def parse_search_page(page: str) -> list[Listing]:
    found: dict[str, Listing] = {}
    for blob in _json_blobs(page):
        for node in _walk(blob):
            if _looks_like_item(node):
                item = _item_from_json(node)
                found.setdefault(item.id, item)
    if found:
        return list(found.values())
    log.debug("JSON-состояние не найдено, разбираю HTML-вёрстку")
    return _parse_search_html(page)


_ITEM_BLOCK_RE = re.compile(r'<div[^>]*data-marker="item"[^>]*data-item-id="(\d+)"(.*?)(?=<div[^>]*data-marker="item"|\Z)', re.DOTALL)


def _strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _parse_search_html(page: str) -> list[Listing]:
    """Запасной разбор по data-marker, если Авито перестанет встраивать JSON."""
    items = []
    for item_id, block in _ITEM_BLOCK_RE.findall(page):
        title_m = re.search(r'data-marker="item-title"[^>]*?(?:title="([^"]*)")?[^>]*href="([^"]+)"|href="([^"]+)"[^>]*data-marker="item-title"[^>]*?(?:title="([^"]*)")?', block)
        if not title_m:
            continue
        href = title_m.group(2) or title_m.group(3)
        title = title_m.group(1) or title_m.group(4) or ""
        if not title:
            t = re.search(r'data-marker="item-title"[^>]*>(.*?)</a>', block, re.DOTALL)
            title = _strip_tags(t.group(1)) if t else ""
        price_m = re.search(r'itemprop="price"[^>]*content="(\d+)"', block)
        addr_m = re.search(r'data-marker="item-address"[^>]*>(.*?)</div>\s*</div>', block, re.DOTALL)
        desc_m = re.search(r'itemprop="description"[^>]*content="([^"]*)"', block) or re.search(
            r'class="[^"]*description[^"]*"[^>]*>(.*?)</', block, re.DOTALL
        )
        if price_m:
            price = int(price_m.group(1))
        else:
            pm = re.search(r'data-marker="item-price"[^>]*>(.*?)</', block, re.DOTALL)
            price = _digits(_strip_tags(pm.group(1))) if pm else None
        items.append(
            Listing(
                id=item_id,
                title=html_lib.unescape(title).strip(),
                url=absolute(html_lib.unescape(href)) or "",
                price=price,
                price_text=f"{price:,} ₽".replace(",", " ") if price else "",
                address=_strip_tags(addr_m.group(1)) if addr_m else "",
                description=_strip_tags(desc_m.group(1)) if desc_m else "",
            )
        )
    return items


# ----------------------------------------------------------------------------
# Продавец (для фильтра «Анти-Агент»)
# ----------------------------------------------------------------------------

AGENCY_WORDS = re.compile(r"\b(Агентство|Компания|Застройщик|Риелтор|Риэлтор|Агент|Застройщика)\b", re.IGNORECASE)
PRIVATE_WORDS = re.compile(r"Частное лицо|Собственник", re.IGNORECASE)
_PROFILE_LINK_RE = re.compile(r'href="(/(?:user|brands)/[^"?#]+)')
_ACTIVE_RE = re.compile(r"(\d+)\s*(?:активн\w*\s*)?объявлени", re.IGNORECASE)
_CLOSED_RE = re.compile(r"(?:Завершен\w*|Завершён\w*|Закрыт\w*|Продан\w*)[^0-9<]{0,40}?(\d+)|(\d+)\s*(?:завершён\w*|завершен\w*|закрыт\w*)", re.IGNORECASE)


def _seller_nodes(page: str) -> Iterator[dict[str, Any]]:
    for blob in _json_blobs(page):
        for node in _walk(blob):
            if isinstance(node, dict) and any(k in node for k in ("sellerType", "isCompany", "isShop", "profileType", "sellerInfo")):
                yield node


def parse_item_seller(page: str) -> SellerInfo:
    info = SellerInfo()

    # 1) Структурированные данные из JSON-состояния карточки
    for node in _seller_nodes(page):
        info.checked = True
        for key in ("isCompany", "isShop", "isAgency"):
            if node.get(key) is True:
                info.is_agency = True
        for key in ("sellerType", "profileType", "type"):
            val = node.get(key)
            if isinstance(val, str) and (AGENCY_WORDS.search(val) or val.lower() in ("company", "shop", "agency")):
                info.is_agency = True
                info.label = str(val)
        for key in ("profileUrl", "link", "userLink", "url"):
            val = node.get(key)
            if isinstance(val, str) and re.match(r"^(?:https?://www\.avito\.ru)?/(?:user|brands)/", val):
                info.profile_url = absolute(val)

    # 2) Текст блока продавца на странице
    seller_block_m = re.search(r'data-marker="seller-info[^"]*"(.*?)(?:data-marker="item-view/|$)', page, re.DOTALL)
    seller_text = _strip_tags(seller_block_m.group(1))[:1500] if seller_block_m else ""
    if seller_text:
        info.checked = True
        if PRIVATE_WORDS.search(seller_text):
            info.label = info.label or "Частное лицо"
        elif AGENCY_WORDS.search(seller_text):
            info.is_agency = True
            info.label = info.label or AGENCY_WORDS.search(seller_text).group(1)
        m = _ACTIVE_RE.search(seller_text)
        if m:
            info.active_count = int(m.group(1))

    if not info.profile_url:
        m = _PROFILE_LINK_RE.search(page)
        if m:
            info.profile_url = absolute(html_lib.unescape(m.group(1)))
    return info


def merge_profile(info: SellerInfo, page: str) -> None:
    """Дополняет SellerInfo данными со страницы профиля продавца."""
    text = _strip_tags(page)
    info.checked = True
    if "/brands/" in (info.profile_url or ""):
        info.is_agency = True  # /brands/ — магазины и компании
    head = text[:6000]
    if not PRIVATE_WORDS.search(head) and AGENCY_WORDS.search(head):
        info.is_agency = True
        info.label = info.label or AGENCY_WORDS.search(head).group(1)

    # Количество объявлений: сначала из JSON, затем из текста
    for blob in _json_blobs(page):
        for node in _walk(blob):
            if not isinstance(node, dict):
                continue
            for key in ("activeItemsCount", "activeCount", "itemsCount"):
                if isinstance(node.get(key), int):
                    info.active_count = max(info.active_count or 0, node[key])
            for key in ("closedItemsCount", "closedCount", "soldCount"):
                if isinstance(node.get(key), int):
                    info.closed_count = max(info.closed_count or 0, node[key])
    if info.active_count is None:
        m = _ACTIVE_RE.search(text)
        if m:
            info.active_count = int(m.group(1))
    if info.closed_count is None:
        m = _CLOSED_RE.search(text)
        if m:
            info.closed_count = int(m.group(1) or m.group(2))
