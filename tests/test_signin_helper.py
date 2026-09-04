import importlib
import sys
from threading import Thread
from types import SimpleNamespace


class EventHook:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        for handler in self.handlers:
            handler()


def test_closing_webview_stops_watcher_and_reports_once(monkeypatch, capsys):
    closed = EventHook()
    window = SimpleNamespace(
        events=SimpleNamespace(closed=closed), evaluate_js=lambda _: [], destroy=closed.fire
    )

    def start(callback, args, **kwargs):
        assert kwargs["private_mode"] is True
        watcher = Thread(target=callback, args=args)
        watcher.start()
        closed.fire()
        watcher.join(timeout=1)
        assert not watcher.is_alive()

    webview = SimpleNamespace(create_window=lambda *a, **k: window, start=start)
    monkeypatch.setitem(sys.modules, "webview", webview)
    module_name = "usbc_average_lookup.signin_helper"
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    helper = importlib.import_module(module_name)
    helper.run_private_sign_in(300)
    output = capsys.readouterr().out
    assert output.count(helper.AUTH_MESSAGE_PREFIX) == 1
    assert "The sign-in window was closed" in output
