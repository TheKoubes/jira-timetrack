from timetrack.tray import (
    PBT_APMSUSPEND,
    UPDATE_CMD_ID,
    WM_DESTROY,
    WM_POWERBROADCAST,
    WM_QUERYENDSESSION,
    WM_TRAY_BALLOON,
    WM_WTSSESSION_CHANGE,
    WTS_SESSION_LOCK,
    AutoStopFlags,
    TrayThread,
    menu_action,
)


def test_window_destroy_requests_app_quit():
    actions = []
    tray = TrayThread("ctrl+alt+t", on_action=actions.append, on_error=actions.append)

    tray._handle_message(None, WM_DESTROY, 0, 0)

    assert actions == ["quit"]


def _tray(flags):
    stops = []
    tray = TrayThread(
        "ctrl+alt+t",
        on_action=lambda a: None,
        on_error=lambda m: None,
        on_autostop=lambda: stops.append(1),
        flags=flags,
    )
    return tray, stops


def test_lock_autostops_when_enabled():
    tray, stops = _tray(AutoStopFlags(lock=True))

    assert tray._handle_message(0, WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK, 0) == 0
    assert stops == [1]


def test_lock_ignored_when_disabled():
    tray, stops = _tray(AutoStopFlags(lock=False))

    tray._handle_message(0, WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK, 0)

    assert stops == []


def test_unlock_never_autostops():
    tray, stops = _tray(AutoStopFlags(lock=True))

    tray._handle_message(0, WM_WTSSESSION_CHANGE, 0x8, 0)  # WTS_SESSION_UNLOCK

    assert stops == []


def test_suspend_autostops_when_enabled():
    tray, stops = _tray(AutoStopFlags(suspend=True))

    assert tray._handle_message(0, WM_POWERBROADCAST, PBT_APMSUSPEND, 0) == 1
    assert stops == [1]


def test_suspend_ignored_when_disabled():
    tray, stops = _tray(AutoStopFlags(suspend=False))

    assert tray._handle_message(0, WM_POWERBROADCAST, PBT_APMSUSPEND, 0) == 1
    assert stops == []


def test_queryendsession_autostops_and_allows_shutdown():
    tray, stops = _tray(AutoStopFlags(logoff=True))

    assert tray._handle_message(0, WM_QUERYENDSESSION, 0, 0) == 1  # TRUE = povolit
    assert stops == [1]


def test_queryendsession_allows_shutdown_even_when_disabled():
    tray, stops = _tray(AutoStopFlags(logoff=False))

    assert tray._handle_message(0, WM_QUERYENDSESSION, 0, 0) == 1
    assert stops == []


def test_menu_ids_map_to_actions():
    assert menu_action(1) == "show"
    assert menu_action(2) == "summary"
    assert menu_action(3) == "week"
    assert menu_action(4) == "quit"
    assert menu_action(5) == "jira"
    assert menu_action(6) == "edit"
    assert menu_action(7) == "settings"
    assert menu_action(8) == "restart"


def test_unknown_or_cancelled_menu_gives_none():
    assert menu_action(0) is None  # TrackPopupMenu vraci 0 pri zavreni bez vyberu
    assert menu_action(999) is None


def test_update_item_is_not_a_regular_menu_action():
    # Polozka "Aktualizovat..." ma vlastni cmd id a resi se zvlast v _show_menu.
    assert menu_action(UPDATE_CMD_ID) is None


def test_balloon_message_routes_to_show_balloon():
    tray = TrayThread("ctrl+alt+t", on_action=lambda a: None, on_error=lambda m: None)
    shown = []
    tray._show_balloon = lambda: shown.append(1)

    assert tray._handle_message(0, WM_TRAY_BALLOON, 0, 0) == 0
    assert shown == [1]


def test_notify_update_without_window_is_noop():
    tray = TrayThread("ctrl+alt+t", on_action=lambda a: None, on_error=lambda m: None)

    tray.notify_update("1.4", "TimeTrack", "nova verze")  # hwnd je None

    assert tray.update_version is None  # bez okna se nic nenastavi ani nespadne
