from __future__ import annotations

import os
import queue
import threading
import time
from pathlib import Path
from tkinter import Tk

from lead_enrichment.application import (
    PipelineRunRequest,
    inspect_kontur_input,
    run_kontur_pipeline,
)
from lead_enrichment.gui.main_view import MainView


class AppController:
    def __init__(self, root: Tk, view: MainView) -> None:
        self._root = root
        self._view = view
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._cancel_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._closing_deadline: float | None = None
        view.bind_actions(
            inspect_command=self.inspect,
            start_command=self.start,
            cancel_command=self.cancel,
        )
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self._drain_events)

    def inspect(self) -> None:
        kontur = self._kontur_path()
        if kontur is None:
            return
        self._start_worker(self._inspect_worker, kontur)

    def start(self) -> None:
        kontur = self._kontur_path()
        if kontur is None:
            return
        output_raw = self._view.output_path.get().strip()
        if not output_raw:
            self._view.show_error("Выберите путь итогового Excel")
            return
        roles = self._view.selected_roles()
        if not roles:
            self._view.show_error("Выберите хотя бы одну целевую роль")
            return
        request = PipelineRunRequest(
            kontur_file=kontur,
            output_file=Path(output_raw),
            checkpoint_file=_default_checkpoint_path(),
            target_roles=roles,
        )
        self._cancel_event.clear()
        self._view.set_progress(0, 0)
        self._start_worker(self._run_worker, request)

    def cancel(self) -> None:
        self._cancel_event.set()
        self._view.set_status("Запрошена отмена — завершается текущая операция")

    def close(self) -> None:
        if self._worker and self._worker.is_alive():
            if self._closing_deadline is None and not self._view.confirm_close():
                return
            self._cancel_event.set()
            self._closing_deadline = self._closing_deadline or time.monotonic() + 2.0
            self._wait_before_close()
            return
        self._root.destroy()

    def _wait_before_close(self) -> None:
        if not self._worker or not self._worker.is_alive():
            self._root.destroy()
            return
        if self._closing_deadline is not None and time.monotonic() >= self._closing_deadline:
            self._root.destroy()
            return
        self._root.after(100, self._wait_before_close)

    def _kontur_path(self) -> Path | None:
        raw = self._view.kontur_path.get().strip()
        if not raw:
            self._view.show_error("Выберите выгрузку Контур")
            return None
        path = Path(raw)
        if not path.is_file():
            self._view.show_error("Файл выгрузки Контур не найден")
            return None
        return path

    def _start_worker(self, target, *args) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._view.set_busy(True)
        self._worker = threading.Thread(target=target, args=args, daemon=True)
        self._worker.start()

    def _inspect_worker(self, kontur: Path) -> None:
        try:
            result = inspect_kontur_input(kontur)
            message = (
                f"Строк: {result.total_rows}; принято по ИНН: {result.imported_companies}; "
                f"пропущено: {result.skipped_rows}; невалидных ИНН: {result.invalid_inn_rows}; "
                f"дубликатов ИНН: {result.duplicate_inn_rows}; сайты: {result.rows_with_website}; "
                f"руководители: {result.rows_with_manager}; email: {result.rows_with_emails}; "
                f"телефоны: {result.rows_with_phones}."
            )
            self._events.put(("inspection", message))
        except Exception as error:
            self._events.put(("error", str(error)))
        finally:
            self._events.put(("idle", None))

    def _run_worker(self, request: PipelineRunRequest) -> None:
        try:
            result = run_kontur_pipeline(
                request,
                status_callback=lambda value: self._events.put(("status", value)),
                progress_callback=lambda done, total: self._events.put(
                    ("progress", (done, total))
                ),
                should_cancel=self._cancel_event.is_set,
            )
            self._events.put(("complete", (result, request.output_file)))
        except Exception as error:
            self._events.put(("error", str(error)))
        finally:
            self._events.put(("idle", None))

    def _drain_events(self) -> None:
        while True:
            try:
                event, payload = self._events.get_nowait()
            except queue.Empty:
                break
            if event == "status":
                self._view.set_status(str(payload))
            elif event == "progress":
                done, total = payload
                self._view.set_progress(done, total)
            elif event == "inspection":
                self._view.set_status(str(payload))
            elif event == "error":
                self._view.set_status("Ошибка")
                self._view.show_error(str(payload))
            elif event == "complete":
                result, output = payload
                message = (
                    f"Сохранено: {output}\n"
                    f"RESOLVED: {result.summary.resolved}; PARTIAL: {result.summary.partial}; "
                    f"MANUAL_REQUIRED: {result.summary.manual_required}."
                )
                self._view.set_status("Готово" if not result.cancelled else "Отменено")
                self._view.show_info(message)
            elif event == "idle":
                self._view.set_busy(False)
        if self._root.winfo_exists():
            self._root.after(100, self._drain_events)


def _default_checkpoint_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "AdBeamPersonParser" / "state" / "checkpoints.sqlite3"
