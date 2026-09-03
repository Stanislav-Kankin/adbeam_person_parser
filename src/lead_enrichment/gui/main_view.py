from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tkinter import StringVar, Text, Tk, filedialog, messagebox
from tkinter import ttk

from lead_enrichment.models import ContactRole


class MainView:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.kontur_path = StringVar()
        self.output_path = StringVar()
        self.marketing_enabled = StringVar(value="1")
        self.sales_enabled = StringVar(value="1")
        self.status_text = StringVar(value="Выберите выгрузку Контур с ИНН")
        self.progress_text = StringVar(value="0 / 0")
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

    def set_busy(self, busy: bool) -> None:
        normal = "disabled" if busy else "normal"
        self.inspect_button.configure(state=normal)
        self.start_button.configure(state=normal)
        self.cancel_button.configure(state="normal" if busy else "disabled")

    def set_status(self, value: str) -> None:
        self.status_text.set(value)
        self.append_log(value)

    def set_progress(self, completed: int, total: int) -> None:
        self.progress.configure(maximum=max(total, 1), value=completed)
        self.progress_text.set(f"{completed} / {total}")

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

    def _build(self) -> None:
        self.root.title("AdBeam Person Parser")
        self.root.geometry("920x650")
        self.root.minsize(760, 560)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        container = ttk.Frame(self.root, padding=18)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(1, weight=1)

        ttk.Label(
            container,
            text="Поиск B2B-контактов",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        ttk.Label(
            container,
            text="Контур с ИНН → официальный сайт → Excel-результат",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 16))

        self._file_row(container, 2, "Выгрузка Контур", self.kontur_path, self._choose_kontur)
        self._file_row(container, 3, "Итоговый Excel", self.output_path, self._choose_output)

        roles = ttk.LabelFrame(container, text="Целевые роли", padding=10)
        roles.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(12, 10))
        ttk.Checkbutton(
            roles,
            text="Маркетинг",
            variable=self.marketing_enabled,
            onvalue="1",
            offvalue="0",
        ).pack(side="left", padx=(0, 18))
        ttk.Checkbutton(
            roles,
            text="Продажи / коммерческий директор",
            variable=self.sales_enabled,
            onvalue="1",
            offvalue="0",
        ).pack(side="left")

        actions = ttk.Frame(container)
        actions.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        self.inspect_button = ttk.Button(actions, text="Проверить вход")
        self.inspect_button.pack(side="left")
        self.start_button = ttk.Button(actions, text="Запустить", style="Accent.TButton")
        self.start_button.pack(side="left", padx=8)
        self.cancel_button = ttk.Button(actions, text="Отменить", state="disabled")
        self.cancel_button.pack(side="left")

        progress_frame = ttk.Frame(container)
        progress_frame.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        progress_frame.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(progress_frame, mode="determinate")
        self.progress.grid(row=0, column=0, sticky="ew")
        ttk.Label(progress_frame, textvariable=self.progress_text, width=12).grid(
            row=0, column=1, padx=(10, 0)
        )
        ttk.Label(container, textvariable=self.status_text).grid(
            row=7, column=0, columnspan=3, sticky="w"
        )

        self.log = Text(
            container,
            height=14,
            wrap="word",
            state="disabled",
            font=("Consolas", 10),
        )
        self.log.grid(row=8, column=0, columnspan=3, sticky="nsew", pady=(10, 0))
        container.rowconfigure(8, weight=1)

    def _file_row(
        self,
        parent,
        row: int,
        label: str,
        variable: StringVar,
        command: Callable[[], None],
    ) -> None:
        ttk.Label(parent, text=label, width=22).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=1, sticky="ew", padx=(0, 8), pady=4
        )
        ttk.Button(parent, text="Выбрать…", command=command).grid(
            row=row, column=2, sticky="e", pady=4
        )

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
