from __future__ import annotations

from tkinter import Tk, ttk

from lead_enrichment.gui.controller import AppController
from lead_enrichment.gui.main_view import MainView


def main() -> None:
    root = Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    view = MainView(root)
    AppController(root, view)
    root.mainloop()


if __name__ == "__main__":
    main()
