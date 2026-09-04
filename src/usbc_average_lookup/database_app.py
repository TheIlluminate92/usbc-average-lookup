"""Persistent bowler directory, with background work delivered through a main-thread queue."""

from __future__ import annotations

import sqlite3
import tkinter as tk
from collections import Counter
from multiprocessing import freeze_support
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
from tkinter import filedialog, messagebox, ttk

from usbc_average_lookup.database import BowlerDatabase
from usbc_average_lookup.services.auth import (
    AuthSession,
    AuthState,
    SignInCancelledError,
    WebViewAuthenticator,
)
from usbc_average_lookup.services.bowl_api import HttpBowlApi
from usbc_average_lookup.services.input_parser import parse_input_file, workbook_sheet_names
from usbc_average_lookup.services.refresh import refresh_bowlers
from usbc_average_lookup.ui import (
    AddDialog,
    ChoiceDialog,
    DetailDialog,
    ExportDialog,
    delete_saved_bowlers,
    table,
)


class AverageLookupApp(tk.Tk):
    def __init__(self, database: BowlerDatabase | None = None):
        super().__init__()
        self.database = database or BowlerDatabase()
        self.title("Average Assistant")
        try:
            self.geometry(self.database.setting("geometry", "1120x720"))
        except tk.TclError:
            self.geometry("1120x720")
        self.minsize(920, 580)
        self.authenticator = WebViewAuthenticator()
        self.auth_session = AuthSession(AuthState.SIGNED_OUT)
        self.events = Queue()
        self.cancel = Event()
        self.signin_cancel = Event()
        self.busy = False
        self.signing_in = False
        self.closing = False
        self.auth_generation = 0
        self._style()
        self._build()
        self.render()
        self.after(100, self.poll_events)
        self.protocol("WM_DELETE_WINDOW", self.close_app)

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background="#F3F5F7", foreground="#183044")
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("TButton", padding=(10, 7))
        style.configure("Treeview", background="white", fieldbackground="white", rowheight=32)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), padding=7)
        style.map(
            "Treeview", background=[("selected", "#194E70")], foreground=[("selected", "white")]
        )
        self.configure(background="#F3F5F7")

    def _build(self):
        page = ttk.Frame(self, padding=20)
        page.pack(fill="both", expand=True)
        header = ttk.Frame(page)
        header.pack(fill="x", pady=(0, 14))
        ttk.Label(header, text="Average Assistant", style="Title.TLabel").pack(side="left")
        self.sign_button = ttk.Button(header, text="Sign in", command=self.toggle_sign_in)
        self.sign_button.pack(side="right")
        self.auth_label = ttk.Label(header, text="BOWL.com • Not signed in")
        self.auth_label.pack(side="right", padx=14)
        actions = ttk.Frame(page)
        actions.pack(fill="x", pady=(0, 14))
        self.add_button = ttk.Button(actions, text="Add bowler", command=self.add_bowler)
        self.add_button.pack(side="left")
        self.import_button = ttk.Button(actions, text="Import…", command=self.import_file)
        self.import_button.pack(side="left", padx=6)
        self.refresh_buttons = {}
        for scope in ("Selected", "Visible", "All"):
            button = ttk.Button(
                actions,
                text=f"Refresh {scope.lower()}",
                command=lambda value=scope: self.start_refresh(value),
            )
            button.pack(side="left", padx=(0, 6))
            self.refresh_buttons[scope] = button
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.cancel_refresh)
        self.cancel_button.pack(side="left")
        self.export_button = ttk.Button(actions, text="Export…", command=self.export)
        self.export_button.pack(side="right")
        self.backup_button = ttk.Button(actions, text="Back up…", command=self.backup)
        self.backup_button.pack(side="right", padx=6)
        filters = ttk.Frame(page)
        filters.pack(fill="x", pady=(0, 10))
        ttk.Label(filters, text="Search bowlers").pack(side="left", padx=(0, 10))
        self.query = tk.StringVar(value=self.database.setting("query"))
        search = ttk.Entry(filters, textvariable=self.query)
        search.pack(side="left", fill="x", expand=True)
        self.filter = tk.StringVar(value=self.database.setting("filter", "All"))
        if self.filter.get() not in ("All", "Active", "Inactive", "Needs attention"):
            self.filter.set("All")
        ttk.Combobox(
            filters,
            textvariable=self.filter,
            values=["All", "Active", "Inactive", "Needs attention"],
            state="readonly",
            width=18,
        ).pack(side="left", padx=8)
        self.count = ttk.Label(filters, text="")
        self.count.pack(side="right")
        footer = ttk.Frame(page)
        footer.pack(side="bottom", fill="x", pady=(12, 0))
        self.status = ttk.Label(
            footer,
            text="Add or import bowlers. Saved records stay here between runs.",
            wraplength=550,
        )
        self.status.pack(side="left")
        self.details_button = ttk.Button(footer, text="Details / history", command=self.details)
        self.details_button.pack(side="right")
        self.delete_button = ttk.Button(
            footer, text="Delete selected…", command=self.delete_selected
        )
        self.delete_button.pack(side="right", padx=6)
        self.progress = ttk.Progressbar(page, mode="determinate")
        self.progress.pack(side="bottom", fill="x", pady=(10, 0))
        self.view = table(
            page,
            [
                ("name", "Bowler", 220),
                ("id", "USBC ID", 130),
                ("association", "Association", 230),
                ("active", "Active", 70),
                ("refreshed", "Last refreshed", 170),
                ("status", "Status", 160),
            ],
        )
        self.sort_column = self.database.setting("sort", "name")
        self.sort_reverse = self.database.setting("sort_reverse") == "True"
        for column in self.view["columns"]:
            self.view.heading(column, command=lambda value=column: self.sort(value))
        self.query.trace_add("write", lambda *_: self.render())
        self.filter.trace_add("write", lambda *_: self.render())
        self.view.bind("<<TreeviewSelect>>", lambda _: self.update_actions())
        self.view.bind("<Double-1>", lambda _: self.details())
        self.view.bind("<Return>", lambda _: self.details())
        self.view.bind("<Delete>", lambda _: self.delete_selected())
        self.bind("<Control-f>", lambda _: search.focus_set())

    def sort(self, column):
        self.sort_reverse = not self.sort_reverse if self.sort_column == column else False
        self.sort_column = column
        self.render()

    def render(self):
        selected = self.view.selection()
        yview = self.view.yview()[0]
        self.rows = self.database.list_bowlers(self.query.get(), self.filter.get())
        columns = {
            "name": "display_name",
            "id": "membership_id",
            "association": "association",
            "active": "active",
            "refreshed": "refreshed_at",
            "status": "status",
        }
        self.rows.sort(
            key=lambda row: str(
                row[columns.get(self.sort_column, "display_name")] or ""
            ).casefold(),
            reverse=self.sort_reverse,
        )
        self.view.delete(*self.view.get_children())
        for row in self.rows:
            self.view.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    row["display_name"],
                    row["membership_id"] or "—",
                    row["association"],
                    "—" if row["active"] is None else "Yes" if row["active"] else "No",
                    (row["refreshed_at"] or "Never")[:19].replace("T", " "),
                    row["status"],
                ),
            )
        self.view.selection_set([item for item in selected if self.view.exists(item)])
        self.view.yview_moveto(yview)
        self.count.configure(text=f"{len(self.rows)} shown")
        self.update_actions()

    def scopes(self):
        return {
            "Selected": [int(item) for item in self.view.selection()],
            "Visible": [row["id"] for row in self.rows],
            "All": [row["id"] for row in self.database.list_bowlers()],
        }

    def update_actions(self):
        scopes = self.scopes()
        signed_in = self.auth_session.state == AuthState.SIGNED_IN
        for scope, button in self.refresh_buttons.items():
            button.configure(
                state="normal"
                if scopes[scope] and signed_in and not self.busy and not self.closing
                else "disabled"
            )
        for button in (self.add_button, self.import_button):
            button.configure(state="disabled" if self.busy or self.closing else "normal")
        self.export_button.configure(
            state="normal" if scopes["All"] and not self.busy and not self.closing else "disabled"
        )
        self.details_button.configure(
            state="normal" if scopes["Selected"] and not self.busy else "disabled"
        )
        self.delete_button.configure(
            state="normal"
            if scopes["Selected"] and not self.busy and not self.closing
            else "disabled"
        )
        self.cancel_button.configure(state="normal" if self.busy else "disabled")
        self.sign_button.configure(
            text="Cancel sign-in" if self.signing_in else "Sign out" if signed_in else "Sign in"
        )
        self.sign_button.configure(state="disabled" if self.closing else "normal")
        self.auth_label.configure(text=f"BOWL.com • {self.auth_session.state.value}")

    def add_bowler(self):
        bowler = AddDialog(self).show()
        if bowler:
            self.import_rows([bowler])

    def import_rows(self, inputs):
        try:
            result = self.database.import_bowlers(inputs)
            added, reused = list(result.added), list(result.reused)
            for bowler in result.conflicts:
                matches = self.database.list_bowlers(bowler.name)
                options = {
                    f"Reuse {row['display_name']} ({row['membership_id'] or 'unresolved'}) "
                    f"[#{row['id']}]": row["id"]
                    for row in matches
                }
                options["Add a different person with this name"] = None
                choice = ChoiceDialog(
                    self,
                    "Possible duplicate",
                    f"{bowler.name} has no USBC ID in this import. Choose the saved person "
                    "or add a separate record.",
                    list(options),
                ).show()
                if choice and options[choice] is None:
                    added.extend(self.database.import_bowlers([bowler], allow_same_name=True).added)
                elif choice:
                    reused.append(options[choice])
            self.query.set("")
            self.filter.set("All")
            self.render()
            self.view.selection_set([str(i) for i in dict.fromkeys(added + reused)])
            self.status.configure(
                text=f"Added {len(added)} • Reused {len(reused)} • "
                "Select Refresh to fetch BOWL.com data."
            )
        except (ValueError, OSError, sqlite3.Error) as error:
            messagebox.showerror("Could not import bowlers", str(error), parent=self)

    def import_file(self):
        filename = filedialog.askopenfilename(
            parent=self,
            title="Import bowlers",
            filetypes=[("Bowler files", "*.csv *.xlsx *.txt *.tsv *.json"), ("All files", "*.*")],
        )
        if not filename:
            return
        try:
            path = Path(filename)
            sheet = None
            if path.suffix.casefold() == ".xlsx":
                sheets = workbook_sheet_names(path)
                if len(sheets) > 1:
                    sheet = ChoiceDialog(
                        self, "Choose worksheet", "Which sheet contains bowlers?", sheets
                    ).show()
                    if sheet is None:
                        return
            self.import_rows(parse_input_file(path, sheet))
        except (ValueError, OSError) as error:
            messagebox.showerror("Could not read import", str(error), parent=self)

    def details(self):
        if self.busy or not self.view.selection():
            return
        changed = DetailDialog(self, self.database, int(self.view.selection()[0])).show()
        self.render()
        if changed == "deleted":
            self.status.configure(text="Bowler deleted from the saved database.")
        elif changed:
            if self.auth_session.state == AuthState.SIGNED_IN:
                self.start_refresh("Selected", bowler_ids=[changed])
            else:
                self.status.configure(
                    text="Identity/search saved. Sign in and refresh to search BOWL.com."
                )

    def delete_selected(self):
        if self.busy or self.closing:
            return
        ids = self.scopes()["Selected"]
        if delete_saved_bowlers(self, self.database, ids):
            self.render()
            self.status.configure(text=f"Deleted {len(ids)} saved bowler(s).")

    def toggle_sign_in(self):
        if self.signing_in or self.auth_session.state == AuthState.SIGNED_IN:
            self.signin_cancel.set()
            self.auth_generation += 1
            self.cancel.set()
            self.auth_session = AuthSession(AuthState.SIGNED_OUT)
            Thread(target=self.authenticator.sign_out, daemon=True).start()
            self.status.configure(text="Sign-in cancelled." if self.signing_in else "Signed out.")
            self.update_actions()
            return
        self.signing_in = True
        self.signin_cancel = Event()
        self.auth_generation += 1
        generation = self.auth_generation
        self.status.configure(text="Complete sign-in in the private BOWL.com window.")
        self.update_actions()

        def worker():
            try:
                session = self.authenticator.sign_in(self.signin_cancel)
                self.events.put(("auth", generation, session))
            except SignInCancelledError:
                self.events.put(("auth_cancel", generation, None))
            except Exception:
                self.events.put(
                    (
                        "auth_error",
                        generation,
                        "Could not sign in. Check your connection and WebView2 installation.",
                    )
                )
            finally:
                self.events.put(("auth_done", generation, None))

        Thread(target=worker, daemon=True).start()

    def start_refresh(self, scope, *, bowler_ids=None):
        ids = self.scopes()[scope] if bowler_ids is None else bowler_ids
        if self.busy or not ids or self.auth_session.state != AuthState.SIGNED_IN:
            return
        self.busy = True
        self.cancel = Event()
        token = self.auth_session.bearer_token
        self.progress.configure(maximum=len(ids), value=0)
        self.status.configure(text=f"Refreshing {len(ids)} bowlers…")
        self.update_actions()

        def worker():
            try:
                results = refresh_bowlers(
                    self.database,
                    lambda: HttpBowlApi(lambda: token, cancel=self.cancel),
                    ids,
                    cancel=self.cancel,
                    progress=lambda event: self.events.put(("progress", event)),
                )
                self.events.put(("refresh_done", results))
            except Exception:
                self.events.put(("refresh_error", "Refresh stopped. Saved data remains available."))

        Thread(target=worker, daemon=True).start()

    def cancel_refresh(self):
        self.cancel.set()
        self.status.configure(text="Cancelling… waiting for the current requests to finish.")

    def poll_events(self):
        changed = False
        try:
            while True:
                kind, *values = self.events.get_nowait()
                if kind.startswith("auth"):
                    generation, value = values
                    if kind == "auth_done":
                        self.signing_in = False
                    if generation != self.auth_generation:
                        continue
                    if kind == "auth":
                        self.auth_session = value
                        self.status.configure(text="Signed in to BOWL.com.")
                    elif kind == "auth_cancel":
                        self.status.configure(text="Sign-in cancelled.")
                    elif kind == "auth_error":
                        self.status.configure(text=value)
                elif kind == "progress":
                    event = values[0]
                    self.progress.configure(value=event.completed)
                    self.status.configure(
                        text=f"{event.completed} / {event.total} • {event.status}"
                    )
                    if event.status == "Sign in again":
                        self.auth_session = AuthSession(AuthState.EXPIRED)
                    changed = True
                elif kind == "refresh_done":
                    self.busy = False
                    counts = Counter(event.status for event in values[0])
                    prefix = "Stopped" if self.cancel.is_set() else "Refresh complete"
                    self.status.configure(
                        text=prefix
                        + " • "
                        + ", ".join(f"{count} {status.lower()}" for status, count in counts.items())
                    )
                    changed = True
                elif kind == "refresh_error":
                    self.busy = False
                    self.status.configure(text=values[0])
        except Empty:
            pass
        if changed:
            self.render()
        self.update_actions()
        if self.closing and not self.busy and not self.signing_in:
            self.destroy()
            return
        self.after(100, self.poll_events)

    def export(self):
        scopes = {key: value for key, value in self.scopes().items() if value}
        result = ExportDialog(self, self.database, scopes).show()
        if result:
            count, path = result
            self.status.configure(text=f"Exported {count} bowlers to {Path(path).name}")

    def backup(self):
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Back up bowler database",
            initialfile="bowler-database-backup.sqlite3",
            defaultextension=".sqlite3",
            filetypes=[("SQLite database", "*.sqlite3")],
        )
        if filename:
            try:
                self.database.backup(Path(filename))
                self.status.configure(text="Database backup saved.")
            except (ValueError, OSError, sqlite3.Error) as error:
                messagebox.showerror("Could not save backup", str(error), parent=self)

    def close_app(self):
        if self.closing:
            return
        for key, value in [
            ("geometry", self.geometry()),
            ("query", self.query.get()),
            ("filter", self.filter.get()),
            ("sort", self.sort_column),
            ("sort_reverse", str(self.sort_reverse)),
        ]:
            self.database.set_setting(key, value)
        self.closing = True
        self.signin_cancel.set()
        self.auth_generation += 1
        self.auth_session = AuthSession(AuthState.SIGNED_OUT)
        self.cancel.set()
        Thread(target=self.authenticator.sign_out, daemon=True).start()
        self.status.configure(text="Closing… finishing current requests safely.")
        self.update_actions()


def main():
    freeze_support()
    try:
        database = BowlerDatabase()
    except (OSError, sqlite3.Error, ValueError) as error:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Could not open bowler database",
            f"{error}\n\nYour database has not been replaced. Restore a backup "
            "or use a compatible app version.",
            parent=root,
        )
        root.destroy()
        return
    AverageLookupApp(database).mainloop()
