from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tkinter import StringVar, Text, Tk, filedialog, messagebox
from tkinter import ttk

from lead_enrichment.gui.progress import format_duration
from lead_enrichment.models import ContactRole

BACKGROUND = "#F3F6FA"
CARD = "#FFFFFF"
NAVY = "#14213D"
BLUE = "#2563EB"
BLUE_DARK = "#1D4ED8"
TEXT = "#172033"
MUTED = "#64748B"
BORDER = "#DCE3EC"
GREEN = "#15803D"
GREEN_BG = "#DCFCE7"
AMBER = "#B45309"
AMBER_BG = "#FEF3C7"
RED = "#B91C1C"
RED_BG = "#FEE2E2"

PIPELINE_STEPS = (
    "Проверка файла",
    "Подготовка компаний",
    "Поиск на сайтах",
    "Экспорт результата",
)


class MainView:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.kontur_path = StringVar(master=root)
        self.output_path = StringVar(master=root)
        self.marketing_enabled = StringVar(master=root, value="1")
        self.sales_enabled = StringVar(master=root, value="1")
        self.status_text = StringVar(master=root, value="Выберите выгрузку Контур с ИНН")
        self.status_badge = StringVar(master=root, value="ОЖИДАНИЕ")
        self.progress_text = StringVar(master=root, value="0 из 0")
        self.elapsed_text = StringVar(master=root, value="0 сек")
        self.eta_text = StringVar(master=root, value="—")
        self.rate_text = StringVar(master=root, value="—")
        self.input_summary = StringVar(
            master=root,
            value="После проверки здесь появится сводка по ИНН и доступным данным.",
        )
        self._editable_widgets: list[ttk.Widget] = []
        self._step_labels: list[ttk.Label] = []
        self._configure_styles()
        self._build()

    def bind_actions(
        self,
        *,
        inspect_command: Callable[[], None],
        start_command: Callable[[], None],
        cancel_command: Callable[[], None],
    ) -> None:
        self.inspect_button.configure(command=inspect_command)
        self.start_button.configure(command=start_command)
        self.cancel_button.configure(command=cancel_command)

    def selected_roles(self) -> tuple[ContactRole, ...]:
        roles: list[ContactRole] = []
        if self.marketing_enabled.get() == "1":
            roles.append(ContactRole.MARKETING)
        if self.sales_enabled.get() == "1":
            roles.append(ContactRole.SALES)
        return tuple(roles)

    def set_busy(self, busy: bool, *, allow_cancel: bool = True) -> None:
        editable_state = "disabled" if busy else "normal"
        for widget in self._editable_widgets:
            widget.configure(state=editable_state)
        self.inspect_button.configure(state=editable_state)
        self.start_button.configure(state=editable_state)
        self.cancel_button.configure(
            state="normal" if busy and allow_cancel else "disabled"
        )

    def reset_run_progress(self) -> None:
        self.set_progress(0, 0, elapsed_seconds=0, remaining_seconds=None, rate=None)
        self.set_pipeline_stage(-1)

    def set_status(self, value: str, *, state: str | None = None) -> None:
        self.status_text.set(value)
        if state is not None:
            self.set_state(state)
        self.append_log(value)

    def set_state(self, state: str) -> None:
        labels = {
            "idle": ("ОЖИДАНИЕ", "StatusIdle.TLabel"),
            "running": ("В РАБОТЕ", "StatusRunning.TLabel"),
            "success": ("ГОТОВО", "StatusSuccess.TLabel"),
            "warning": ("ОТМЕНА", "StatusWarning.TLabel"),
            "error": ("ОШИБКА", "StatusError.TLabel"),
        }
        text, style = labels.get(state, labels["idle"])
        self.status_badge.set(text)
        self.status_badge_label.configure(style=style)

    def set_input_summary(self, value: str) -> None:
        self.input_summary.set(value)

    def set_progress(
        self,
        completed: int,
        total: int,
        *,
        elapsed_seconds: float,
        remaining_seconds: float | None,
        rate: float | None,
    ) -> None:
        self.progress.configure(maximum=max(total, 1), value=completed)
        self.progress_text.set(f"{completed} из {total}")
        self.elapsed_text.set(format_duration(elapsed_seconds))
        self.eta_text.set(format_duration(remaining_seconds) if total else "—")
        self.rate_text.set(f"{rate * 60:.1f} комп./мин" if rate else "—")

    def set_pipeline_stage(
        self,
        active_index: int = -1,
        *,
        completed_through: int = -1,
        all_done: bool = False,
    ) -> None:
        for index, label in enumerate(self._step_labels):
            if all_done or index <= completed_through or index < active_index:
                prefix = "✓"
                style = "StepDone.TLabel"
            elif index == active_index:
                prefix = "●"
                style = "StepActive.TLabel"
            else:
                prefix = "○"
                style = "StepPending.TLabel"
            label.configure(text=f"{prefix}  {index + 1}. {PIPELINE_STEPS[index]}", style=style)

    def append_log(self, value: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"{value}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def show_error(self, message: str) -> None:
        messagebox.showerror("AdBeam Person Parser", message, parent=self.root)

    def show_info(self, message: str) -> None:
        messagebox.showinfo("AdBeam Person Parser", message, parent=self.root)

    def confirm_close(self) -> bool:
        return messagebox.askyesno(
            "Остановить обработку?",
            "Текущая ограниченная операция завершится, после чего приложение закроется.",
            parent=self.root,
        )

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("App.TFrame", background=BACKGROUND)
        style.configure("Header.TFrame", background=NAVY)
        style.configure("Card.TFrame", background=CARD, borderwidth=1, relief="solid")
        style.configure("Inner.TFrame", background=CARD, borderwidth=0, relief="flat")
        style.configure("HeaderTitle.TLabel", background=NAVY, foreground="#FFFFFF", font=("Segoe UI", 21, "bold"))
        style.configure("HeaderSub.TLabel", background=NAVY, foreground="#B8C7E0", font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background=CARD, foreground=TEXT, font=("Segoe UI", 12, "bold"))
        style.configure("CardText.TLabel", background=CARD, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("MetricValue.TLabel", background=CARD, foreground=TEXT, font=("Segoe UI", 13, "bold"))
        style.configure("MetricLabel.TLabel", background=CARD, foreground=MUTED, font=("Segoe UI", 8))
        style.configure("Card.TCheckbutton", background=CARD, foreground=TEXT, font=("Segoe UI", 10))
        style.map("Card.TCheckbutton", background=[("active", CARD)])
        style.configure("Accent.TButton", background=BLUE, foreground="#FFFFFF", borderwidth=0, padding=(18, 10), font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", BLUE_DARK), ("disabled", "#AFC5F5")])
        style.configure("Secondary.TButton", background="#E8EEF7", foreground=TEXT, borderwidth=0, padding=(14, 9), font=("Segoe UI", 10))
        style.map("Secondary.TButton", background=[("active", "#DCE6F3")])
        style.configure("Danger.TButton", background=RED_BG, foreground=RED, borderwidth=0, padding=(14, 9), font=("Segoe UI", 10, "bold"))
        style.map("Danger.TButton", background=[("active", "#FECACA")])
        style.configure("App.Horizontal.TProgressbar", troughcolor="#E7EDF5", background=BLUE, lightcolor=BLUE, darkcolor=BLUE, bordercolor="#E7EDF5", thickness=14)
        style.configure("StatusIdle.TLabel", background="#E8EEF7", foreground=MUTED, padding=(10, 4), font=("Segoe UI", 8, "bold"))
        style.configure("StatusRunning.TLabel", background="#DBEAFE", foreground=BLUE_DARK, padding=(10, 4), font=("Segoe UI", 8, "bold"))
        style.configure("StatusSuccess.TLabel", background=GREEN_BG, foreground=GREEN, padding=(10, 4), font=("Segoe UI", 8, "bold"))
        style.configure("StatusWarning.TLabel", background=AMBER_BG, foreground=AMBER, padding=(10, 4), font=("Segoe UI", 8, "bold"))
        style.configure("StatusError.TLabel", background=RED_BG, foreground=RED, padding=(10, 4), font=("Segoe UI", 8, "bold"))
        style.configure("StepPending.TLabel", background=CARD, foreground="#94A3B8", font=("Segoe UI", 9))
        style.configure("StepActive.TLabel", background=CARD, foreground=BLUE, font=("Segoe UI", 9, "bold"))
        style.configure("StepDone.TLabel", background=CARD, foreground=GREEN, font=("Segoe UI", 9, "bold"))

    def _build(self) -> None:
        self.root.title("AdBeam Person Parser")
        self.root.geometry("1040x780")
        self.root.minsize(880, 700)
        self.root.configure(background=BACKGROUND)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, style="Header.TFrame", padding=(28, 16))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="AdBeam Person Parser", style="HeaderTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="ИНН → проверка компании → поиск контактов → проверяемый Excel", style="HeaderSub.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(header, text="INN-FIRST PIPELINE", style="StatusRunning.TLabel").grid(row=0, column=1, rowspan=2, sticky="e")

        body = ttk.Frame(self.root, style="App.TFrame", padding=(24, 18, 24, 22))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(2, weight=1)

        input_card = ttk.Frame(body, style="Card.TFrame", padding=16)
        input_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
        input_card.columnconfigure(1, weight=1)
        ttk.Label(input_card, text="Входные данные", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(input_card, text="Выгрузка Контур с обязательными колонками «Наименование» и «ИНН»", style="Muted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 8))
        self._file_row(input_card, 2, "Выгрузка Контур", self.kontur_path, self._choose_kontur)
        self._file_row(input_card, 3, "Итоговый Excel", self.output_path, self._choose_output)

        roles = ttk.Frame(input_card, style="Inner.TFrame")
        roles.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 2))
        ttk.Label(roles, text="Целевые роли:", style="CardText.TLabel").pack(side="left", padx=(0, 12))
        marketing = ttk.Checkbutton(roles, text="Маркетинг", variable=self.marketing_enabled, onvalue="1", offvalue="0", style="Card.TCheckbutton")
        marketing.pack(side="left", padx=(0, 14))
        sales = ttk.Checkbutton(roles, text="Продажи / коммерческий директор", variable=self.sales_enabled, onvalue="1", offvalue="0", style="Card.TCheckbutton")
        sales.pack(side="left")
        self._editable_widgets.extend([marketing, sales])

        actions = ttk.Frame(input_card, style="Inner.TFrame")
        actions.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.inspect_button = ttk.Button(actions, text="Проверить файл", style="Secondary.TButton")
        self.inspect_button.pack(side="left")
        self.start_button = ttk.Button(actions, text="Запустить обработку", style="Accent.TButton")
        self.start_button.pack(side="left", padx=9)
        self.cancel_button = ttk.Button(actions, text="Остановить", style="Danger.TButton", state="disabled")
        self.cancel_button.pack(side="left")

        stages_card = ttk.Frame(body, style="Card.TFrame", padding=16)
        stages_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 12))
        ttk.Label(stages_card, text="Этапы обработки", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(stages_card, text="Текущий этап подсвечивается синим", style="Muted.TLabel").pack(anchor="w", pady=(2, 12))
        for index, step in enumerate(PIPELINE_STEPS):
            label = ttk.Label(stages_card, text=f"○  {index + 1}. {step}", style="StepPending.TLabel")
            label.pack(anchor="w", pady=4)
            self._step_labels.append(label)

        progress_card = ttk.Frame(body, style="Card.TFrame", padding=16)
        progress_card.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        progress_card.columnconfigure(0, weight=1)
        title_row = ttk.Frame(progress_card, style="Inner.TFrame")
        title_row.grid(row=0, column=0, sticky="ew")
        title_row.columnconfigure(1, weight=1)
        ttk.Label(title_row, text="Выполнение задачи", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.status_badge_label = ttk.Label(title_row, textvariable=self.status_badge, style="StatusIdle.TLabel")
        self.status_badge_label.grid(row=0, column=2, sticky="e")
        ttk.Label(progress_card, textvariable=self.status_text, style="CardText.TLabel").grid(row=1, column=0, sticky="w", pady=(7, 6))
        self.progress = ttk.Progressbar(progress_card, mode="determinate", style="App.Horizontal.TProgressbar")
        self.progress.grid(row=2, column=0, sticky="ew")

        metrics = ttk.Frame(progress_card, style="Inner.TFrame")
        metrics.grid(row=3, column=0, sticky="ew", pady=(9, 0))
        for column in range(4):
            metrics.columnconfigure(column, weight=1)
        self._metric(metrics, 0, "ОБРАБОТАНО", self.progress_text)
        self._metric(metrics, 1, "ПРОШЛО ВРЕМЕНИ", self.elapsed_text)
        self._metric(metrics, 2, "ОСТАЛОСЬ ПРИМЕРНО", self.eta_text)
        self._metric(metrics, 3, "СКОРОСТЬ", self.rate_text)
        ttk.Separator(progress_card).grid(row=4, column=0, sticky="ew", pady=(10, 7))
        ttk.Label(progress_card, textvariable=self.input_summary, style="Muted.TLabel", wraplength=920, justify="left").grid(row=5, column=0, sticky="ew")

        log_card = ttk.Frame(body, style="Card.TFrame", padding=14)
        log_card.grid(row=2, column=0, columnspan=2, sticky="nsew")
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(1, weight=1)
        ttk.Label(log_card, text="Журнал выполнения", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 7))
        self.log = Text(log_card, height=4, wrap="word", state="disabled", font=("Cascadia Mono", 9), background="#F8FAFC", foreground="#334155", borderwidth=0, padx=12, pady=8, insertbackground=TEXT, selectbackground="#BFDBFE")
        self.log.grid(row=1, column=0, sticky="nsew")

    def _file_row(self, parent, row: int, label: str, variable: StringVar, command: Callable[[], None]) -> None:
        ttk.Label(parent, text=label, style="CardText.TLabel", width=19).grid(row=row, column=0, sticky="w", pady=5)
        entry = ttk.Entry(parent, textvariable=variable, font=("Segoe UI", 10))
        entry.grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=3, ipady=4)
        button = ttk.Button(parent, text="Выбрать…", command=command, style="Secondary.TButton")
        button.grid(row=row, column=2, sticky="e", pady=3)
        self._editable_widgets.extend([entry, button])

    @staticmethod
    def _metric(parent, column: int, label: str, variable: StringVar) -> None:
        block = ttk.Frame(parent, style="Inner.TFrame")
        block.grid(row=0, column=column, sticky="w", padx=(0, 24))
        ttk.Label(block, textvariable=variable, style="MetricValue.TLabel").pack(anchor="w")
        ttk.Label(block, text=label, style="MetricLabel.TLabel").pack(anchor="w")

    def _choose_kontur(self) -> None:
        value = filedialog.askopenfilename(
            title="Выберите выгрузку Контур",
            filetypes=[("Excel", "*.xlsx *.xlsm")],
            parent=self.root,
        )
        if not value:
            return
        self.kontur_path.set(value)
        if not self.output_path.get().strip():
            source = Path(value)
            self.output_path.set(str(source.with_name(f"{source.stem}_parsed.xlsx")))

    def _choose_output(self) -> None:
        value = filedialog.asksaveasfilename(
            title="Куда сохранить результат",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            parent=self.root,
        )
        if value:
            self.output_path.set(value)
