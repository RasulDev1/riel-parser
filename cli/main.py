"""
Консольный мониторинг Авито для риелторов.

Следит за ссылками поиска из config.json, находит новые объявления, отсеивает
агентов и дубли и присылает новые объекты в Telegram.

Запуск:
    python main.py                 # обычный режим, работает бесконечно
    python main.py --once          # один проход по всем ссылкам и выход
    python main.py --dry-run       # ничего не отправлять в Telegram, только лог
    python main.py --test-telegram # отправить тестовое сообщение и выйти
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import logging
import random
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


def ensure_dependencies() -> None:
    """
    При первом запуске сам ставит недостающие библиотеки через pip.
    В собранном .exe всё уже внутри, там ничего не делаем.
    """
    if getattr(sys, "frozen", False):
        return
    import importlib.util
    import subprocess

    required = {"httpx": "httpx>=0.27", "curl_cffi": "curl_cffi>=0.7"}
    missing = [pkg for module, pkg in required.items() if importlib.util.find_spec(module) is None]
    if not missing:
        return
    print(f"Устанавливаю недостающие библиотеки: {', '.join(missing)} ...", flush=True)
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *missing]
    if subprocess.call(cmd) != 0:
        # без прав администратора пробуем поставить в профиль пользователя
        if subprocess.call(cmd + ["--user"]) != 0:
            print("Не удалось установить библиотеки. Выполните вручную:\n  " + " ".join(cmd))
            raise SystemExit(1)
    importlib.invalidate_caches()
    print("Библиотеки установлены.\n", flush=True)


ensure_dependencies()

import httpx  # noqa: E402

from avito_client import AvitoBlocked, AvitoClient, Listing, SellerInfo, normalize_search_url  # noqa: E402

# ----------------------------------------------------------------------------
# Пути: рядом со скриптом или рядом с .exe (PyInstaller)
# ----------------------------------------------------------------------------

BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
DB_PATH = BASE_DIR / "history.db"
LOG_PATH = BASE_DIR / "parser.log"

log = logging.getLogger("monitor")

CONFIG_TEMPLATE = {
    "telegram_bot_token": "123456:ABC-ваш-токен-от-BotFather",
    "rieltor_chat_id": "123456789",
    "global_check_interval_seconds": 60,
    "jitter_seconds": 3,
    "notify_on_first_run": False,
    "anti_agent": {
        "enabled": True,
        "max_active_listings": 1,
        "max_closed_listings": 0,
        "skip_if_unknown": False,
    },
    "targets_to_watch": [
        {
            "client_name": "Иван 1к",
            "avito_url": "https://www.avito.ru/moskva/kvartiry/prodam/1-komnatnye-ASgBAgICAkSSA8YQygiAWQ?pmax=12000000",
        }
    ],
}

MIN_INTERVAL = 10  # быстрее Авито почти гарантированно покажет капчу


# ----------------------------------------------------------------------------
# Конфиг
# ----------------------------------------------------------------------------


@dataclass
class Target:
    client_name: str
    avito_url: str


@dataclass
class AntiAgent:
    enabled: bool = True
    max_active_listings: int = 1
    max_closed_listings: int = 0
    skip_if_unknown: bool = False


@dataclass
class Config:
    token: str
    chat_id: str
    interval: float
    jitter: float
    notify_on_first_run: bool
    anti_agent: AntiAgent
    targets: list[Target] = field(default_factory=list)


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        example = BASE_DIR / "config.example.json"
        if example.exists():
            CONFIG_PATH.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            log.warning("config.json не найден, скопировал config.example.json. Для проверки этого хватит, "
                        "для работы впишите токен бота, chat id и свои ссылки: %s", CONFIG_PATH)
            return load_config()
        CONFIG_PATH.write_text(json.dumps(CONFIG_TEMPLATE, ensure_ascii=False, indent=2), encoding="utf-8")
        log.error("Файл config.json не найден. Создал шаблон: %s. Заполните его и запустите снова.", CONFIG_PATH)
        raise SystemExit(1)
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        log.error("Ошибка в config.json (строка %s, столбец %s): %s", e.lineno, e.colno, e.msg)
        raise SystemExit(1)

    targets = [
        Target(str(t.get("client_name") or "Без имени"), str(t["avito_url"]))
        for t in raw.get("targets_to_watch", [])
        if t.get("avito_url")
    ]
    if not targets:
        log.error("В config.json нет ни одной ссылки в targets_to_watch.")
        raise SystemExit(1)

    interval = float(raw.get("global_check_interval_seconds", 60))
    if interval < MIN_INTERVAL:
        log.warning("Интервал %s с слишком мал, Авито быстро заблокирует. Использую %s с.", interval, MIN_INTERVAL)
        interval = MIN_INTERVAL

    aa = raw.get("anti_agent") or {}
    return Config(
        token=str(raw.get("telegram_bot_token", "")).strip(),
        chat_id=str(raw.get("rieltor_chat_id", "")).strip(),
        interval=interval,
        jitter=float(raw.get("jitter_seconds", 3)),
        notify_on_first_run=bool(raw.get("notify_on_first_run", False)),
        anti_agent=AntiAgent(
            enabled=bool(aa.get("enabled", True)),
            max_active_listings=int(aa.get("max_active_listings", 1)),
            max_closed_listings=int(aa.get("max_closed_listings", 0)),
            skip_if_unknown=bool(aa.get("skip_if_unknown", False)),
        ),
        targets=targets,
    )


# ----------------------------------------------------------------------------
# SQLite
# ----------------------------------------------------------------------------


class History:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS listings (
                id          TEXT PRIMARY KEY,
                text_hash   TEXT,
                client_name TEXT,
                title       TEXT,
                price       INTEGER,
                url         TEXT,
                status      TEXT,          -- sent / agent / duplicate / baseline / dry_run
                created_at  INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_listings_hash ON listings(text_hash);
            CREATE TABLE IF NOT EXISTS sellers (
                profile_url TEXT PRIMARY KEY,
                is_agent    INTEGER,
                details     TEXT,
                checked_at  INTEGER
            );
            CREATE TABLE IF NOT EXISTS targets_seen (
                url TEXT PRIMARY KEY
            );
            """
        )
        self.db.commit()

    @staticmethod
    def text_hash(item: Listing) -> str | None:
        text = " ".join((item.description or "").lower().split())
        if len(text) < 40:  # слишком короткое описание, по тексту не сравниваем
            return None
        return hashlib.sha1(text[:500].encode("utf-8")).hexdigest()

    def seen_id(self, item_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM listings WHERE id = ?", (item_id,)).fetchone() is not None

    def seen_text(self, h: str | None) -> bool:
        if not h:
            return False
        return self.db.execute("SELECT 1 FROM listings WHERE text_hash = ?", (h,)).fetchone() is not None

    def save(self, item: Listing, client: str, status: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO listings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (item.id, self.text_hash(item), client, item.title, item.price, item.url, status, int(time.time())),
        )
        self.db.commit()

    def target_is_new(self, url: str) -> bool:
        return self.db.execute("SELECT 1 FROM targets_seen WHERE url = ?", (url,)).fetchone() is None

    def mark_target(self, url: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO targets_seen VALUES (?)", (url,))
        self.db.commit()

    def cached_seller(self, profile_url: str, max_age: int = 7 * 86400) -> bool | None:
        row = self.db.execute(
            "SELECT is_agent, checked_at FROM sellers WHERE profile_url = ?", (profile_url,)
        ).fetchone()
        if row and time.time() - row[1] < max_age:
            return bool(row[0])
        return None

    def save_seller(self, profile_url: str, is_agent: bool, details: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO sellers VALUES (?, ?, ?, ?)",
            (profile_url, int(is_agent), details, int(time.time())),
        )
        self.db.commit()


# ----------------------------------------------------------------------------
# Telegram
# ----------------------------------------------------------------------------


class Telegram:
    def __init__(self, token: str, chat_id: str, dry_run: bool = False):
        self.token = token
        self.chat_id = chat_id
        self.dry_run = dry_run
        self.http = httpx.AsyncClient(timeout=20)

    async def close(self) -> None:
        await self.http.aclose()

    async def send(self, text: str) -> bool:
        if self.dry_run:
            log.info("[dry-run] Сообщение в Telegram:\n%s", text)
            return True
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False}
        for attempt in range(3):
            try:
                r = await self.http.post(url, json=payload)
                data = r.json()
                if data.get("ok"):
                    return True
                if r.status_code == 429:
                    wait = int(data.get("parameters", {}).get("retry_after", 5))
                    log.warning("Telegram просит подождать %s с", wait)
                    await asyncio.sleep(wait + 1)
                    continue
                log.error("Telegram не принял сообщение: %s", data.get("description"))
                return False
            except httpx.HTTPError as e:
                log.warning("Ошибка связи с Telegram (%s), попытка %s/3", e, attempt + 1)
                await asyncio.sleep(3 * (attempt + 1))
        return False


def format_message(client: str, item: Listing, seller: SellerInfo | None) -> str:
    e = html.escape
    desc = item.description[:150].rstrip()
    if len(item.description) > 150:
        desc += "…"
    lines = [
        f"🏠 <b>Новый объект для: {e(client)}</b>",
        "",
        f"<b>{e(item.title)}</b>",
        f"💰 {e(item.price_text or 'цена не указана')}",
    ]
    if item.address:
        lines.append(f"📍 {e(item.address)}")
    if desc:
        lines += ["", f"<i>{e(desc)}</i>"]
    if seller is not None and seller.checked:
        who = seller.label or "продавец"
        cnt = f", объявлений: {seller.active_count}" if seller.active_count is not None else ""
        lines.append(f"👤 {e(who)}{e(cnt)}")
    elif seller is not None:
        lines.append("👤 ⚠️ продавца проверить не удалось")
    lines += ["", f'🔗 <a href="{e(item.url, quote=True)}">Открыть на Авито</a>']
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Основная логика
# ----------------------------------------------------------------------------


class Monitor:
    def __init__(self, cfg: Config, dry_run: bool = False):
        self.cfg = cfg
        self.history = History(DB_PATH)
        self.avito = AvitoClient()
        self.tg = Telegram(cfg.token, cfg.chat_id, dry_run=dry_run)
        self.dry_run = dry_run
        self.block_streak = 0

    async def close(self) -> None:
        await self.avito.close()
        await self.tg.close()

    def _verdict(self, info: SellerInfo) -> tuple[bool, str]:
        """True, если это агент и объявление надо пропустить."""
        aa = self.cfg.anti_agent
        if info.is_agency:
            return True, f"профиль компании/агентства ({info.label or 'по признакам на странице'})"
        if info.active_count is not None and info.active_count > aa.max_active_listings:
            return True, f"у продавца {info.active_count} активных объявлений"
        if info.closed_count is not None and info.closed_count > aa.max_closed_listings:
            return True, f"у продавца {info.closed_count} завершённых объявлений"
        if not info.checked and aa.skip_if_unknown:
            return True, "не удалось проверить продавца"
        return False, ""

    async def check_seller(self, item: Listing) -> tuple[bool, str, SellerInfo | None]:
        if not self.cfg.anti_agent.enabled:
            return False, "", None
        try:
            info = await self.avito.item_seller(item)
        except AvitoBlocked:
            raise
        except Exception as e:
            log.warning("   Не удалось открыть карточку %s: %s", item.id, e)
            info = SellerInfo()

        if info.profile_url and not info.is_agency:
            cached = self.history.cached_seller(info.profile_url)
            if cached is not None:  # этого продавца уже проверяли за последнюю неделю
                return cached, "по сохранённой проверке продавца", info
            await self.avito.fill_profile(info, referer=item.url)

        is_agent, reason = self._verdict(info)
        if info.profile_url and info.checked:
            self.history.save_seller(
                info.profile_url, is_agent, f"{info.label}; active={info.active_count}; closed={info.closed_count}"
            )
        return is_agent, reason, info

    async def process_target(self, target: Target) -> None:
        log.info("🔎 Ищу для «%s»...", target.client_name)
        items = await self.avito.search(target.avito_url)
        log.info("   На странице %s объявлений", len(items))
        if not items:
            log.warning("   Объявлений не найдено. Проверьте ссылку или откройте её в браузере (возможна капча).")

        key = normalize_search_url(target.avito_url)
        first_run = self.history.target_is_new(key)
        if first_run and not self.cfg.notify_on_first_run:
            for it in items:
                self.history.save(it, target.client_name, "baseline")
            self.history.mark_target(key)
            log.info("   Первый запуск для этой ссылки: запомнил %s текущих объявлений, присылать буду только новые.", len(items))
            return
        self.history.mark_target(key)

        fresh = [it for it in items if not self.history.seen_id(it.id)]
        sent = 0
        for item in fresh:
            if self.history.seen_text(self.history.text_hash(item)):
                log.info("   ↪ Дубль по тексту: %s", item.title)
                self.history.save(item, target.client_name, "duplicate")
                continue

            await asyncio.sleep(random.uniform(1.5, 3.5))
            is_agent, reason, seller = await self.check_seller(item)
            if is_agent:
                log.info("   🚫 Агент, пропускаю: %s (%s)", item.title, reason)
                self.history.save(item, target.client_name, "agent")
                continue

            ok = await self.tg.send(format_message(target.client_name, item, seller))
            if ok:
                sent += 1
                self.history.save(item, target.client_name, "dry_run" if self.dry_run else "sent")
                log.info("   ✅ Отправил: %s, %s", item.title, item.price_text)
            else:
                log.warning("   Не отправилось, попробую при следующей проверке: %s", item.title)

        log.info("   Найдено %s новых объектов, отправлено %s", len(fresh), sent)

    async def run_once(self) -> None:
        for i, target in enumerate(self.cfg.targets):
            try:
                await self.process_target(target)
                self.block_streak = 0
            except AvitoBlocked as e:
                self.block_streak += 1
                pause = min(60 * 2 ** (self.block_streak - 1), 30 * 60)
                log.error("⛔ Авито ограничил доступ (%s). Пауза %s мин.", e, pause // 60)
                if self.block_streak == 1:
                    await self.tg.send(
                        "⛔ Авито временно ограничил доступ с этого компьютера. "
                        f"Парсер сделает паузу {pause // 60} мин и продолжит сам. "
                        "Если повторяется, откройте Авито в браузере и пройдите капчу."
                    )
                await asyncio.sleep(pause)
                self.avito._warmed_up = False
            except Exception as e:
                log.exception("Ошибка при проверке «%s»: %s", target.client_name, e)

            if i < len(self.cfg.targets) - 1:
                await self._pause()

    async def _pause(self) -> None:
        delay = max(MIN_INTERVAL / 2, self.cfg.interval + random.uniform(-self.cfg.jitter, self.cfg.jitter))
        log.info("⏳ Ожидание %.1f с...", delay)
        await asyncio.sleep(delay)

    async def run_forever(self) -> None:
        log.info("Запущено. Ссылок для мониторинга: %s. Интервал %s±%s с.", len(self.cfg.targets), self.cfg.interval, self.cfg.jitter)
        while True:
            await self.run_once()
            await self._pause()


# ----------------------------------------------------------------------------
# Точка входа
# ----------------------------------------------------------------------------


def setup_logging(verbose: bool) -> None:
    fmt = logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    file = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(console)
    root.addHandler(file)
    for noisy in ("httpx", "httpcore", "curl_cffi"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def amain(args: argparse.Namespace) -> None:
    cfg = load_config()
    if not args.dry_run and (not cfg.token or "ваш-токен" in cfg.token or not cfg.chat_id):
        log.error("Укажите telegram_bot_token и rieltor_chat_id в config.json (или запустите с --dry-run).")
        raise SystemExit(1)

    monitor = Monitor(cfg, dry_run=args.dry_run)
    try:
        if args.test_telegram:
            ok = await monitor.tg.send("✅ Парсер Авито подключён. Уведомления будут приходить сюда.")
            log.info("Тестовое сообщение %s", "отправлено" if ok else "НЕ отправлено")
        elif args.once:
            await monitor.run_once()
        else:
            await monitor.run_forever()
    finally:
        await monitor.close()


def main() -> None:
    if sys.platform == "win32":
        # curl_cffi в asyncio на Windows требует selector-цикл
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Мониторинг новых объявлений Авито с уведомлениями в Telegram")
    parser.add_argument("--once", action="store_true", help="один проход по всем ссылкам и выход")
    parser.add_argument("--dry-run", action="store_true", help="не отправлять в Telegram, только писать в консоль")
    parser.add_argument("--test-telegram", action="store_true", help="отправить тестовое сообщение и выйти")
    parser.add_argument("-v", "--verbose", action="store_true", help="подробный лог")
    args = parser.parse_args()

    setup_logging(args.verbose)
    code = 0
    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        log.info("Остановлено пользователем.")
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    # Если .exe запущен двойным кликом, не даём окну сразу закрыться
    if getattr(sys, "frozen", False):
        try:
            input("Нажмите Enter, чтобы закрыть окно...")
        except EOFError:
            pass
    sys.exit(code)


if __name__ == "__main__":
    main()
