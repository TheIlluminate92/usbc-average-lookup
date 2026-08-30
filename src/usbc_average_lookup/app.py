from __future__ import annotations

import tkinter as tk
from collections import Counter
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from usbc_average_lookup.models import InputBowler, LookupResult, LookupStatus
from usbc_average_lookup.services.exports import export_json
from usbc_average_lookup.services.input_parser import parse_input_file


class AverageLookupApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("USBC Average Lookup")
        self.geometry("900x620")
        self.minsize(760, 520)
        self.results: list[LookupResult] = []
        self.bowlers: list[InputBowler] = []
        self._build_ui()

    def _build_ui(self) -> None:
        container = ttk.Frame(self, padding=16)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        auth = ttk.Frame(container)
        auth.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.auth_status = ttk.Label(auth, text="Ready for names")
        self.auth_status.pack(side=tk.LEFT)

        ttk.Label(container, text="Bowler file").grid(
            row=1, column=0, sticky="w"
        )
        input_area = ttk.Frame(container)
        input_area.grid(row=2, column=0, sticky="nsew", pady=(4, 12))
        input_area.columnconfigure(0, weight=1)
        self.file_label = ttk.Label(input_area, text="No file selected")
        self.file_label.grid(row=0, column=0, sticky="w")
        controls = ttk.Frame(input_area)
        controls.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        ttk.Button(controls, text="Choose file", command=self._choose_file).pack(fill=tk.X)
        ttk.Button(controls, text="Look up averages", command=self._lookup).pack(fill=tk.X)

        results_frame = ttk.LabelFrame(container, text="Results", padding=8)
        results_frame.grid(row=3, column=0, sticky="nsew")
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(
            results_frame,
            columns=("name", "average", "status", "notes"),
            show="headings",
        )
        for column, label, width in (
            ("name", "Bowler", 220),
            ("average", "Average", 80),
            ("status", "Status", 130),
            ("notes", "Notes", 360),
        ):
            self.table.heading(column, text=label)
            self.table.column(column, width=width, anchor="w")
        self.table.grid(row=0, column=0, sticky="nsew")

        footer = ttk.Frame(container)
        footer.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        self.summary = ttk.Label(footer, text="Processed: 0")
        self.summary.pack(side=tk.LEFT)
        ttk.Button(footer, text="Save results", command=self._save_results).pack(
            side=tk.RIGHT
        )

    def _choose_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose bowler file",
            filetypes=(("Bowler files", "*.csv *.txt"), ("All files", "*.*")),
        )
        if not selected:
            return
        try:
            self.bowlers = parse_input_file(Path(selected))
        except (OSError, UnicodeError, ValueError) as error:
            messagebox.showerror("Could not read file", str(error))
            return
        self.file_label.configure(text=f"{Path(selected).name} — {len(self.bowlers)} bowlers")
        self.auth_status.configure(text="Ready to look up averages")

    def _lookup(self) -> None:
        if not self.bowlers:
            messagebox.showwarning("No file", "Choose a bowler file first.")
            return
        self.results = [
            LookupResult(
                input_name=bowler.name,
                status=LookupStatus.API_ERROR,
                membership_id=bowler.membership_id,
                note="This starter version is not connected to BOWL.com yet",
            )
            for bowler in self.bowlers
        ]
        self._render_results()

    def _render_results(self) -> None:
        self.table.delete(*self.table.get_children())
        for result in self.results:
            self.table.insert(
                "",
                tk.END,
                values=(
                    result.input_name,
                    result.average if result.average is not None else "—",
                    result.status.value,
                    result.note,
                ),
            )
        counts = Counter(result.status for result in self.results)
        parts = [f"Processed: {len(self.results)}"]
        parts.extend(f"{status.value}: {counts[status]}" for status in LookupStatus if counts[status])
        self.summary.configure(text="  |  ".join(parts))

    def _save_results(self) -> None:
        if not self.results:
            messagebox.showwarning("No results", "Look up a bowler file first.")
            return
        selected = filedialog.asksaveasfilename(
            title="Save results",
            defaultextension=".json",
            initialfile="bowler-averages.json",
            filetypes=(("JSON file", "*.json"),),
        )
        if selected:
            export_json(Path(selected), self.results)
            messagebox.showinfo("Results saved", f"Saved {len(self.results)} bowlers.")


def main() -> None:
    AverageLookupApp().mainloop()
