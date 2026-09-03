from usbc_average_lookup.workspace import LeagueWorkspaceContext, ScoreSheetEditLocks


def test_workspace_context_notifies_only_when_selection_changes() -> None:
    context = LeagueWorkspaceContext("league-1")
    selections: list[str] = []
    context.subscribe(selections.append)

    context.select("league-1")
    context.select("league-2")

    assert context.competition_id == "league-2"
    assert selections == ["league-2"]


def test_workspace_context_subscription_can_be_removed() -> None:
    context = LeagueWorkspaceContext("league-1")
    selections: list[str] = []
    unsubscribe = context.subscribe(selections.append, notify=True)

    unsubscribe()
    context.select("league-2")

    assert selections == ["league-1"]


def test_score_sheet_lock_rejects_another_window_until_released() -> None:
    locks = ScoreSheetEditLocks()

    assert locks.acquire("week-1", "main")
    assert not locks.acquire("week-1", "detached")

    locks.release("week-1", "main")

    assert locks.acquire("week-1", "detached")
