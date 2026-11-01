"""
Riel Parser — десктоп-приложение для риелторов.

Окно с интерфейсом (pywebview + HTML/Tailwind), внутри тот же мониторинг Авито,
что и в консольной версии main.py. Запуск: python app.py  (или двойной клик по start_app.bat)
"""

from __future__ import annotations

import asyncio
import collections
import logging
import sys
import threading
import time
import webbrowser
from pathlib import Path

import main  # noqa: E402  (ставит httpx/curl_cffi при первом запуске)
import criteria  # noqa: E402
from main import (  # noqa: E402
    DB_PATH,
    History,
    Monitor,
    parse_config,
    read_raw_config,
    write_raw_config,
)

log = logging.getLogger("app")

UI_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "ui"


# ----------------------------------------------------------------------------
# Журнал для интерфейса
# ----------------------------------------------------------------------------


class UiLogHandler(logging.Handler):
    """Хранит последние строки лога, интерфейс забирает новые по id."""

    def __init__(self, capacity: int = 1500):
        super().__init__(logging.INFO)
        self.records: collections.deque = collections.deque(maxlen=capacity)
        self.counter = 0
        self._buf_lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            if record.exc_info and record.levelno >= logging.ERROR:
                msg = msg.splitlines()[0]
        except Exception:
            return
        with self._buf_lock:
            self.counter += 1
            self.records.append(
                {"id": self.counter, "time": time.strftime("%H:%M:%S", time.localtime(record.created)),
                 "level": record.levelname.lower(), "msg": msg.strip()}
            )

    def since(self, after_id: int) -> list[dict]:
        with self._buf_lock:
            return [r for r in self.records if r["id"] > after_id]


# ----------------------------------------------------------------------------
# Встроенный браузер для загрузки Авито
# ----------------------------------------------------------------------------


class BrowserLoader:
    """
    Открывает страницы Авито в скрытом окне встроенного браузера (Edge WebView2).
    Для Авито это обычный посетитель: настоящий браузер, свои куки, ваш IP.
    Если Авито просит пройти проверку, окно показывается, вы проходите её руками,
    и мониторинг продолжается сам.
    """

    CAPTCHA_WAIT = 10 * 60

    def __init__(self) -> None:
        self.window = None
        self._lock = threading.Lock()
        self._loaded = threading.Event()
        self.cancel = threading.Event()
        self.captcha = False

    def attach(self, window) -> None:
        self.window = window
        window.events.loaded += self._loaded.set

    def _html(self) -> str:
        return self.window.evaluate_js("document.documentElement.outerHTML") or ""

    def _load(self, url: str) -> str:
        self._loaded.clear()
        self.window.load_url(url)
        if not self._loaded.wait(40):
            raise RuntimeError("страница Авито не загрузилась за 40 с")
        # даём странице дорисоваться
        for _ in range(20):
            if self.window.evaluate_js("document.readyState") == "complete":
                break
            time.sleep(0.5)
        time.sleep(1.0)
        return self._html()

    def __call__(self, url: str) -> str:
        from avito_client import AvitoBlocked, is_block_page

        if self.window is None:
            raise RuntimeError("встроенный браузер не готов")
        with self._lock:
            html = self._load(url)
            if not is_block_page(html):
                return html

            log.warning("🧩 Авито просит подтвердить, что вы не робот. Пройдите проверку в открывшемся окне.")
            self.captcha = True
            self.window.show()
            try:
                deadline = time.time() + self.CAPTCHA_WAIT
                while time.time() < deadline and not self.cancel.is_set():
                    time.sleep(3)
                    try:
                        if not is_block_page(self._html()):
                            break
                    except Exception:
                        pass
                else:
                    if self.cancel.is_set():
                        raise AvitoBlocked("мониторинг остановлен во время проверки")
                    raise AvitoBlocked("проверку Авито не прошли за 10 минут")
            finally:
                self.captcha = False
                try:
                    self.window.hide()
                except Exception:
                    pass
            log.info("✅ Проверка пройдена, продолжаю.")
            return self._load(url)


# ----------------------------------------------------------------------------
# Фоновый мониторинг
# ----------------------------------------------------------------------------


class Runner:
    """Крутит Monitor в отдельном потоке со своим asyncio-циклом."""

    def __init__(self, browser: BrowserLoader | None = None) -> None:
        self.browser = browser
        self.thread: threading.Thread | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.monitor: Monitor | None = None
        self.started_at: float | None = None

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, cfg: main.Config) -> None:
        if self.running:
            return
        dry_run = not (cfg.token and cfg.chat_id)
        ready = threading.Event()
        use_browser = self.browser is not None and self.browser.window is not None and cfg.browser_mode
        if self.browser:
            self.browser.cancel.clear()

        def target() -> None:
            if sys.platform == "win32":
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.monitor = Monitor(cfg, dry_run=dry_run, page_loader=self.browser if use_browser else None)
            ready.set()
            try:
                self.loop.run_until_complete(self.monitor.run_forever())
            except Exception:
                log.exception("Мониторинг остановился из-за ошибки")
            finally:
                try:
                    self.loop.run_until_complete(self.monitor.close())
                except Exception:
                    pass
                self.loop.close()

        self.thread = threading.Thread(target=target, name="monitor", daemon=True)
        self.thread.start()
        ready.wait(5)
        self.started_at = time.time()
        log.info("Загрузка страниц: %s", "встроенный браузер" if use_browser else "прямые запросы (curl_cffi)")
        if dry_run:
            log.warning("Telegram не настроен: новые объекты будут только в ленте приложения.")

    def stop(self, wait: float = 5) -> None:
        if self.browser:
            self.browser.cancel.set()
        if self.running and self.loop and self.monitor:
            self.loop.call_soon_threadsafe(self.monitor.stop)
            self.thread.join(wait)
        self.started_at = None

    def state(self) -> dict:
        if self.running and self.monitor:
            st = {**self.monitor.state, "dry_run": self.monitor.dry_run}
            if self.browser and self.browser.captcha:
                st["phase"] = "captcha"
            return st
        return {"phase": "idle", "client": None, "next_check_at": None, "last_error": None, "dry_run": False}


# ----------------------------------------------------------------------------
# API, которое вызывает интерфейс (window.pywebview.api.*)
# ----------------------------------------------------------------------------


class Api:
    def __init__(self, log_handler: UiLogHandler, browser: BrowserLoader | None = None) -> None:
        self._logs = log_handler
        self._browser = browser
        self._runner = Runner(browser)
        self._db_lock = threading.Lock()
        self._history = History(DB_PATH)
        self._history.db.close()  # таблицы созданы; дальше читаем отдельными подключениями

    # --- настройки -----------------------------------------------------------

    def get_config(self) -> dict:
        return read_raw_config()

    def save_config(self, raw: dict) -> dict:
        try:
            aa = raw.get("anti_agent") or {}
            clean = {
                "telegram_bot_token": str(raw.get("telegram_bot_token", "")).strip(),
                "rieltor_chat_id": str(raw.get("rieltor_chat_id", "")).strip(),
                "global_check_interval_seconds": max(main.MIN_INTERVAL, float(raw.get("global_check_interval_seconds") or 60)),
                "jitter_seconds": max(0.0, float(raw.get("jitter_seconds") or 0)),
                "notify_on_first_run": bool(raw.get("notify_on_first_run")),
                "avito_cookies": str(raw.get("avito_cookies") or "").strip(),
                "browser_mode": bool(raw.get("browser_mode", True)),
                "anti_agent": {
                    "enabled": bool(aa.get("enabled", True)),
                    "max_active_listings": int(aa.get("max_active_listings") or 0),
                    "max_closed_listings": int(aa.get("max_closed_listings") or 0),
                    "skip_if_unknown": bool(aa.get("skip_if_unknown")),
                },
                "targets_to_watch": [self._clean_target(t) for t in raw.get("targets_to_watch") or []],
            }
            bad = [
                t["client_name"] for t in clean["targets_to_watch"]
                if t["mode"] == "url" and "avito.ru" not in t["avito_url"]
            ]
            if bad:
                return {"ok": False, "error": f"Ссылка не похожа на Авито: {', '.join(bad)}"}
            write_raw_config(clean)
        except (TypeError, ValueError) as e:
            return {"ok": False, "error": f"Проверьте числа в настройках ({e})"}

        restarted = False
        if self._runner.running:
            self._runner.stop()
            result = self.start()
            restarted = result.get("ok", False)
        log.info("Настройки сохранены%s.", ", мониторинг перезапущен" if restarted else "")
        return {"ok": True, "restarted": restarted, "config": clean}

    @staticmethod
    def _clean_target(t: dict) -> dict:
        mode = t.get("mode") or ("url" if t.get("avito_url") else "criteria")
        return {
            "client_name": str(t.get("client_name") or "").strip() or "Без имени",
            "enabled": bool(t.get("enabled", True)),
            "mode": "url" if mode == "url" else "criteria",
            "avito_url": str(t.get("avito_url") or "").strip(),
            "criteria": criteria.normalize(t.get("criteria")),
        }

    def get_options(self) -> dict:
        return {
            "cities": criteria.CITIES,
            "categories": criteria.CATEGORIES,
            "deals": criteria.DEALS,
            "defaults": criteria.DEFAULT_CRITERIA,
        }

    def build_url(self, crit: dict) -> str:
        return criteria.build_search_url(crit or {})

    # --- мониторинг ----------------------------------------------------------

    def start(self) -> dict:
        try:
            cfg = parse_config(read_raw_config())
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        self._runner.start(cfg)
        return {"ok": True}

    def stop(self) -> dict:
        self._runner.stop()
        return {"ok": True}

    def status(self) -> dict:
        st = self._runner.state()
        counts = self._counts()
        return {
            "running": self._runner.running,
            "started_at": self._runner.started_at,
            "now": time.time(),
            **st,
            "counts": counts,
        }

    def test_telegram(self, token: str, chat_id: str) -> dict:
        import httpx

        token, chat_id = (token or "").strip(), (chat_id or "").strip()
        if not token or not chat_id:
            return {"ok": False, "error": "Заполните токен бота и chat id"}
        try:
            r = httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": "✅ Riel Parser подключён. Новые объекты будут приходить сюда."},
                timeout=15,
            )
            data = r.json()
        except Exception as e:
            return {"ok": False, "error": f"Нет связи с Telegram: {e}"}
        if data.get("ok"):
            return {"ok": True}
        desc = data.get("description", "неизвестная ошибка")
        if "chat not found" in desc:
            desc = "чат не найден: сначала напишите своему боту любое сообщение"
        elif "Unauthorized" in desc:
            desc = "неверный токен бота"
        return {"ok": False, "error": desc}

    # --- данные --------------------------------------------------------------

    def _query(self, sql: str, params: tuple = ()) -> list[tuple]:
        import sqlite3

        with self._db_lock:
            con = sqlite3.connect(DB_PATH, timeout=10)
            try:
                return con.execute(sql, params).fetchall()
            finally:
                con.close()

    def _counts(self) -> dict:
        midnight = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        rows = self._query(
            "SELECT status, COUNT(*), SUM(created_at >= ?) FROM listings GROUP BY status", (midnight,)
        )
        by = {s: (total, today or 0) for s, total, today in rows}
        per_client = dict(self._query(
            "SELECT client_name, COUNT(*) FROM listings WHERE status IN ('sent', 'dry_run') GROUP BY client_name"
        ))
        found = ("sent", "dry_run")
        return {
            "found_today": sum(by.get(s, (0, 0))[1] for s in found),
            "found_total": sum(by.get(s, (0, 0))[0] for s in found),
            "agents": by.get("agent", (0, 0))[0],
            "duplicates": by.get("duplicate", (0, 0))[0],
            "baseline": by.get("baseline", (0, 0))[0],
            "by_client": per_client,
        }

    def listings(self, status: str = "found", query: str = "", limit: int = 300) -> list[dict]:
        where, params = [], []
        if status == "found":
            where.append("status IN ('sent', 'dry_run')")
        elif status in ("agent", "duplicate"):
            where.append("status = ?")
            params.append(status)
        else:
            where.append("status != 'baseline'")
        if query:
            where.append("(title LIKE ? OR address LIKE ? OR client_name LIKE ? OR description LIKE ?)")
            params += [f"%{query}%"] * 4
        sql = (
            "SELECT id, client_name, title, price, price_text, address, description, url, status, seller, reason,"
            " created_at FROM listings WHERE " + " AND ".join(where) + " ORDER BY created_at DESC LIMIT ?"
        )
        rows = self._query(sql, (*params, int(limit)))
        keys = ["id", "client", "title", "price", "price_text", "address", "description", "url", "status",
                "seller", "reason", "created_at"]
        return [dict(zip(keys, r)) for r in rows]

    def logs(self, after_id: int = 0) -> list[dict]:
        return self._logs.since(int(after_id))

    def open_url(self, url: str) -> None:
        if url.startswith("https://"):
            webbrowser.open(url)

    def reset_client(self, client_name: str) -> dict:
        """Забыть историю клиента: при следующей проверке текущие объявления снова станут «базой»."""
        import sqlite3

        with self._db_lock:
            con = sqlite3.connect(DB_PATH, timeout=10)
            try:
                con.execute("DELETE FROM listings WHERE client_name = ? AND status = 'baseline'", (client_name,))
                con.commit()
            finally:
                con.close()
        return {"ok": True}

    def show_browser(self) -> dict:
        """Открыть окно встроенного браузера, например чтобы зайти на Авито или пройти проверку."""
        if not self._browser or not self._browser.window:
            return {"ok": False, "error": "Встроенный браузер недоступен"}
        if not self._browser.captcha:
            threading.Thread(target=lambda: self._browser.window.load_url("https://www.avito.ru/"), daemon=True).start()
        self._browser.window.show()
        return {"ok": True}

    def shutdown(self) -> None:
        self._runner.stop(wait=3)


# ----------------------------------------------------------------------------
# Запуск
# ----------------------------------------------------------------------------


def serve_in_browser(api: "Api") -> None:
    """
    Запасной режим: интерфейс открывается в обычном браузере по адресу http://127.0.0.1:<порт>.
    Работает без pywebview. Встроенный браузер для Авито в этом режиме недоступен.
    """
    import json
    import secrets
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    token = secrets.token_urlsafe(16)
    bridge = (
        "<script>window.pywebview={api:new Proxy({},{get:(_,m)=>(...a)=>fetch('/api/'+m,"
        "{method:'POST',headers:{'X-Token':'%s','Content-Type':'application/json'},body:JSON.stringify(a)})"
        ".then(r=>r.json())})};</script>" % token
    ).encode()
    allowed = {name for name in dir(api) if not name.startswith("_")}

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(UI_DIR), **k)

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                body = (UI_DIR / "index.html").read_bytes().replace(b'<script src="app.js">', bridge + b'<script src="app.js">')
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def do_POST(self):
            name = self.path.rsplit("/", 1)[-1]
            if self.headers.get("X-Token") != token or name not in allowed:
                self.send_error(403)
                return
            try:
                args = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"[]")
                result = getattr(api, name)(*args)
                body = json.dumps(result, ensure_ascii=False).encode()
            except Exception as e:
                log.exception("Ошибка в %s", name)
                body = json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    log.info("Интерфейс открыт в браузере: %s", url)
    print(f"\nИнтерфейс Riel Parser открыт в браузере: {url}\nНе закрывайте это окно, пока работаете. Выход: Ctrl+C или закройте окно.\n", flush=True)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        api.shutdown()


def run() -> None:
    handler = UiLogHandler()
    main.setup_logging(verbose=False)
    logging.getLogger().addHandler(handler)

    if "--browser" in sys.argv:
        serve_in_browser(Api(handler))
        return

    try:
        main.ensure_dependencies({"webview": "pywebview>=5"})
        import webview  # type: ignore
    except (Exception, SystemExit) as e:
        log.warning("Окно приложения недоступно (%s), открываю интерфейс в браузере.", e)
        serve_in_browser(Api(handler))
        return

    browser = BrowserLoader()
    api = Api(handler, browser)
    avito_window = webview.create_window(
        "Авито — встроенный браузер Riel Parser",
        html="<!doctype html><meta charset='utf-8'><title>Авито</title>",
        hidden=True,
        width=1100,
        height=800,
    )
    browser.attach(avito_window)
    quitting = {"v": False}

    def on_avito_closing():
        # Крестик просто прячет окно: оно нужно для работы мониторинга
        if quitting["v"]:
            return True
        avito_window.hide()
        return False

    avito_window.events.closing += on_avito_closing

    window = webview.create_window(
        "Riel Parser — новые объекты Авито",
        url=str(UI_DIR / "index.html"),
        js_api=api,
        width=1280,
        height=820,
        min_size=(980, 640),
        background_color="#F6F7F9",
    )

    def on_main_closing():
        quitting["v"] = True
        api.shutdown()
        try:
            avito_window.destroy()
        except Exception:
            pass

    window.events.closing += on_main_closing
    log.info("Приложение запущено. Данные: %s", main.BASE_DIR)
    try:
        # Постоянный профиль браузера: куки Авито и пройденная капча сохраняются между запусками
        webview.start(
            debug="--debug" in sys.argv,
            private_mode=False,
            storage_path=str(main.BASE_DIR / "browser_profile"),
        )
    except Exception as e:
        log.exception("Не удалось открыть окно приложения: %s", e)
        print(
            "\nОкно приложения не открылось (подробности в parser.log). "
            "Открываю интерфейс в обычном браузере.\n"
            "Чтобы окно работало, установите Microsoft Edge WebView2 Runtime: "
            "https://go.microsoft.com/fwlink/p/?LinkId=2124703\n",
            flush=True,
        )
        browser.window = None  # встроенный браузер недоступен, Авито грузится прямыми запросами
        api._runner.browser = None
        serve_in_browser(api)


if __name__ == "__main__":
    run()
