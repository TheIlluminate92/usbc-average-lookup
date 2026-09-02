from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from queue import Queue
from threading import Thread
from tkinter import messagebox, simpledialog, ttk

from usbc_average_lookup.models import InputBowler, LookupResult, Member
from usbc_average_lookup.services.bowl_api import BowlApi
from usbc_average_lookup.services.input_parser import parse_input_text
from usbc_average_lookup.services.lookup import look_up_bowler, resolve_selected_member
from usbc_average_lookup.services.registration import (
    Competition,
    CompetitionKind,
    RegistrationDataError,
    RegistrationStore,
    RegistrationView,
)

LookupTask = tuple[BowlApi, str, InputBowler]


class RegistrationDesk(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        store: RegistrationStore | None,
        api_provider: Callable[[], BowlApi | None],
        status_callback: Callable[[str], None],
    ) -> None:
        super().__init__(parent, style="App.TFrame", padding=(28, 20, 28, 24))
        self.store = store
        self.api_provider = api_provider
        self.status_callback = status_callback
        self.competition_by_label: dict[str, Competition] = {}
        self.team_by_label: dict[str, str] = {}
        self.lookup_results: dict[str, LookupResult] = {}
        self.lookup_queue: Queue[LookupTask | None] = Queue()
        self.bulk_pending: set[str] = set()
        self.competition_var = tk.StringVar()
        self.team_filter_var = tk.StringVar(value="All teams")
        self.name_var = tk.StringVar()
        self.member_id_var = tk.StringVar()
        self.quick_team_var = tk.StringVar(value="Unassigned")
        self._build()
        self.refresh()
        for _worker_number in range(2):
            Thread(target=self._lookup_queue_worker, daemon=True).start()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        heading = ttk.Frame(self, style="App.TFrame")
        heading.grid(row=0, column=0, sticky="ew")
        heading.columnconfigure(0, weight=1)
        ttk.Label(
            heading,
            text="Registration Desk",
            style="Muted.TLabel",
            font=("Segoe UI", 20, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            heading,
            text="Fast staff entry first. Self-registration can be added later.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Button(
            heading,
            text="New league or tournament",
            command=self._new_competition,
            style="Primary.TButton",
        ).grid(row=0, column=1, rowspan=2, sticky="e")

        selector = ttk.Frame(self, style="Surface.TFrame", padding=14)
        selector.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        selector.columnconfigure(1, weight=1)
        ttk.Label(selector, text="Working on", style="Surface.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 10)
        )
        self.competition_box = ttk.Combobox(
            selector,
            textvariable=self.competition_var,
            state="readonly",
        )
        self.competition_box.grid(row=0, column=1, sticky="ew")
        self.competition_box.bind(
            "<<ComboboxSelected>>", lambda _event: self._competition_changed()
        )
        self.new_team_button = ttk.Button(selector, text="Add team", command=self._new_team)
        self.new_team_button.grid(row=0, column=2, padx=(10, 0))
        self.team_button = ttk.Button(
            selector, text="Register whole team", command=self._register_team
        )
        self.team_button.grid(row=0, column=3, padx=(8, 0))
        self.check_all_button = ttk.Button(
            selector, text="Check unverified", command=self._check_all
        )
        self.check_all_button.grid(row=0, column=4, padx=(8, 0))

        quick = ttk.Frame(self, style="Surface.TFrame", padding=14)
        quick.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        quick.columnconfigure(0, weight=2)
        quick.columnconfigure(1, weight=1)
        quick.columnconfigure(2, weight=1)
        ttk.Label(quick, text="Bowler name", style="Surface.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(quick, text="Member ID (optional)", style="Surface.TLabel").grid(
            row=0, column=1, sticky="w", padx=(10, 0)
        )
        ttk.Label(quick, text="Team", style="Surface.TLabel").grid(
            row=0, column=2, sticky="w", padx=(10, 0)
        )
        self.name_entry = ttk.Entry(quick, textvariable=self.name_var)
        self.name_entry.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        ttk.Entry(quick, textvariable=self.member_id_var).grid(
            row=1, column=1, sticky="ew", padx=(10, 0), pady=(5, 0)
        )
        self.quick_team_box = ttk.Combobox(
            quick, textvariable=self.quick_team_var, state="readonly"
        )
        self.quick_team_box.grid(row=1, column=2, sticky="ew", padx=(10, 0), pady=(5, 0))
        self.add_button = ttk.Button(
            quick,
            text="Add bowler",
            command=self._quick_add,
            style="Warm.TButton",
        )
        self.add_button.grid(row=1, column=3, padx=(10, 0), pady=(5, 0))
        self.name_entry.bind("<Return>", lambda _event: self._quick_add())

        table_frame = ttk.Frame(self, style="Surface.TFrame")
        table_frame.grid(row=3, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(1, weight=1)
        table_header = ttk.Frame(table_frame, style="Surface.TFrame", padding=(12, 9))
        table_header.grid(row=0, column=0, columnspan=2, sticky="ew")
        table_header.columnconfigure(0, weight=1)
        self.counter_label = ttk.Label(
            table_header, text="No registrations", style="Surface.TLabel"
        )
        self.counter_label.grid(row=0, column=0, sticky="w")
        ttk.Label(table_header, text="Show", style="Surface.TLabel").grid(
            row=0, column=1, padx=(12, 6)
        )
        self.team_filter_box = ttk.Combobox(
            table_header,
            textvariable=self.team_filter_var,
            state="readonly",
            width=22,
        )
        self.team_filter_box.grid(row=0, column=2)
        self.team_filter_box.bind("<<ComboboxSelected>>", lambda _event: self._render_rows())

        self.table = ttk.Treeview(
            table_frame,
            columns=("name", "member_id", "team", "average", "status", "notes"),
            show="headings",
        )
        for column, label, width, stretch in (
            ("name", "Bowler", 190, True),
            ("member_id", "Member ID", 115, False),
            ("team", "Team", 155, True),
            ("average", "Average", 70, False),
            ("status", "Status", 155, False),
            ("notes", "Notes", 245, True),
        ):
            self.table.heading(column, text=label)
            self.table.column(column, width=width, minwidth=65, stretch=stretch, anchor="w")
        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.table.tag_configure("ready", foreground="#72D6A5")
        self.table.tag_configure("attention", foreground="#F1C76D")
        self.table.tag_configure("error", foreground="#FF9999")
        self.table.tag_configure("withdrawn", foreground="#9FB0BF")
        self.table.bind("<<TreeviewSelect>>", lambda _event: self._update_row_actions())
        self.table.bind("<Double-1>", lambda _event: self._review_selected())

        footer = ttk.Frame(self, style="App.TFrame")
        footer.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(
            footer,
            text="Registrations save automatically. BOWL.com checks never block entry.",
            style="Muted.TLabel",
        ).pack(side=tk.LEFT)
        self.withdraw_button = ttk.Button(
            footer, text="Withdraw selected", command=self._toggle_withdrawn, state=tk.DISABLED
        )
        self.withdraw_button.pack(side=tk.RIGHT)
        self.edit_button = ttk.Button(
            footer, text="Edit selected", command=self._edit_selected, state=tk.DISABLED
        )
        self.edit_button.pack(side=tk.RIGHT, padx=(0, 8))
        self.review_button = ttk.Button(
            footer, text="Review / recheck", command=self._review_selected, state=tk.DISABLED
        )
        self.review_button.pack(side=tk.RIGHT, padx=(0, 8))

    def refresh(self) -> None:
        if self.store is None:
            self.competition_box.configure(values=(), state=tk.DISABLED)
            self._set_competition_actions(False)
            self.counter_label.configure(text="Registration data could not be opened")
            return
        competitions = sorted(
            self.store.competitions,
            key=lambda item: (item.kind.value, item.season, item.name.casefold()),
            reverse=True,
        )
        self.competition_by_label = {item.display_name: item for item in competitions}
        labels = list(self.competition_by_label)
        self.competition_box.configure(values=labels, state="readonly")
        if self.competition_var.get() not in self.competition_by_label:
            self.competition_var.set(labels[0] if labels else "")
        self._competition_changed()

    def refresh_auth_state(self) -> None:
        self._update_actions()

    def _current_competition(self) -> Competition | None:
        return self.competition_by_label.get(self.competition_var.get())

    def _competition_changed(self) -> None:
        competition = self._current_competition()
        enabled = competition is not None and self.store is not None
        self._set_competition_actions(enabled)
        self._refresh_teams()
        self._render_rows()
        if enabled:
            self.name_entry.focus_set()

    def _set_competition_actions(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for widget in (
            self.new_team_button,
            self.team_button,
            self.add_button,
            self.name_entry,
            self.quick_team_box,
        ):
            widget.configure(state=state if widget is not self.quick_team_box else (
                "readonly" if enabled else tk.DISABLED
            ))
        self._update_actions()

    def _refresh_teams(self) -> None:
        competition = self._current_competition()
        teams = self.store.list_teams(competition.id) if self.store and competition else []
        self.team_by_label = {team.name: team.id for team in teams}
        quick_values = ["Unassigned", *self.team_by_label]
        self.quick_team_box.configure(values=quick_values)
        if self.quick_team_var.get() not in quick_values:
            self.quick_team_var.set("Unassigned")
        filter_values = ["All teams", "Unassigned", *self.team_by_label]
        self.team_filter_box.configure(values=filter_values)
        if self.team_filter_var.get() not in filter_values:
            self.team_filter_var.set("All teams")

    def _new_competition(self) -> None:
        if self.store is None:
            return
        choice = CompetitionDialog(self).show()
        if choice is None:
            return
        name, season, kind = choice
        try:
            competition = self.store.add_competition(name, season, kind)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not create", str(error), parent=self)
            return
        self.refresh()
        self.competition_var.set(competition.display_name)
        self._competition_changed()

    def _new_team(self) -> None:
        competition = self._current_competition()
        if self.store is None or competition is None:
            return
        name = simpledialog.askstring("Add team", "Team name", parent=self)
        if name is None:
            return
        try:
            team = self.store.add_team(competition.id, name)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not add team", str(error), parent=self)
            return
        self._refresh_teams()
        self.quick_team_var.set(team.name)

    def _quick_add(self) -> None:
        competition = self._current_competition()
        if self.store is None or competition is None:
            messagebox.showinfo(
                "Create a league or tournament first",
                "Registration needs somewhere to put this bowler.",
                parent=self,
            )
            return
        team_id = self.team_by_label.get(self.quick_team_var.get(), "")
        try:
            registration = self.store.register_bowler(
                competition.id,
                self.name_var.get(),
                self.member_id_var.get(),
                team_id,
            )
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not register bowler", str(error), parent=self)
            return
        bowler = InputBowler(self.name_var.get().strip(), self.member_id_var.get().strip())
        self.name_var.set("")
        self.member_id_var.set("")
        self._render_rows()
        self.name_entry.focus_set()
        if self.api_provider() is not None:
            self._start_lookup(registration.id, bowler)

    def _register_team(self) -> None:
        competition = self._current_competition()
        if self.store is None or competition is None:
            return
        choice = TeamRegistrationDialog(self, list(self.team_by_label)).show()
        if choice is None:
            return
        team_name, text = choice
        try:
            bowlers = parse_input_text(text)
            _team, registrations = self.store.register_team(
                competition.id, team_name, bowlers
            )
        except (OSError, UnicodeError, ValueError, RegistrationDataError) as error:
            messagebox.showerror("Could not register team", str(error), parent=self)
            return
        self._refresh_teams()
        self._render_rows()
        if self.api_provider() is not None:
            self._queue_lookups(
                [
                    (registration.id, bowler)
                    for registration, bowler in zip(registrations, bowlers, strict=True)
                ]
            )

    def _check_all(self) -> None:
        if self.store is None:
            return
        competition = self._current_competition()
        api = self.api_provider()
        if competition is None or api is None:
            messagebox.showinfo(
                "Sign in needed",
                "Sign in to BOWL.com to check registrations. "
                "You can keep entering bowlers without signing in.",
                parent=self,
            )
            return
        pending = [
            view
            for view in self.store.registration_views(competition.id)
            if not view.registration.withdrawn and view.status != "Ready"
        ]
        if not pending:
            messagebox.showinfo(
                "Nothing to check",
                "All active registrations are ready.",
                parent=self,
            )
            return
        self.bulk_pending.update(view.registration.id for view in pending)
        self._queue_lookups(
            [
                (
                    view.registration.id,
                    InputBowler(view.bowler.name, view.bowler.membership_id),
                )
                for view in pending
            ]
        )
        self.status_callback(f"Checking 0 of {len(pending)} registrations…")

    def _start_lookup(self, registration_id: str, bowler: InputBowler) -> None:
        if self.store is None:
            return
        api = self.api_provider()
        if api is None:
            return
        self._queue_lookups([(registration_id, bowler)])

    def _queue_lookups(self, items: list[tuple[str, InputBowler]]) -> None:
        if self.store is None or not items:
            return
        api = self.api_provider()
        if api is None:
            return
        try:
            self.store.mark_checking_many([registration_id for registration_id, _ in items])
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not save lookup status", str(error), parent=self)
            return
        self._render_rows()
        for registration_id, bowler in items:
            self.lookup_queue.put((api, registration_id, bowler))
        if len(items) == 1:
            self.status_callback(f"Checking {items[0][1].name}…")
        else:
            self.status_callback(f"Queued {len(items)} registrations for checking")

    def _lookup_queue_worker(self) -> None:
        while True:
            task = self.lookup_queue.get()
            if task is None:
                self.lookup_queue.task_done()
                return
            api, registration_id, bowler = task
            result = look_up_bowler(api, bowler)
            self.after(
                0,
                self._lookup_finished,
                registration_id,
                result,
                "Registration updated",
            )
            self.lookup_queue.task_done()

    def _lookup_finished(
        self, registration_id: str, result: LookupResult, status_text: str
    ) -> None:
        if self.store is None:
            return
        try:
            self.store.apply_lookup_result(registration_id, result)
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not save lookup result", str(error), parent=self)
            return
        self.lookup_results[registration_id] = result
        self._render_rows()
        if registration_id in self.bulk_pending:
            self.bulk_pending.remove(registration_id)
            remaining = len(self.bulk_pending)
            if remaining:
                self.status_callback(f"{remaining} registrations still checking…")
            else:
                self.status_callback("Registration checks complete")
        else:
            self.status_callback(status_text)

    def _render_rows(self) -> None:
        self.table.delete(*self.table.get_children())
        competition = self._current_competition()
        if self.store is None or competition is None:
            self.counter_label.configure(text="Create a league or tournament to begin")
            self._update_row_actions()
            return
        views = self.store.registration_views(competition.id)
        total = len(views)
        active = [view for view in views if not view.registration.withdrawn]
        ready = sum(view.status == "Ready" for view in active)
        attention = len(active) - ready
        self.counter_label.configure(
            text=f"{total} registered  •  {ready} ready  •  {attention} need attention"
        )
        selected_filter = self.team_filter_var.get()
        for view in views:
            team_name = view.team.name if view.team else "Unassigned"
            if selected_filter not in {"", "All teams", team_name}:
                continue
            average = (
                str(view.registration.average)
                if view.registration.average is not None
                else "—"
            )
            tag = self._row_tag(view)
            self.table.insert(
                "",
                tk.END,
                iid=view.registration.id,
                values=(
                    view.bowler.name,
                    view.bowler.membership_id or "—",
                    team_name,
                    average,
                    view.status,
                    view.registration.note or "—",
                ),
                tags=(tag,),
            )
        self._update_row_actions()

    @staticmethod
    def _row_tag(view: RegistrationView) -> str:
        if view.registration.withdrawn:
            return "withdrawn"
        if view.status == "Ready":
            return "ready"
        if "error" in view.status.casefold() or "not found" in view.status.casefold():
            return "error"
        return "attention"

    def _selected_view(self) -> RegistrationView | None:
        if self.store is None:
            return None
        selected = self.table.selection()
        competition = self._current_competition()
        if not selected or competition is None:
            return None
        return next(
            (
                view
                for view in self.store.registration_views(competition.id)
                if view.registration.id == selected[0]
            ),
            None,
        )

    def _update_actions(self) -> None:
        competition = self._current_competition()
        can_check = competition is not None and self.api_provider() is not None
        self.check_all_button.configure(state=tk.NORMAL if can_check else tk.DISABLED)
        self._update_row_actions()

    def _update_row_actions(self) -> None:
        view = self._selected_view()
        selected_state = tk.NORMAL if view is not None else tk.DISABLED
        self.edit_button.configure(state=selected_state)
        self.withdraw_button.configure(state=selected_state)
        can_review = view is not None and self.api_provider() is not None
        self.review_button.configure(state=tk.NORMAL if can_review else tk.DISABLED)
        if view:
            self.withdraw_button.configure(
                text="Restore selected" if view.registration.withdrawn else "Withdraw selected"
            )

    def _review_selected(self) -> None:
        view = self._selected_view()
        if view is None:
            return
        api = self.api_provider()
        if api is None:
            messagebox.showinfo("Sign in needed", "Sign in to BOWL.com first.", parent=self)
            return
        result = self.lookup_results.get(view.registration.id)
        if result is not None and result.candidates:
            RegistrationMatchDialog(
                self,
                result,
                lambda member: self._resolve_member(view, member),
            )
            return
        self._start_lookup(
            view.registration.id,
            InputBowler(view.bowler.name, view.bowler.membership_id),
        )

    def _resolve_member(self, view: RegistrationView, member: Member) -> None:
        api = self.api_provider()
        if api is None:
            return
        bowler = InputBowler(view.bowler.name, f"{member.prefix}-{member.suffix}")
        self.status_callback(f"Confirming {member.display_name}…")
        Thread(
            target=self._resolve_worker,
            args=(api, view.registration.id, bowler, member),
            daemon=True,
        ).start()

    def _resolve_worker(
        self,
        api: BowlApi,
        registration_id: str,
        bowler: InputBowler,
        member: Member,
    ) -> None:
        result = resolve_selected_member(api, bowler, member)
        self.after(0, self._lookup_finished, registration_id, result, "Match confirmed")

    def _edit_selected(self) -> None:
        if self.store is None:
            return
        view = self._selected_view()
        if view is None:
            return
        choice = RegistrationEditDialog(
            self, view, list(self.team_by_label)
        ).show()
        if choice is None:
            return
        name, membership_id, team_label = choice
        team_id = self.team_by_label.get(team_label, "")
        try:
            self.store.update_registration(
                view.registration.id,
                name,
                membership_id,
                team_id,
            )
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not update bowler", str(error), parent=self)
            return
        self._render_rows()
        if self.api_provider() is not None:
            self._start_lookup(
                view.registration.id, InputBowler(name, membership_id)
            )

    def _toggle_withdrawn(self) -> None:
        if self.store is None:
            return
        view = self._selected_view()
        if view is None:
            return
        try:
            self.store.set_withdrawn(
                view.registration.id, not view.registration.withdrawn
            )
        except (OSError, RegistrationDataError) as error:
            messagebox.showerror("Could not update registration", str(error), parent=self)
            return
        self._render_rows()

    def close(self) -> None:
        for _worker_number in range(2):
            self.lookup_queue.put(None)


class CompetitionDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.choice: tuple[str, str, CompetitionKind] | None = None
        self.title("New league or tournament")
        self.geometry("500x320")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(1, weight=1)
        ttk.Label(
            content,
            text="Create a registration workspace",
            style="Muted.TLabel",
            font=("Segoe UI", 17, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 18))
        self.kind_var = tk.StringVar(value=CompetitionKind.LEAGUE.value)
        self.name_var = tk.StringVar()
        self.season_var = tk.StringVar()
        for row, label in enumerate(("Type", "Name", "Season or year"), start=1):
            ttk.Label(content, text=label, style="Muted.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=7
            )
        ttk.Combobox(
            content,
            textvariable=self.kind_var,
            values=[item.value for item in CompetitionKind],
            state="readonly",
        ).grid(row=1, column=1, sticky="ew", pady=7)
        name_entry = ttk.Entry(content, textvariable=self.name_var)
        name_entry.grid(row=2, column=1, sticky="ew", pady=7)
        ttk.Entry(content, textvariable=self.season_var).grid(
            row=3, column=1, sticky="ew", pady=7
        )
        ttk.Label(
            content,
            text="Example: Monday Misfits, 2026–27",
            style="Muted.TLabel",
        ).grid(row=4, column=1, sticky="w")
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(26, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons, text="Create", command=self._accept, style="Primary.TButton"
        ).pack(side=tk.LEFT, padx=(8, 0))
        name_entry.focus_set()
        self.bind("<Return>", lambda _event: self._accept())

    def _accept(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Name needed", "Enter a name.", parent=self)
            return
        self.choice = (
            name,
            self.season_var.get().strip(),
            CompetitionKind(self.kind_var.get()),
        )
        self.destroy()

    def show(self) -> tuple[str, str, CompetitionKind] | None:
        self.wait_window()
        return self.choice


class TeamRegistrationDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, teams: list[str]) -> None:
        super().__init__(parent)
        self.choice: tuple[str, str] | None = None
        self.title("Register a whole team")
        self.geometry("620x510")
        self.minsize(540, 430)
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(4, weight=1)
        ttk.Label(
            content,
            text="Register a whole team",
            style="Muted.TLabel",
            font=("Segoe UI", 17, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            content,
            text="Use an existing team or type a new team name.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 14))
        self.team_var = tk.StringVar(value=teams[0] if teams else "")
        team_box = ttk.Combobox(content, textvariable=self.team_var, values=teams)
        team_box.grid(row=2, column=0, sticky="ew")
        ttk.Label(
            content,
            text="One bowler per line. Member IDs are optional: Jane Smith (1234-567890)",
            style="Muted.TLabel",
        ).grid(row=3, column=0, sticky="w", pady=(16, 6))
        self.roster = tk.Text(
            content,
            height=12,
            background="#263139",
            foreground="#EDF4FA",
            insertbackground="#EDF4FA",
            relief=tk.FLAT,
            padx=10,
            pady=8,
        )
        self.roster.grid(row=4, column=0, sticky="nsew")
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=5, column=0, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons,
            text="Register team",
            command=self._accept,
            style="Warm.TButton",
        ).pack(side=tk.LEFT, padx=(8, 0))
        team_box.focus_set()

    def _accept(self) -> None:
        team = self.team_var.get().strip()
        roster = self.roster.get("1.0", tk.END).strip()
        if not team or not roster:
            messagebox.showwarning(
                "Team and bowlers needed",
                "Enter a team name and at least one bowler.",
                parent=self,
            )
            return
        self.choice = (team, roster)
        self.destroy()

    def show(self) -> tuple[str, str] | None:
        self.wait_window()
        return self.choice


class RegistrationEditDialog(tk.Toplevel):
    def __init__(
        self, parent: tk.Misc, view: RegistrationView, teams: list[str]
    ) -> None:
        super().__init__(parent)
        self.choice: tuple[str, str, str] | None = None
        self.title("Edit registration")
        self.geometry("520x350")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(1, weight=1)
        ttk.Label(
            content,
            text="Edit registration",
            style="Muted.TLabel",
            font=("Segoe UI", 17, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 18))
        self.name_var = tk.StringVar(value=view.bowler.name)
        self.id_var = tk.StringVar(value=view.bowler.membership_id)
        self.team_var = tk.StringVar(value=view.team.name if view.team else "Unassigned")
        for row, label in enumerate(("Bowler name", "Member ID", "Team"), start=1):
            ttk.Label(content, text=label, style="Muted.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=7
            )
        name_entry = ttk.Entry(content, textvariable=self.name_var)
        name_entry.grid(row=1, column=1, sticky="ew", pady=7)
        ttk.Entry(content, textvariable=self.id_var).grid(
            row=2, column=1, sticky="ew", pady=7
        )
        ttk.Combobox(
            content,
            textvariable=self.team_var,
            values=["Unassigned", *teams],
            state="readonly",
        ).grid(row=3, column=1, sticky="ew", pady=7)
        ttk.Label(
            content,
            text="Changing the name or member ID will recheck the bowler when signed in.",
            style="Muted.TLabel",
            wraplength=330,
        ).grid(row=4, column=1, sticky="w", pady=(6, 0))
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(26, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons, text="Save changes", command=self._accept, style="Warm.TButton"
        ).pack(side=tk.LEFT, padx=(8, 0))
        name_entry.focus_set()
        self.bind("<Return>", lambda _event: self._accept())

    def _accept(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Name needed", "Enter a bowler name.", parent=self)
            return
        self.choice = (name, self.id_var.get().strip(), self.team_var.get())
        self.destroy()

    def show(self) -> tuple[str, str, str] | None:
        self.wait_window()
        return self.choice


class RegistrationMatchDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        result: LookupResult,
        on_select: Callable[[Member], None],
    ) -> None:
        super().__init__(parent)
        self.result = result
        self.on_select = on_select
        self.title("Choose the right bowler")
        self.geometry("680x420")
        self.transient(parent)
        self.grab_set()
        content = ttk.Frame(self, style="App.TFrame", padding=22)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)
        ttk.Label(
            content,
            text=f"Choose the right {result.input_name}",
            style="Muted.TLabel",
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            content,
            text="The rest of registration can continue while this waits.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 14))
        self.table = ttk.Treeview(
            content,
            columns=("name", "id", "association", "status"),
            show="headings",
        )
        for column, label, width in (
            ("name", "Bowler", 180),
            ("id", "Member ID", 120),
            ("association", "Association", 230),
            ("status", "Status", 80),
        ):
            self.table.heading(column, text=label)
            self.table.column(column, width=width, anchor="w")
        self.table.grid(row=2, column=0, sticky="nsew")
        for index, member in enumerate(result.candidates):
            association = ", ".join(
                value for value in (member.association, member.association_state) if value
            )
            self.table.insert(
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
        if result.candidates:
            self.table.selection_set("0")
            self.table.focus("0")
        buttons = ttk.Frame(content, style="App.TFrame")
        buttons.grid(row=3, column=0, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Not now", command=self.destroy).pack(side=tk.LEFT)
        ttk.Button(
            buttons,
            text="Use selected bowler",
            command=self._accept,
            style="Primary.TButton",
        ).pack(side=tk.LEFT, padx=(8, 0))
        self.table.bind("<Double-1>", lambda _event: self._accept())

    def _accept(self) -> None:
        selected = self.table.selection()
        if not selected:
            return
        member = self.result.candidates[int(selected[0])]
        self.destroy()
        self.on_select(member)
