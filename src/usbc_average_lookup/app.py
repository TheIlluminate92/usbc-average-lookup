from __future__ import annotations

import tkinter as tk
from collections import Counter
from collections.abc import Callable
from multiprocessing import freeze_support
from pathlib import Path
from threading import Thread
from tkinter import filedialog, messagebox, ttk

from usbc_average_lookup.models import InputBowler, LookupResult, LookupStatus, Member
from usbc_average_lookup.registration_ui import RegistrationDesk
from usbc_average_lookup.services.auth import (
    AuthSession,
    AuthState,
    SignInCancelledError,
    WebViewAuthenticator,
    clear_legacy_sign_in_data,
)
from usbc_average_lookup.services.bowl_api import HttpBowlApi
from usbc_average_lookup.services.exports import ExportSubset, export_results, select_results
from usbc_average_lookup.services.input_parser import (
    parse_input_file,
    workbook_sheet_names,
)
from usbc_average_lookup.services.lookup import (
    look_up_all,
    look_up_bowler,
    resolve_selected_member,
)
from usbc_average_lookup.services.registration import (
    RegistrationDataError,
    RegistrationStore,
)

COLORS = {
    "navy": "#0C2744",
    "navy_soft": "#153252",
    "canvas": "#13191F",
    "surface": "#1D252C",
    "surface_raised": "#263139",
    "line": "#3A4852",
    "text": "#EDF4FA",
    "muted": "#9FB0BF",
    "wood": "#E6A260",
    "green": "#72D6A5",
    "green_bg": "#183B2D",
    "red": "#FF9999",
    "red_bg": "#472525",
    "gold": "#F1C76D",
    "gold_bg": "#40341C",
}


class AverageLookupApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Bowling Manager")
        self.geometry("1080x720")
        self.minsize(820, 580)
        self.configure(background=COLORS["canvas"])
        self.results: list[LookupResult] = []
        self.bowlers: list[InputBowler] = []
        self.selected_path: Path | None = None
        self.auth_session = AuthSession(AuthState.SIGNED_OUT)
        self.signing_in = False
        clear_legacy_sign_in_data()
        self.authenticator = WebViewAuthenticator()
        self.api: HttpBowlApi | None = None
        self.registration_data_error = ""
        try:
            self.registration_store: RegistrationStore | None = RegistrationStore()
        except RegistrationDataError as error:
            self.registration_store = None
            self.registration_data_error = str(error)
        self._configure_style()
        self._build_ui()
        self._render_results()
        if self.registration_data_error:
            self.after(
                0,
                messagebox.showerror,
                "Registration data needs attention",
                self.registration_data_error
                + "\n\nThe file was left unchanged. Registration is disabled until it is repaired.",
            )
        self.protocol("WM_DELETE_WINDOW", self._close_app)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=COLORS["canvas"], foreground=COLORS["text"])
        style.configure("App.TFrame", background=COLORS["canvas"])
        style.configure("Surface.TFrame", background=COLORS["surface"])
        style.configure(
            "Title.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["text"],
            font=("Segoe UI", 24, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["muted"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Surface.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["text"],
        )
        style.configure(
            "Muted.TLabel",
            background=COLORS["canvas"],
            foreground=COLORS["muted"],
        )
        style.configure(
            "Status.TLabel",
            background=COLORS["green_bg"],
            foreground=COLORS["green"],
            padding=(12, 7),
        )
        style.configure(
            "TButton",
            background=COLORS["surface_raised"],
            foreground=COLORS["text"],
            bordercolor=COLORS["line"],
            padding=(12, 8),
        )
        style.map("TButton", background=[("active", COLORS["navy_soft"])])
        style.configure(
            "Primary.TButton",
            background=COLORS["navy_soft"],
            foreground=COLORS["text"],
            bordercolor=COLORS["navy_soft"],
        )
        style.map("Primary.TButton", background=[("active", COLORS["navy"])])
        style.configure(
            "Warm.TButton",
            background=COLORS["wood"],
            foreground="#1B120A",
            bordercolor=COLORS["wood"],
        )
        style.map("Warm.TButton", background=[("active", "#C98447")])
        style.configure(
            "TCombobox",
            fieldbackground=COLORS["surface_raised"],
            background=COLORS["surface_raised"],
            foreground=COLORS["text"],
            arrowcolor=COLORS["text"],
            bordercolor=COLORS["line"],
            lightcolor=COLORS["line"],
            darkcolor=COLORS["line"],
        )
        style.map(
            "TCombobox",
            fieldbackground=[
                ("readonly", COLORS["surface_raised"]),
                ("disabled", COLORS["surface"]),
            ],
            foreground=[
                ("readonly", COLORS["text"]),
                ("disabled", COLORS["muted"]),
            ],
            selectbackground=[("readonly", COLORS["navy_soft"])],
            selectforeground=[("readonly", COLORS["text"])],
        )
        style.configure(
            "TNotebook",
            background=COLORS["canvas"],
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            background=COLORS["surface"],
            foreground=COLORS["muted"],
            padding=(18, 9),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", COLORS["navy_soft"])],
            foreground=[("selected", COLORS["text"])],
        )
        style.configure(
            "Treeview",
            background=COLORS["surface"],
            fieldbackground=COLORS["surface"],
            foreground=COLORS["text"],
            bordercolor=COLORS["line"],
            rowheight=34,
        )
        style.map(
            "Treeview",
            background=[("selected", COLORS["navy_soft"])],
            foreground=[("selected", COLORS["text"])],
        )
        style.configure(
            "Treeview.Heading",
            background=COLORS["surface_raised"],
            foreground=COLORS["muted"],
            bordercolor=COLORS["line"],
            padding=(8, 8),
        )
        style.map("Treeview.Heading", background=[("active", COLORS["surface_raised"])])
        style.configure(
            "TEntry",
            fieldbackground=COLORS["surface_raised"],
            foreground=COLORS["text"],
            insertcolor=COLORS["text"],
        )

    def _build_ui(self) -> None:
        header = ttk.Frame(self, style="Surface.TFrame", padding=(28, 20, 28, 16))
        header.pack(fill=tk.X)
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Bowling Manager", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="Leagues, tournaments, teams, and verified averages.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.auth_status = ttk.Label(header, text="Not signed in", style="Status.TLabel")
        self.auth_status.grid(row=0, column=1, rowspan=2, padx=(18, 0), sticky="e")
        self.sign_in_button = ttk.Button(
            header,
            text="Sign in to BOWL.com",
            command=self._start_sign_in,
            style="Primary.TButton",
        )
        self.sign_in_button.grid(row=0, column=2, rowspan=2, padx=(10, 0), sticky="e")
        self.sign_out_button = ttk.Button(
            header,
            text="Sign out",
            command=self._sign_out,
            state=tk.DISABLED,
        )
        self.sign_out_button.grid(row=0, column=3, rowspan=2, padx=(8, 0), sticky="e")

        self.workspace = ttk.Notebook(self)
        self.workspace.pack(fill=tk.BOTH, expand=True)
        lookup_workspace = ttk.Frame(self.workspace, style="App.TFrame")
        registration_workspace = ttk.Frame(self.workspace, style="App.TFrame")
        self.workspace.add(registration_workspace, text="Registration Desk")
        self.workspace.add(lookup_workspace, text="Average lookup")

        main = ttk.Frame(
            lookup_workspace, style="App.TFrame", padding=(28, 20, 28, 24)
        )
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)

        filebar = ttk.Frame(main, style="Surface.TFrame", padding=14)
        filebar.grid(row=0, column=0, sticky="ew")
        filebar.columnconfigure(0, weight=1)
        self.file_label = ttk.Label(
            filebar,
            text="No roster selected",
            style="Surface.TLabel",
            font=("Segoe UI", 10, "bold"),
        )
        self.file_label.grid(row=0, column=0, sticky="w")
        self.file_detail = ttk.Label(
            filebar,
            text="CSV, TSV, text, JSON, or Excel",
            style="Subtitle.TLabel",
        )
        self.file_detail.grid(row=1, column=0, sticky="w", pady=(2, 0))
        controls = ttk.Frame(filebar, style="Surface.TFrame")
        controls.grid(row=0, column=1, rowspan=2, sticky="e", padx=(14, 0))
        self.single_button = ttk.Button(
            controls,
            text="Single lookup",
            command=self._start_single_lookup,
            state=tk.DISABLED,
        )
        self.single_button.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(controls, text="Choose roster", command=self._choose_file).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        self.clear_button = ttk.Button(
            controls, text="Clear results", command=self._clear_results, state=tk.DISABLED
        )
        self.clear_button.pack(side=tk.LEFT, padx=(0, 8))
        self.lookup_button = ttk.Button(
            controls,
            text="Look up averages",
            command=self._start_lookup,
            state=tk.DISABLED,
            style="Primary.TButton",
        )
        self.lookup_button.pack(side=tk.LEFT)

        self.summary = ttk.Label(main, text="No current results", style="Muted.TLabel")
        self.summary.grid(row=1, column=0, sticky="ew", pady=(16, 8))

        self.notebook = ttk.Notebook(main)
        self.notebook.grid(row=2, column=0, sticky="nsew")
        self.notebook.bind("<<NotebookTabChanged>>", lambda _event: self._update_fix_button())
        self.all_tab = ttk.Frame(self.notebook, style="Surface.TFrame")
        self.fixes_tab = ttk.Frame(self.notebook, style="Surface.TFrame")
        self.notebook.add(self.all_tab, text="All results")
        self.notebook.add(self.fixes_tab, text="Fixes needed (0)")
        self.all_table = self._make_result_table(self.all_tab)
        self.fixes_table = self._make_result_table(self.fixes_tab)

        footer = ttk.Frame(main, style="App.TFrame")
        footer.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        self.help_label = ttk.Label(
            footer,
            text="Double-click a highlighted row to fix it.",
            style="Muted.TLabel",
        )
        self.help_label.pack(side=tk.LEFT)
        self.save_button = ttk.Button(
            footer,
            text="Save results",
            command=self._save_results,
            state=tk.DISABLED,
            style="Warm.TButton",
        )
        self.save_button.pack(side=tk.RIGHT)
        self.fix_button = ttk.Button(
            footer,
            text="Fix selected",
            command=self._fix_selected,
            state=tk.DISABLED,
        )
        self.fix_button.pack(side=tk.RIGHT, padx=(0, 8))

        self.registration_desk = RegistrationDesk(
            registration_workspace,
            self.registration_store,
            lambda: self.api,
            self._set_status,
        )
        self.registration_desk.pack(fill=tk.BOTH, expand=True)

    def _set_status(self, text: str) -> None:
        self.auth_status.configure(text=text)

    def _make_result_table(self, parent: ttk.Frame) -> ttk.Treeview:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        table = ttk.Treeview(
            parent,
            columns=("name", "member_id", "average", "status", "notes"),
            show="headings",
        )
        for column, label, width, stretch in (
            ("name", "Name", 205, True),
            ("member_id", "Member ID", 125, False),
            ("average", "Average", 75, False),
            ("status", "Status", 125, False),
            ("notes", "Notes", 310, True),
        ):
            table.heading(column, text=label)
            table.column(column, width=width, minwidth=70, stretch=stretch, anchor="w")
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=table.yview)
        table.configure(yscrollcommand=scrollbar.set)
        table.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        table.tag_configure("ready", foreground=COLORS["green"])
        table.tag_configure("issue", foreground=COLORS["red"])
        table.tag_configure("inactive", foreground=COLORS["gold"])
        table.bind("<Double-1>", lambda _event: self._fix_selected())
        table.bind("<<TreeviewSelect>>", lambda _event: self._update_fix_button())
        return table

    def _start_sign_in(self) -> None:
        self.authenticator.sign_out()
        self.signing_in = True
        self.sign_in_button.configure(state=tk.DISABLED)
        self.sign_out_button.configure(state=tk.DISABLED)
        self.auth_status.configure(text="Finish signing in…")
        Thread(target=self._sign_in_worker, daemon=True).start()

    def _sign_in_worker(self) -> None:
        try:
            session = self.authenticator.sign_in()
        except SignInCancelledError:
            self.after(0, self._sign_in_cancelled)
            return
        except Exception as error:
            self.after(0, self._sign_in_failed, str(error))
            return
        self.after(0, self._signed_in, session)

    def _signed_in(self, session: AuthSession) -> None:
        self.signing_in = False
        self.auth_session = session
        self.api = HttpBowlApi(lambda: self.auth_session.bearer_token)
        self.auth_status.configure(text="Signed in — ready")
        self.sign_in_button.configure(text="Sign in again", state=tk.NORMAL)
        self.sign_out_button.configure(state=tk.NORMAL)
        self._update_action_states()
        self.registration_desk.refresh_auth_state()

    def _sign_in_failed(self, message: str) -> None:
        self._restore_sign_in_controls()
        messagebox.showerror("Could not sign in", message)

    def _sign_in_cancelled(self) -> None:
        self._restore_sign_in_controls()

    def _restore_sign_in_controls(self) -> None:
        self.signing_in = False
        signed_in = self.api is not None
        self.auth_status.configure(
            text="Signed in — ready" if signed_in else "Not signed in"
        )
        self.sign_in_button.configure(
            text="Sign in again" if signed_in else "Sign in to BOWL.com",
            state=tk.NORMAL,
        )
        self.sign_out_button.configure(state=tk.NORMAL if signed_in else tk.DISABLED)
        self._update_action_states()
        self.registration_desk.refresh_auth_state()

    def _sign_out(self) -> None:
        self.authenticator.sign_out()
        self.auth_session = AuthSession(AuthState.SIGNED_OUT)
        self.api = None
        self.auth_status.configure(text="Not signed in")
        self.sign_in_button.configure(text="Sign in to BOWL.com", state=tk.NORMAL)
        self.sign_out_button.configure(state=tk.DISABLED)
        self._update_action_states()
        self.registration_desk.refresh_auth_state()

    def _close_app(self) -> None:
        self.registration_desk.close()
        self.authenticator.sign_out()
        self.auth_session = AuthSession(AuthState.SIGNED_OUT)
        self.api = None
        self.destroy()

    def _choose_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose bowler roster",
            filetypes=(
                ("Supported rosters", "*.csv *.tsv *.txt *.json *.xlsx"),
                ("Excel workbook", "*.xlsx"),
                ("JSON file", "*.json"),
                ("Delimited text", "*.csv *.tsv *.txt"),
                ("All files", "*.*"),
            ),
        )
        if not selected:
            return
        path = Path(selected)
        sheet_name = None
        try:
            if path.suffix.casefold() == ".xlsx":
                sheets = workbook_sheet_names(path)
                if len(sheets) > 1:
                    sheet_name = SheetPickerDialog(self, sheets).show()
                    if sheet_name is None:
                        return
            bowlers = parse_input_file(path, sheet_name)
            if not bowlers:
                raise ValueError("The selected file does not contain any bowlers")
        except (OSError, UnicodeError, ValueError) as error:
            messagebox.showerror("Could not read roster", str(error))
            return
        self.selected_path = path
        self.bowlers = bowlers
        self.results = []
        self.file_label.configure(text=path.name)
        detail = f"{len(bowlers)} bowlers loaded"
        if sheet_name:
            detail += f" from {sheet_name}"
        self.file_detail.configure(text=detail)
        self._render_results()
        self._update_action_states()

    def _start_lookup(self) -> None:
        if not self.bowlers:
            messagebox.showwarning("No roster", "Choose a bowler roster first.")
            return
        if self.api is None:
            messagebox.showwarning("Sign in needed", "Sign in to BOWL.com first.")
            return
        self.lookup_button.configure(state=tk.DISABLED)
        self.auth_status.configure(text="Looking up averages…")
        Thread(target=self._lookup_worker, daemon=True).start()

    def _lookup_worker(self) -> None:
        assert self.api is not None
        results = look_up_all(self.api, self.bowlers)
        self.after(0, self._lookup_finished, results)

    def _lookup_finished(self, results: list[LookupResult]) -> None:
        self.results = results
        self._render_results()
        self.auth_status.configure(text="Lookup complete")
        self._update_action_states()

    def _start_single_lookup(self) -> None:
        if self.api is None:
            messagebox.showwarning("Sign in needed", "Sign in to BOWL.com first.")
            return
        if self.bowlers and len(self.bowlers) != len(self.results):
            replace = messagebox.askyesno(
                "Roster not processed",
                "The selected roster has not been looked up. Start a separate single lookup?",
            )
            if not replace:
                return
            self.bowlers = []
            self.results = []
            self.selected_path = None
        bowler = SingleLookupDialog(self).show()
        if bowler is None:
            return
        self.single_button.configure(state=tk.DISABLED)
        self.auth_status.configure(text="Looking up one bowler…")
        Thread(target=self._single_lookup_worker, args=(bowler,), daemon=True).start()

    def _single_lookup_worker(self, bowler: InputBowler) -> None:
        assert self.api is not None
        result = look_up_bowler(self.api, bowler)
        self.after(0, self._single_lookup_finished, bowler, result)

    def _single_lookup_finished(
        self, bowler: InputBowler, result: LookupResult
    ) -> None:
        self.bowlers.append(bowler)
        self.results.append(result)
        if self.selected_path is None:
            self.file_label.configure(text="Manual lookups")
            self.file_detail.configure(text=f"{len(self.bowlers)} bowlers added individually")
        else:
            self.file_detail.configure(
                text=f"{len(self.bowlers)} total bowlers, including manual lookups"
            )
        self._render_results()
        self.auth_status.configure(text="Single lookup complete")
        self._update_action_states()
        if result.needs_attention:
            index = len(self.results) - 1
            self.notebook.select(self.fixes_tab)
            self.fixes_table.selection_set(str(index))
            self.fixes_table.focus(str(index))
            self.fixes_table.see(str(index))

    def _clear_results(self) -> None:
        self.results = []
        self._render_results()
        self.auth_status.configure(
            text="Signed in — ready" if self.api is not None else "Not signed in"
        )
        self._update_action_states()

    def _render_results(self) -> None:
        for table in (self.all_table, self.fixes_table):
            table.delete(*table.get_children())
        for index, result in enumerate(self.results):
            values = (
                result.input_name,
                result.membership_id or "—",
                result.average if result.average is not None else "—",
                result.status.value,
                result.note,
            )
            tag = self._result_tag(result)
            self.all_table.insert("", tk.END, iid=str(index), values=values, tags=(tag,))
            if result.needs_attention:
                self.fixes_table.insert(
                    "", tk.END, iid=str(index), values=values, tags=(tag,)
                )
        issue_count = sum(result.needs_attention for result in self.results)
        self.notebook.tab(self.fixes_tab, text=f"Fixes needed ({issue_count})")
        if not self.results:
            self.summary.configure(text="No current results")
        else:
            counts = Counter(result.status for result in self.results)
            ready = counts[LookupStatus.FOUND]
            inactive = sum(result.confirmed_inactive for result in self.results)
            self.summary.configure(
                text=(
                    f"{len(self.results)} processed   •   {ready} ready   •   "
                    f"{issue_count} need attention   •   {inactive} inactive"
                )
            )
        self._update_fix_button()

    @staticmethod
    def _result_tag(result: LookupResult) -> str:
        if result.status is LookupStatus.FOUND:
            return "ready"
        if result.status is LookupStatus.INACTIVE_MEMBER:
            return "inactive"
        return "issue"

    def _active_table(self) -> ttk.Treeview:
        return self.fixes_table if self.notebook.select() == str(self.fixes_tab) else self.all_table

    def _selected_result_index(self) -> int | None:
        table = self._active_table()
        selected = table.selection()
        return int(selected[0]) if selected else None

    def _update_fix_button(self) -> None:
        index = self._selected_result_index()
        can_fix = index is not None and self.results[index].needs_attention
        self.fix_button.configure(state=tk.NORMAL if can_fix else tk.DISABLED)

    def _fix_selected(self) -> None:
        index = self._selected_result_index()
        if index is None or not self.results[index].needs_attention:
            return
        IssueDialog(
            self,
            self.results[index],
            on_retry=lambda bowler, move_next: self._retry_issue(
                index, bowler, move_next
            ),
            on_member=lambda bowler, member, move_next: self._resolve_issue_member(
                index, bowler, member, move_next
            ),
        )

    def _retry_issue(
        self, index: int, bowler: InputBowler, move_next: bool
    ) -> None:
        if self.api is None:
            messagebox.showwarning("Sign in needed", "Sign in to BOWL.com first.")
            return
        self.auth_status.configure(text=f"Retrying {bowler.name}…")
        Thread(
            target=self._fix_worker,
            args=(index, bowler, None, move_next),
            daemon=True,
        ).start()

    def _resolve_issue_member(
        self, index: int, bowler: InputBowler, member: Member, move_next: bool
    ) -> None:
        if self.api is None:
            messagebox.showwarning("Sign in needed", "Sign in to BOWL.com first.")
            return
        self.auth_status.configure(text=f"Updating {bowler.name}…")
        Thread(
            target=self._fix_worker,
            args=(index, bowler, member, move_next),
            daemon=True,
        ).start()

    def _fix_worker(
        self,
        index: int,
        bowler: InputBowler,
        member: Member | None,
        move_next: bool,
    ) -> None:
        assert self.api is not None
        result = (
            resolve_selected_member(self.api, bowler, member)
            if member is not None
            else look_up_bowler(self.api, bowler)
        )
        self.after(0, self._fix_finished, index, bowler, result, move_next)

    def _fix_finished(
        self,
        index: int,
        bowler: InputBowler,
        result: LookupResult,
        move_next: bool,
    ) -> None:
        self.bowlers[index] = bowler
        self.results[index] = result
        self._close_issue_dialogs()
        self._render_results()
        self.auth_status.configure(text="Result updated")
        self._update_action_states()
        if move_next:
            self.after(100, self._open_next_issue, index)

    def _close_issue_dialogs(self) -> None:
        for child in self.winfo_children():
            if isinstance(child, IssueDialog):
                child.destroy()

    def _open_next_issue(self, after_index: int) -> None:
        unresolved = [
            index for index, result in enumerate(self.results) if result.needs_attention
        ]
        if not unresolved:
            messagebox.showinfo("All fixed", "No results currently need attention.")
            return
        index = next((item for item in unresolved if item > after_index), unresolved[0])
        self.notebook.select(self.fixes_tab)
        self.fixes_table.selection_set(str(index))
        self.fixes_table.focus(str(index))
        self.fixes_table.see(str(index))
        self._fix_selected()

    def _save_results(self) -> None:
        if not self.results:
            messagebox.showwarning("No results", "Look up a bowler roster first.")
            return
        choice = SaveDialog(self, self.results).show()
        if choice is None:
            return
        subset, extension = choice
        selected_count = len(select_results(self.results, subset))
        unresolved = sum(result.needs_attention for result in self.results)
        if subset is ExportSubset.FULL and unresolved:
            proceed = messagebox.askyesno(
                "Unresolved bowlers",
                f"{unresolved} bowlers still need attention. Save the full roster anyway?",
            )
            if not proceed:
                return
        filetypes = {
            ".json": (("JSON file", "*.json"),),
            ".xlsx": (("Excel workbook", "*.xlsx"),),
            ".csv": (("CSV file", "*.csv"),),
            ".tsv": (("Tab-separated text", "*.tsv"),),
            ".txt": (("Text file", "*.txt"),),
        }
        selected = filedialog.asksaveasfilename(
            title=f"Save {subset.value.lower()}",
            defaultextension=extension,
            initialfile=f"bowler-averages{extension}",
            filetypes=filetypes[extension],
        )
        if not selected:
            return
        try:
            exported = export_results(Path(selected), self.results, subset)
        except (OSError, ValueError) as error:
            messagebox.showerror("Could not save results", str(error))
            return
        messagebox.showinfo(
            "Results saved",
            f"Saved {exported or selected_count} bowlers to {Path(selected).name}.",
        )

    def _update_action_states(self) -> None:
        self.single_button.configure(
            state=tk.NORMAL if self.api is not None else tk.DISABLED
        )
        self.lookup_button.configure(
            state=tk.NORMAL if self.bowlers and self.api is not None else tk.DISABLED
        )
        has_results = bool(self.results)
        self.clear_button.configure(state=tk.NORMAL if has_results else tk.DISABLED)
        self.save_button.configure(state=tk.NORMAL if has_results else tk.DISABLED)


class SingleLookupDialog(tk.Toplevel):
    def __init__(self, parent: AverageLookupApp) -> None:
        super().__init__(parent)
        self.choice: InputBowler | None = None
        self.title("Single bowler lookup")
        self.geometry("520x310")
        self.resizable(False, False)
        self.configure(background=COLORS["canvas"])
        self.transient(parent)
        self.grab_set()
        self._build()

    def _build(self) -> None:
        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(1, weight=1)
        ttk.Label(
            content,
            text="Look up one bowler",
            style="Muted.TLabel",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            content,
            text="Enter a full name, a membership ID, or both.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 18))
        ttk.Label(content, text="Bowler name", style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 12), pady=6
        )
        self.name_var = tk.StringVar()
        name_entry = ttk.Entry(content, textvariable=self.name_var)
        name_entry.grid(row=2, column=1, sticky="ew", pady=6)
        ttk.Label(content, text="Member ID", style="Muted.TLabel").grid(
            row=3, column=0, sticky="w", padx=(0, 12), pady=6
        )
        self.id_var = tk.StringVar()
        ttk.Entry(content, textvariable=self.id_var).grid(
            row=3, column=1, sticky="ew", pady=6
        )
        ttk.Label(
            content,
            text="Example: 1234-567890",
            style="Muted.TLabel",
        ).grid(row=4, column=1, sticky="w")
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(28, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons,
            text="Look up bowler",
            command=self._accept,
            style="Primary.TButton",
        ).pack(side=tk.LEFT, padx=(8, 0))
        name_entry.focus_set()
        self.bind("<Return>", lambda _event: self._accept())

    def _accept(self) -> None:
        name = self.name_var.get().strip()
        membership_id = self.id_var.get().strip()
        if not name and not membership_id:
            messagebox.showwarning(
                "Name or ID needed",
                "Enter a bowler name or membership ID.",
                parent=self,
            )
            return
        self.choice = InputBowler(name, membership_id)
        self.destroy()

    def show(self) -> InputBowler | None:
        self.wait_window()
        return self.choice


class IssueDialog(tk.Toplevel):
    def __init__(
        self,
        parent: AverageLookupApp,
        result: LookupResult,
        on_retry: Callable[[InputBowler, bool], None],
        on_member: Callable[[InputBowler, Member, bool], None],
    ) -> None:
        super().__init__(parent)
        self.result = result
        self.on_retry = on_retry
        self.on_member = on_member
        self.title("Fix bowler")
        self.geometry("720x500")
        self.minsize(620, 430)
        self.configure(background=COLORS["canvas"])
        self.transient(parent)
        self.grab_set()
        self._build()

    def _build(self) -> None:
        content = ttk.Frame(self, style="App.TFrame", padding=22)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(4, weight=1)
        ttk.Label(
            content,
            text=f"Fix: {self.result.input_name}",
            style="Muted.TLabel",
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            content,
            text=self.result.note or self.result.status.value,
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 18))

        ttk.Label(content, text="Bowler name", style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 12), pady=5
        )
        self.name_var = tk.StringVar(value=self.result.input_name)
        ttk.Entry(content, textvariable=self.name_var).grid(row=2, column=1, sticky="ew", pady=5)
        ttk.Label(content, text="Member ID", style="Muted.TLabel").grid(
            row=3, column=0, sticky="w", padx=(0, 12), pady=5
        )
        self.id_var = tk.StringVar(value=self.result.membership_id)
        ttk.Entry(content, textvariable=self.id_var).grid(row=3, column=1, sticky="ew", pady=5)

        candidate_frame = ttk.Frame(content, style="Surface.TFrame", padding=8)
        candidate_frame.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(14, 12))
        candidate_frame.columnconfigure(0, weight=1)
        candidate_frame.rowconfigure(0, weight=1)
        self.candidate_table = ttk.Treeview(
            candidate_frame,
            columns=("name", "id", "association", "active"),
            show="headings",
            height=6,
        )
        for column, label, width in (
            ("name", "Member", 180),
            ("id", "Member ID", 120),
            ("association", "Association", 230),
            ("active", "Status", 75),
        ):
            self.candidate_table.heading(column, text=label)
            self.candidate_table.column(column, width=width, anchor="w")
        self.candidate_table.grid(row=0, column=0, sticky="nsew")
        for index, member in enumerate(self.result.candidates):
            association = ", ".join(
                part for part in (member.association, member.association_state) if part
            )
            self.candidate_table.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    member.display_name,
                    f"{member.prefix}-{member.suffix}",
                    association or "—",
                    "Active" if member.active else "Inactive",
                ),
            )
        if self.result.candidates:
            self.candidate_table.selection_set("0")
            self.candidate_table.focus("0")
        else:
            guidance = (
                "Enter a member ID above and retry"
                if self.result.status is LookupStatus.API_ERROR
                and not self.result.membership_id
                else "Edit above and retry"
            )
            self.candidate_table.insert(
                "", tk.END, values=("No selectable matches", "—", guidance, "—")
            )

        self.next_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            content,
            text="Open the next item that needs attention",
            variable=self.next_var,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(0, 12))
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=6, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Retry search", command=self._retry).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        self.use_button = ttk.Button(
            buttons,
            text="Use selected member",
            command=self._use_member,
            style="Primary.TButton",
            state=tk.NORMAL if self.result.candidates else tk.DISABLED,
        )
        self.use_button.pack(side=tk.LEFT, padx=(8, 0))

    def _bowler(self) -> InputBowler | None:
        name = self.name_var.get().strip()
        membership_id = self.id_var.get().strip()
        if not name and not membership_id:
            messagebox.showwarning(
                "Name or ID needed",
                "Enter the bowler's name or membership ID.",
                parent=self,
            )
            return None
        return InputBowler(name, membership_id)

    def _retry(self) -> None:
        bowler = self._bowler()
        if bowler:
            self.on_retry(bowler, self.next_var.get())

    def _use_member(self) -> None:
        bowler = self._bowler()
        selected = self.candidate_table.selection()
        if bowler is None or not selected:
            return
        member = self.result.candidates[int(selected[0])]
        chosen = InputBowler(bowler.name, f"{member.prefix}-{member.suffix}")
        self.on_member(chosen, member, self.next_var.get())


class SaveDialog(tk.Toplevel):
    FORMATS = {
        "JSON — complete structured details": ".json",
        "Excel — easy to review": ".xlsx",
        "CSV — works almost anywhere": ".csv",
        "Tab-separated text": ".tsv",
        "Plain text": ".txt",
    }

    def __init__(self, parent: AverageLookupApp, results: list[LookupResult]) -> None:
        super().__init__(parent)
        self.results = results
        self.choice: tuple[ExportSubset, str] | None = None
        self.title("Save results")
        self.geometry("500x320")
        self.resizable(False, False)
        self.configure(background=COLORS["canvas"])
        self.transient(parent)
        self.grab_set()
        self._build()

    def _build(self) -> None:
        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            content,
            text="Save results",
            style="Muted.TLabel",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w")
        ttk.Label(content, text="Which bowlers should be included?", style="Muted.TLabel").pack(
            anchor="w", pady=(18, 5)
        )
        self.subset_var = tk.StringVar(value=ExportSubset.FULL.value)
        subset_box = ttk.Combobox(
            content,
            textvariable=self.subset_var,
            values=[subset.value for subset in ExportSubset],
            state="readonly",
        )
        subset_box.pack(fill=tk.X)
        subset_box.bind("<<ComboboxSelected>>", lambda _event: self._update_count())
        ttk.Label(content, text="File type", style="Muted.TLabel").pack(
            anchor="w", pady=(14, 5)
        )
        self.format_var = tk.StringVar(value=next(iter(self.FORMATS)))
        ttk.Combobox(
            content,
            textvariable=self.format_var,
            values=list(self.FORMATS),
            state="readonly",
        ).pack(fill=tk.X)
        self.count_label = ttk.Label(content, text="", style="Muted.TLabel")
        self.count_label.pack(anchor="w", pady=(14, 0))
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.pack(side=tk.BOTTOM, anchor="e")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        self.continue_button = ttk.Button(
            buttons, text="Continue", command=self._accept, style="Warm.TButton"
        )
        self.continue_button.pack(side=tk.LEFT, padx=(8, 0))
        self._update_count()

    def _update_count(self) -> None:
        subset = ExportSubset(self.subset_var.get())
        count = len(select_results(self.results, subset))
        self.count_label.configure(text=f"{count} bowlers will be written")
        self.continue_button.configure(state=tk.NORMAL if count else tk.DISABLED)

    def _accept(self) -> None:
        self.choice = (
            ExportSubset(self.subset_var.get()),
            self.FORMATS[self.format_var.get()],
        )
        self.destroy()

    def show(self) -> tuple[ExportSubset, str] | None:
        self.wait_window()
        return self.choice


class SheetPickerDialog(tk.Toplevel):
    def __init__(self, parent: AverageLookupApp, sheets: list[str]) -> None:
        super().__init__(parent)
        self.choice: str | None = None
        self.title("Choose Excel sheet")
        self.geometry("420x210")
        self.resizable(False, False)
        self.configure(background=COLORS["canvas"])
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            content,
            text="This workbook has more than one roster.",
            style="Muted.TLabel",
        ).pack(anchor="w")
        self.value = tk.StringVar(value=sheets[0])
        ttk.Combobox(
            content,
            textvariable=self.value,
            values=sheets,
            state="readonly",
        ).pack(fill=tk.X, pady=(14, 18))
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.pack(anchor="e")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Use this sheet", command=self._accept).pack(
            side=tk.LEFT, padx=(8, 0)
        )

    def _accept(self) -> None:
        self.choice = self.value.get()
        self.destroy()

    def show(self) -> str | None:
        self.wait_window()
        return self.choice


def main() -> None:
    freeze_support()
    AverageLookupApp().mainloop()
