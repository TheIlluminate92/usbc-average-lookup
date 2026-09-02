from threading import Thread

from usbc_average_lookup import signin_helper


class EventHook:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self) -> None:
        for handler in self.handlers:
            handler()


class FakeEvents:
    def __init__(self) -> None:
        self.closed = EventHook()


class FakeWindow:
    def __init__(self) -> None:
        self.events = FakeEvents()

    def evaluate_js(self, _script: str):
        return []

    def destroy(self) -> None:
        self.events.closed.fire()


def test_closing_window_stops_watcher_and_reports_once(monkeypatch, capsys) -> None:
    window = FakeWindow()
    monkeypatch.setattr(signin_helper.webview, "create_window", lambda *_args, **_kwargs: window)

    def close_during_watch(callback, args, **_kwargs) -> None:
        watcher = Thread(target=callback, args=args)
        watcher.start()
        window.events.closed.fire()
        watcher.join(timeout=1)
        assert not watcher.is_alive()

    monkeypatch.setattr(signin_helper.webview, "start", close_during_watch)

    signin_helper.run_private_sign_in(timeout_seconds=300)

    output = capsys.readouterr().out
    assert output.count(signin_helper.AUTH_MESSAGE_PREFIX) == 1
    assert "The sign-in window was closed" in output
