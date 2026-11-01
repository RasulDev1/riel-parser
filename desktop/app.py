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
# Фоновый мониторинг
# ----------------------------------------------------------------------------


class Runner:
    """Крутит Monitor в отдельном потоке со своим asyncio-циклом."""

    def __init__(self) -> None:
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

        def target() -> None:
            if sys.platform == "win32":
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.monitor = Monitor(cfg, dry_run=dry_run)
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
        if dry_run:
            log.warning("Telegram не настроен: новые объекты будут только в ленте приложения.")

    def stop(self, wait: float = 5) -> None:
        if self.running and self.loop and self.monitor:
            self.loop.call_soon_threadsafe(self.monitor.stop)
            self.thread.join(wait)
        self.started_at = None

    def state(self) -> dict:
        if self.running and self.monitor:
            return {**self.monitor.state, "dry_run": self.monitor.dry_run}
        return {"phase": "idle", "client": None, "next_check_at": None, "last_error": None, "dry_run": False}


# ----------------------------------------------------------------------------
# API, которое вызывает интерфейс (window.pywebview.api.*)
# ----------------------------------------------------------------------------


class Api:
    def __init__(self, log_handler: UiLogHandler) -> None:
        self._logs = log_handler
        self._runner = Runner()
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
                "anti_agent": {
                    "enabled": bool(aa.get("enabled", True)),
                    "max_active_listings": int(aa.get("max_active_listings") or 0),
                    "max_closed_listings": int(aa.get("max_closed_listings") or 0),
                    "skip_if_unknown": bool(aa.get("skip_if_unknown")),
                },
                "targets_to_watch": [
                    {
                        "client_name": str(t.get("client_name") or "").strip() or "Без имени",
                        "avito_url": str(t.get("avito_url") or "").strip(),
                        "enabled": bool(t.get("enabled", True)),
                    }
                    for t in raw.get("targets_to_watch") or []
                    if str(t.get("avito_url") or "").strip()
                ],
            }
            bad = [t["client_name"] for t in clean["targets_to_watch"] if "avito.ru" not in t["avito_url"]]
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
        found = ("sent", "dry_run")
        return {
            "found_today": sum(by.get(s, (0, 0))[1] for s in found),
            "found_total": sum(by.get(s, (0, 0))[0] for s in found),
            "agents": by.get("agent", (0, 0))[0],
            "duplicates": by.get("duplicate", (0, 0))[0],
            "baseline": by.get("baseline", (0, 0))[0],
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

    def shutdown(self) -> None:
        self._runner.stop(wait=3)


# ----------------------------------------------------------------------------
# Запуск
# ----------------------------------------------------------------------------


def run() -> None:
    main.ensure_dependencies({"webview": "pywebview>=5"})
    import webview  # type: ignore

    handler = UiLogHandler()
    main.setup_logging(verbose=False)
    logging.getLogger().addHandler(handler)

    api = Api(handler)
    window = webview.create_window(
        "Riel Parser — новые объекты Авито",
        url=str(UI_DIR / "index.html"),
        js_api=api,
        width=1280,
        height=820,
        min_size=(980, 640),
        background_color="#F6F7F9",
    )
    window.events.closing += lambda: api.shutdown()
    log.info("Приложение запущено. Данные: %s", main.BASE_DIR)
    webview.start(debug="--debug" in sys.argv)


if __name__ == "__main__":
    run()
