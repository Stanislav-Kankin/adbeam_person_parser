from __future__ import annotations

import os
import queue
import threading
import time
from pathlib import Path
from tkinter import Tk

from lead_enrichment.application import (
    InputInspection,
    PipelineRunRequest,
    inspect_kontur_input,
    run_kontur_pipeline,
)
from lead_enrichment.gui.main_view import MainView
from lead_enrichment.gui.progress import ProgressEstimate, ProgressEstimator, format_duration


class AppController:
    def __init__(self, root: Tk, view: MainView) -> None:
        self._root = root
        self._view = view
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._cancel_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._closing_deadline: float | None = None
        self._progress_estimator = ProgressEstimator()
        self._last_estimate: ProgressEstimate | None = None
        self._current_progress: tuple[int, int] | None = None
        self._run_active = False
        view.bind_actions(
            inspect_command=self.inspect,
            start_command=self.start,
            cancel_command=self.cancel,
        )
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self._drain_events)
        root.after(1000, self._tick_clock)

    def inspect(self) -> None:
        kontur = self._kontur_path()
        if kontur is None:
            return
        self._view.set_pipeline_stage(0)
        self._view.set_status(
            "Проверяю структуру файла и контрольные суммы ИНН",
            state="running",
        )
        self._view.set_input_summary("Читаю файл и собираю сводку…")
        self._start_worker(self._inspect_worker, kontur, cancelable=False)

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
        self._progress_estimator.start()
        self._last_estimate = None
        self._current_progress = (0, 0)
        self._run_active = True
        self._view.reset_run_progress()
        self._view.set_pipeline_stage(0)
        self._view.set_status("Начинаю обработку выгрузки Контур", state="running")
        self._start_worker(self._run_worker, request)

    def cancel(self) -> None:
        self._cancel_event.set()
        self._view.set_status(
            "Запрошена отмена — завершается текущая операция",
            state="warning",
        )

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

    def _start_worker(self, target, *args, cancelable: bool = True) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._view.set_busy(True, allow_cancel=cancelable)
        self._worker = threading.Thread(target=target, args=args, daemon=True)
        self._worker.start()

    def _inspect_worker(self, kontur: Path) -> None:
        try:
            result = inspect_kontur_input(kontur)
            self._events.put(("inspection", result))
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
                self._handle_status(str(payload))
            elif event == "progress":
                done, total = payload
                self._handle_progress(done, total)
            elif event == "inspection":
                self._handle_inspection(payload)
            elif event == "error":
                self._run_active = False
                self._view.set_status("Обработка завершилась с ошибкой", state="error")
                self._view.show_error(str(payload))
            elif event == "complete":
                result, output = payload
                self._handle_completion(result, output)
            elif event == "idle":
                self._view.set_busy(False)
        if self._root.winfo_exists():
            self._root.after(100, self._drain_events)

    def _handle_status(self, message: str) -> None:
        lowered = message.lower()
        if "читаю" in lowered or "проверя" in lowered:
            self._view.set_pipeline_stage(0)
        elif "подготавли" in lowered or "идентифиц" in lowered:
            self._view.set_pipeline_stage(1)
        elif "поиск" in lowered:
            self._view.set_pipeline_stage(2)
        elif "excel" in lowered or "экспорт" in lowered:
            self._view.set_pipeline_stage(3)
        if "отмен" in lowered:
            state = "warning"
        elif lowered == "готово":
            state = "success"
        else:
            state = "running"
        self._view.set_status(message, state=state)

    def _handle_progress(self, completed: int, total: int) -> None:
        self._current_progress = (completed, total)
        estimate = self._progress_estimator.update(completed, total)
        self._render_estimate(estimate)

    def _render_estimate(self, estimate: ProgressEstimate) -> None:
        self._last_estimate = estimate
        self._view.set_progress(
            estimate.completed,
            estimate.total,
            elapsed_seconds=estimate.elapsed_seconds,
            remaining_seconds=estimate.remaining_seconds,
            rate=estimate.items_per_second,
        )

    def _tick_clock(self) -> None:
        if self._run_active and self._current_progress is not None:
            completed, total = self._current_progress
            self._render_estimate(self._progress_estimator.update(completed, total))
        if self._root.winfo_exists():
            self._root.after(1000, self._tick_clock)

    def _handle_inspection(self, result: InputInspection) -> None:
        summary = (
            f"Принято по ИНН: {result.imported_companies} из {result.total_rows}; "
            f"пропущено: {result.skipped_rows}; невалидных ИНН: {result.invalid_inn_rows}; "
            f"дубликатов: {result.duplicate_inn_rows}. Сайты: {result.rows_with_website}; "
            f"руководители: {result.rows_with_manager}; email: {result.rows_with_emails}; "
            f"телефоны: {result.rows_with_phones}."
        )
        self._view.set_input_summary(summary)
        if result.imported_companies == 0:
            self._view.set_status("В файле нет строк с валидным ИНН", state="error")
            return
        state = "warning" if result.invalid_inn_rows or result.skipped_rows else "success"
        self._view.set_pipeline_stage(completed_through=0)
        self._view.set_status("Файл проверен — можно запускать обработку", state=state)

    def _handle_completion(self, result, output: Path) -> None:
        self._run_active = False
        if result.cancelled:
            self._view.set_status(
                "Обработка отменена; частичный результат сохранён",
                state="warning",
            )
        else:
            self._view.set_pipeline_stage(all_done=True)
            self._view.set_status("Готово — итоговый Excel сохранён", state="success")

        elapsed = (
            format_duration(self._last_estimate.elapsed_seconds)
            if self._last_estimate is not None
            else "—"
        )
        message = (
            f"Сохранено: {output}\n"
            f"Время обработки: {elapsed}\n"
            f"RESOLVED: {result.summary.resolved}; PARTIAL: {result.summary.partial}; "
            f"MANUAL_REQUIRED: {result.summary.manual_required}."
        )
        self._view.show_info(message)


def _default_checkpoint_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "AdBeamPersonParser" / "state" / "checkpoints.sqlite3"
