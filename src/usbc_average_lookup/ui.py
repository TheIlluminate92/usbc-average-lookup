"""Small reusable desktop dialogs. All Tk operations run on the main thread."""

from __future__ import annotations

import json
import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from usbc_average_lookup.database import BowlerDatabase
from usbc_average_lookup.models import InputBowler
from usbc_average_lookup.services.database_exports import (
    AverageRule,
    average_type,
    export_database,
    export_preview,
    stored_averages,
    year_key,
)
from usbc_average_lookup.services.refresh import stored_candidates
from usbc_average_lookup.theme import BACKGROUND, INK, TEAL, color_table


def table(parent, columns, *, height=12):
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    view = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=height)
    color_table(view)
    for key, title, width in columns:
        view.heading(key, text=title)
        view.column(key, width=width, minwidth=60, anchor="w")
    view.grid(row=0, column=0, sticky="nsew")
    scroll = ttk.Scrollbar(frame, orient="vertical", command=view.yview)
    scroll.grid(row=0, column=1, sticky="ns")
    horizontal = ttk.Scrollbar(frame, orient="horizontal", command=view.xview)
    horizontal.grid(row=1, column=0, sticky="ew")
    view.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
    return view


def delete_saved_bowlers(parent, database, bowler_ids):
    """Confirm explicit local deletion, shared by the directory and details dialog."""
    try:
        rows = [database.get(bowler_id) for bowler_id in bowler_ids]
        if not rows:
            return False
        names = "\n".join(
            f"• {row['display_name']} — {row['membership_id'] or 'No USBC ID'}" for row in rows[:10]
        )
        if len(rows) > 10:
            names += f"\n…and {len(rows) - 10} more selected bowlers"
        if not messagebox.askyesno(
            "Delete selected bowlers?",
            f"Delete {len(rows)} saved bowler(s)?\n\n{names}\n\n"
            "Their saved averages and history will also be deleted from this app. "
            "This cannot be undone. BOWL.com records are not changed.",
            parent=parent,
            default="no",
        ):
            return False
        database.delete_bowlers([row["id"] for row in rows])
        return True
    except (ValueError, sqlite3.Error) as error:
        messagebox.showerror("Could not delete bowlers", str(error), parent=parent)
        return False


class Dialog(tk.Toplevel):
    def __init__(self, parent, title, geometry="520x280"):
        super().__init__(parent)
        self.title(title)
        self.configure(background=BACKGROUND)
        width, height = map(int, geometry.split("x"))
        self.geometry(
            f"{min(width, self.winfo_screenwidth() - 60)}x"
            f"{min(height, self.winfo_screenheight() - 120)}"
        )
        self.transient(parent)
        self.grab_set()
        self.choice = None
        self.content = ttk.Frame(self, padding=18)
        self.content.pack(fill="both", expand=True)
        self.bind("<Escape>", lambda _: self.destroy())

    def show(self):
        self.wait_window()
        return self.choice


class ChoiceDialog(Dialog):
    def __init__(self, parent, title, prompt, choices):
        super().__init__(parent, title, "560x230")
        ttk.Label(self.content, text=prompt, wraplength=510).pack(anchor="w", pady=10)
        self.value = tk.StringVar(value=choices[0])
        ttk.Combobox(self.content, values=choices, textvariable=self.value, state="readonly").pack(
            fill="x", pady=10
        )
        ttk.Button(
            self.content, text="Continue", command=self.accept, style="Primary.TButton"
        ).pack(side="right")
        ttk.Button(self.content, text="Cancel", command=self.destroy).pack(side="right", padx=8)

    def accept(self):
        self.choice = self.value.get()
        self.destroy()


class AddDialog(Dialog):
    def __init__(self, parent):
        super().__init__(parent, "Add bowler", "510x250")
        ttk.Label(self.content, text="Enter a name, USBC ID, or both.").pack(anchor="w")
        self.name = tk.StringVar()
        self.usbc = tk.StringVar()
        for label, variable in [("Bowler name", self.name), ("USBC ID (1234-567890)", self.usbc)]:
            ttk.Label(self.content, text=label).pack(anchor="w", pady=(12, 3))
            ttk.Entry(self.content, textvariable=variable).pack(fill="x")
        ttk.Button(
            self.content, text="Add to database", command=self.accept, style="Primary.TButton"
        ).pack(side="right", pady=14)
        ttk.Button(self.content, text="Cancel", command=self.destroy).pack(side="right", padx=8)
        self.bind("<Return>", lambda _: self.accept())

    def accept(self):
        if not self.name.get().strip() and not self.usbc.get().strip():
            return
        self.choice = InputBowler(self.name.get().strip(), self.usbc.get().strip())
        self.destroy()


class DetailDialog(Dialog):
    def __init__(self, parent, database: BowlerDatabase, bowler_id: int):
        super().__init__(parent, "Bowler details and history", "940x650")
        self.database, self.bowler_id = database, bowler_id
        footer = ttk.Frame(self.content)
        footer.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(footer, text="Close", command=self.destroy).pack(side="right")
        ttk.Button(
            footer, text="Delete bowler…", command=self.delete_bowler, style="Danger.TButton"
        ).pack(side="left")
        row = database.get(bowler_id)
        ttk.Label(self.content, text=row["display_name"], style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            self.content,
            text=f"{row['membership_id'] or 'USBC ID not resolved'}  |  "
            f"{row['status']}  |  {row['note']}",
            wraplength=880,
        ).pack(anchor="w", pady=8)
        notebook = ttk.Notebook(self.content)
        notebook.pack(fill="both", expand=True)
        profile = ttk.Frame(notebook, padding=12)
        notebook.add(profile, text="Member")
        text = tk.Text(
            profile,
            wrap="word",
            font=("Segoe UI", 10),
            height=12,
            background="white",
            foreground=INK,
            selectbackground=TEAL,
            selectforeground="white",
            relief="flat",
            padx=12,
            pady=10,
        )
        text.pack(fill="both", expand=True)
        fields = [
            ("USBC ID", "membership_id"),
            ("BOWL.com member ID", "member_id"),
            ("First name", "first_name"),
            ("Middle initial", "middle_initial"),
            ("Last name", "last_name"),
            ("Gender", "gender"),
            ("Active", "active"),
            ("Association", "association"),
            ("State", "association_state"),
            ("Membership from", "membership_from"),
            ("Membership through", "membership_thru"),
            ("Product", "product"),
            ("Last refreshed", "refreshed_at"),
        ]
        text.insert(
            "end",
            "\n".join(
                f"{label}: {row[key] if row[key] is not None else '—'}" for label, key in fields
            ),
        )
        text.insert(
            "end", "\n\nMembership flags\n" + json.dumps(json.loads(row["flags_json"]), indent=2)
        )
        text.configure(state="disabled")
        for title, history in [("Stored averages", False), ("Revision history", True)]:
            frame = ttk.Frame(notebook, padding=10)
            notebook.add(frame, text=title)
            view = table(
                frame,
                [
                    ("year", "Year (ending)", 115),
                    ("type", "Type", 150),
                    ("hand", "Hand", 75),
                    ("average", "Average", 85),
                    ("games", "Games", 75),
                    ("seen", "Observed", 230),
                ],
            )
            for average in database.averages(bowler_id, history=history):
                view.insert(
                    "",
                    "end",
                    values=(
                        average["year"],
                        average_type(average),
                        average["hand"],
                        average["average"],
                        average["games"],
                        average.get("observed_at", average.get("last_seen_at", "")),
                    ),
                )
        raw_frame = ttk.Frame(notebook, padding=10)
        league_frame = ttk.Frame(notebook, padding=10)
        notebook.add(league_frame, text="League activity / history")
        leagues = table(
            league_frame,
            [
                ("league", "League", 190),
                ("year", "Year", 65),
                ("average", "Average", 80),
                ("games", "Games", 65),
                ("type", "Type", 90),
                ("center", "Center", 140),
                ("seen", "Observed", 190),
            ],
        )
        for activity in database.league_averages(bowler_id, history=True):
            leagues.insert(
                "",
                "end",
                values=(
                    activity["league_name"],
                    activity["year"],
                    activity["average"],
                    activity["games"],
                    average_type(activity),
                    activity["center_name"],
                    activity["last_seen_at"],
                ),
            )
        notebook.add(raw_frame, text="Saved API data")
        raw = tk.Text(
            raw_frame,
            wrap="none",
            font=("Consolas", 10),
            background="white",
            foreground=INK,
            selectbackground=TEAL,
            selectforeground="white",
            relief="flat",
            padx=10,
            pady=8,
        )
        raw.pack(fill="both", expand=True)
        raw.insert(
            "end",
            json.dumps(
                [
                    {**snap, "payload_json": json.loads(snap["payload_json"])}
                    for snap in database.snapshots(bowler_id)
                ],
                indent=2,
                ensure_ascii=False,
            ),
        )
        raw.configure(state="disabled")
        if row["status"] != "Refreshed":
            resolve = ttk.Frame(notebook, padding=12)
            notebook.add(resolve, text="Resolve identity")
            self.name = tk.StringVar(value=row["display_name"])
            self.usbc = tk.StringVar(value=row["membership_id"] or "")
            for label, variable in [("Name", self.name), ("USBC ID", self.usbc)]:
                ttk.Label(resolve, text=label).pack(anchor="w")
                ttk.Entry(resolve, textvariable=variable).pack(fill="x", pady=(2, 8))
            search_filters = ttk.Frame(resolve)
            search_filters.pack(fill="x", pady=(0, 8))
            self.search_state = tk.StringVar(value=row["search_state"])
            self.search_zip = tk.StringVar(value=row["search_zip"])
            for label, variable in [
                ("State (optional)", self.search_state),
                ("ZIP / 5-mile radius (optional)", self.search_zip),
            ]:
                ttk.Label(search_filters, text=label).pack(side="left", padx=(0, 5))
                ttk.Entry(search_filters, textvariable=variable, width=9).pack(
                    side="left", padx=(0, 12)
                )
            ttk.Button(
                search_filters,
                text="Search again",
                command=self.search_again,
                style="Primary.TButton",
            ).pack(side="right")
            self.match_query = tk.StringVar()
            self.match_active = tk.StringVar(value="Any")
            match_filters = ttk.Frame(resolve)
            match_filters.pack(fill="x", pady=(0, 6))
            ttk.Label(match_filters, text="Filter returned matches").pack(side="left", padx=(0, 8))
            ttk.Entry(match_filters, textvariable=self.match_query).pack(
                side="left", fill="x", expand=True
            )
            ttk.Combobox(
                match_filters,
                textvariable=self.match_active,
                values=["Any", "Active", "Inactive"],
                state="readonly",
                width=10,
            ).pack(side="left", padx=8)
            ttk.Button(
                resolve, text="Save identity", command=self.save_identity, style="Primary.TButton"
            ).pack(side="bottom", anchor="e", pady=8)
            self.matches = stored_candidates(row)
            self.match_table = table(
                resolve,
                [
                    ("name", "Member", 190),
                    ("id", "USBC ID", 130),
                    ("assn", "Association", 230),
                    ("state", "State", 65),
                    ("active", "Active", 65),
                ],
                height=6,
            )
            self.match_query.trace_add("write", self.render_matches)
            self.match_active.trace_add("write", self.render_matches)
            self.render_matches()
            self.match_table.bind("<<TreeviewSelect>>", self.pick_member)
            notebook.select(resolve)

    def render_matches(self, *_args):
        self.match_table.delete(*self.match_table.get_children())
        terms = self.match_query.get().casefold().split()
        active = self.match_active.get()
        for index, member in enumerate(self.matches):
            searchable = (
                f"{member.display_name} {member.prefix}-{member.suffix} "
                f"{member.association} {member.association_state}".casefold()
            )
            if all(term in searchable for term in terms) and (
                active == "Any" or member.active == (active == "Active")
            ):
                self.match_table.insert(
                    "",
                    "end",
                    iid=str(index),
                    tags=("ready" if member.active else "muted",),
                    values=(
                        member.display_name,
                        f"{member.prefix}-{member.suffix}",
                        member.association,
                        member.association_state,
                        "Yes" if member.active else "No",
                    ),
                )

    def delete_bowler(self):
        if delete_saved_bowlers(self, self.database, [self.bowler_id]):
            self.choice = "deleted"
            self.destroy()

    def search_again(self):
        if self.database.get(self.bowler_id)["refreshed_at"]:
            messagebox.showinfo(
                "Verified member",
                "This bowler already has a verified USBC ID. "
                "Use Save identity to refresh that member.",
                parent=self,
            )
            return
        self.usbc.set("")
        self.save_identity()

    def pick_member(self, _event=None):
        selected = self.match_table.selection()
        if selected:
            member = self.matches[int(selected[0])]
            self.name.set(member.display_name)
            self.usbc.set(f"{member.prefix}-{member.suffix}")

    def save_identity(self):
        try:
            self.database.set_identity(
                self.bowler_id,
                self.name.get(),
                self.usbc.get(),
                search_state=self.search_state.get(),
                search_zip=self.search_zip.get(),
            )
        except ValueError as error:
            messagebox.showerror("Could not save identity", str(error), parent=self)
            return
        self.choice = self.bowler_id
        self.destroy()


class ExportDialog(Dialog):
    def __init__(self, parent, database: BowlerDatabase, scopes: dict[str, list[int]]):
        super().__init__(parent, "Export bowlers", "1030x700")
        self.minsize(
            min(880, self.winfo_screenwidth() - 60), min(520, self.winfo_screenheight() - 120)
        )
        self.database, self.scopes = database, scopes
        self.manual: dict[int, int] = {}
        self.preview: list[dict] = []
        ttk.Label(self.content, text="Export stored averages", style="Title.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            self.content,
            text="Choose which stored average becomes Book Average and "
            "Book Games. Years are season-ending years.",
        ).pack(anchor="w", pady=(4, 12))
        all_averages = [
            a
            for bowler_id in dict.fromkeys(i for ids in scopes.values() for i in ids)
            for a in database.averages(bowler_id) + database.league_averages(bowler_id)
        ]
        years = sorted({a["year"] for a in all_averages}, key=year_key, reverse=True)
        hands = sorted({a["hand"] for a in all_averages if a["hand"]})
        source_bar = ttk.Frame(self.content)
        source_bar.pack(fill="x", pady=(0, 10))
        ttk.Label(source_bar, text="Average source").pack(side="left", padx=(0, 10))
        self.source = tk.StringVar(value="Composite")
        ttk.Combobox(
            source_bar,
            textvariable=self.source,
            state="readonly",
            values=["Composite", "League", "Adjusted league"],
        ).pack(side="left")
        self.source.trace_add("write", self.source_changed)
        options = ttk.Frame(self.content)
        options.pack(fill="x")
        defaults = [
            ("Bowlers", "scope", list(scopes), next(iter(scopes))),
            ("Format", "format", ["BTM26+", "CSV", "XLSX", "JSON"], "BTM26+"),
            ("Rule", "mode", ["Latest", "Highest", "Specific year", "Manual"], "Latest"),
            ("Type", "kind", ["Standard", "Sport", "Challenge", "Any"], "Standard"),
            ("Year", "year", years, years[0] if years else ""),
            ("Hand", "hand", ["Any", "(Unspecified)", *hands], "Any"),
            ("Missing average", "missing", ["Error", "Blank", "Skip"], "Error"),
        ]
        self.variables = {}
        self.boxes = {}
        for index, (label, key, choices, value) in enumerate(defaults):
            column, row = index % 4, (index // 4) * 2
            ttk.Label(options, text=label).grid(row=row, column=column, sticky="w", padx=5)
            variable = tk.StringVar(value=value)
            self.variables[key] = variable
            box = ttk.Combobox(options, values=choices, textvariable=variable, state="readonly")
            box.grid(row=row + 1, column=column, sticky="ew", padx=5, pady=(3, 10))
            options.columnconfigure(column, weight=1)
            variable.trace_add("write", self.update_preview)
            self.boxes[key] = box
        ttk.Label(options, text="Minimum games").grid(row=2, column=3, sticky="w", padx=5)
        self.minimum = tk.StringVar(value="1")
        ttk.Spinbox(options, from_=0, to=99999, textvariable=self.minimum).grid(
            row=3, column=3, sticky="ew", padx=5
        )
        self.minimum.trace_add("write", self.update_preview)
        self.summary = ttk.Label(self.content, text="")
        self.summary.pack(anchor="w", pady=8)
        # Reserve the footer before packing the expanding table. At Windows display
        # scaling or smaller window sizes the table must shrink, never the controls.
        buttons = ttk.Frame(self.content)
        buttons.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        self.save_button = ttk.Button(
            buttons, text="Save export…", command=self.save, style="Primary.TButton"
        )
        self.save_button.pack(side="right", padx=8)
        self.export_help = ttk.Label(self.content, text="", wraplength=850)
        self.export_help.pack(side="bottom", anchor="w", pady=(8, 0))
        self.view = table(
            self.content,
            [
                ("name", "Bowler", 200),
                ("id", "USBC ID", 130),
                ("year", "Year", 80),
                ("type", "Type", 110),
                ("hand", "Hand", 70),
                ("avg", "Book Average", 110),
                ("games", "Book Games", 100),
            ],
        )
        self.view.bind("<Double-1>", self.choose_average)
        self.update_preview()

    def rule(self):
        values = {key: variable.get() for key, variable in self.variables.items()}
        return AverageRule(
            values["mode"],
            values["year"],
            values["kind"],
            int(self.minimum.get()),
            "" if values["hand"] == "(Unspecified)" else values["hand"],
            self.source.get(),
        )

    def update_preview(self, *_args):
        if not hasattr(self, "view"):
            return
        self.view.delete(*self.view.get_children())
        try:
            rule = self.rule()
            self.preview = export_preview(
                self.database, self.scopes[self.variables["scope"].get()], rule, self.manual
            )
        except ValueError as error:
            self.summary.configure(text=str(error))
            self.save_button.configure(state="disabled")
            return
        self.boxes["year"].configure(
            state="readonly" if rule.mode == "Specific year" else "disabled"
        )
        for key in ("kind", "hand"):
            self.boxes[key].configure(state="disabled" if rule.mode == "Manual" else "readonly")
        for item in self.preview:
            b, a = item["bowler"], item["average"]
            self.view.insert(
                "",
                "end",
                iid=str(b["id"]),
                tags=("ready" if a else "attention",),
                values=(
                    b["display_name"],
                    b["membership_id"] or "",
                    a["year"] if a else "—",
                    average_type(a) if a else "No match",
                    a["hand"] if a else "",
                    a["average"] if a else "",
                    a["games"] if a else "",
                ),
            )
        missing = sum(item["average"] is None for item in self.preview)
        stale = sum(item["bowler"]["status"] != "Refreshed" for item in self.preview)
        self.summary.configure(
            text=f"{len(self.preview)} bowlers • {missing} without a matching "
            f"average • {stale} needing refresh/review"
        )
        allowed = bool(self.preview) and not (
            missing and self.variables["missing"].get() == "Error"
        )
        self.save_button.configure(state="normal" if allowed else "disabled")
        self.export_help.configure(
            text=(
                "To export, set Missing average to Blank or Skip, or resolve the missing averages."
                if missing and self.variables["missing"].get() == "Error"
                else "Manual: double-click a bowler to choose an average. "
                "In BTM, skip 1 header line; "
                "map Middle Initial to Middle Name. Assign teams in BTM after import."
            )
        )

    def source_changed(self, *_args):
        self.manual.clear()
        self.update_preview()

    def choose_average(self, _event=None):
        if self.variables["mode"].get() != "Manual" or not self.view.selection():
            return
        bowler_id = int(self.view.selection()[0])
        rows = stored_averages(self.database, bowler_id, self.source.get())
        options = {
            f"{a['year']} • {average_type(a)} • {a['hand'] or 'unspecified hand'} • "
            f"{a['average']} average / {a['games']} games {a.get('league_name', '')} "
            f"[#{a['id']}]": a["id"]
            for a in rows
        }
        if not options:
            return
        choice = ChoiceDialog(
            self, "Choose stored average", "Select the record to export.", list(options)
        ).show()
        if choice:
            self.manual[bowler_id] = options[choice]
            self.update_preview()

    def save(self):
        format = self.variables["format"].get()
        extension = {"XLSX": ".xlsx", "JSON": ".json"}.get(format, ".csv")
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Save bowler export",
            initialdir=self.database.setting("export_directory") or None,
            initialfile="BTM26-bowlers.csv" if format == "BTM26+" else "bowlers" + extension,
            defaultextension=extension,
            filetypes=[(format, "*" + extension)],
        )
        if not filename:
            return
        try:
            self.database.validate_destination(Path(filename))
            count = export_database(
                Path(filename), self.preview, format=format, missing=self.variables["missing"].get()
            )
            self.database.set_setting("export_directory", str(Path(filename).parent))
        except (ValueError, OSError, sqlite3.Error) as error:
            messagebox.showerror("Could not save export", str(error), parent=self)
            return
        self.choice = (count, filename)
        self.destroy()
