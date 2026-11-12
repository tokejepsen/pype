"""Tests for the Resolve menu topmost-window sync."""
import importlib.util
import os
import unittest
from unittest import mock
from unittest.mock import MagicMock, call

# Load by path, the resolve api package imports opentimelineio at import.
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, *[os.pardir] * 5))
MENU_PATH = os.path.join(
    REPO_ROOT, "openpype", "hosts", "resolve", "api", "menu.py"
)
spec = importlib.util.spec_from_file_location(
    "openpype_resolve_menu", MENU_PATH
)
menu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(menu)

RESOLVE_PID = 100
OTHER_PID = 200
FOREGROUND = 999
FLAGS = 0x0013
ASYNC_FLAGS = 0x4013
WS_EX_TOPMOST = 0x8


class TestSyncTopmost(unittest.TestCase):
    def _sync(
        self,
        foreground_pid,
        hwnds=(1, 2),
        foreground=FOREGROUND,
        foreground_exstyle=0,
        exstyles=None,
    ):
        """Run `_sync_topmost` with `foreground` owned by `foreground_pid`.

        `exstyles` maps our hwnds to their actual extended style
        (default 0). Returns the mock user32.
        """
        exstyles = exstyles or {}
        user32 = MagicMock()
        user32.GetForegroundWindow.return_value = foreground
        user32.GetWindowLongW.side_effect = lambda hwnd, index: (
            foreground_exstyle
            if hwnd == foreground
            else exstyles.get(hwnd, 0)
        )
        with mock.patch.object(
            menu, "_get_pid_from_hwnd", return_value=foreground_pid
        ):
            self.result = menu._sync_topmost(
                list(hwnds), {RESOLVE_PID}, user32
            )
        return user32

    def test_sets_windows_topmost_when_resolve_is_foreground(self):
        user32 = self._sync(RESOLVE_PID)

        self.assertEqual(
            [
                call(1, -1, 0, 0, 0, 0, FLAGS),
                call(2, -1, 0, 0, 0, 0, FLAGS),
            ],
            user32.SetWindowPos.call_args_list,
        )

    def test_drops_windows_below_foreground_app_when_other_is_foreground(
        self
    ):
        user32 = self._sync(
            OTHER_PID, hwnds=[1], exstyles={1: WS_EX_TOPMOST}
        )

        self.assertEqual(
            [
                call(1, -2, 0, 0, 0, 0, FLAGS),
                call(1, FOREGROUND, 0, 0, 0, 0, FLAGS),
            ],
            user32.SetWindowPos.call_args_list,
        )

    def test_skips_windows_whose_actual_topmost_bit_matches_desired(self):
        user32 = self._sync(
            RESOLVE_PID, exstyles={1: WS_EX_TOPMOST, 2: WS_EX_TOPMOST}
        )

        user32.SetWindowPos.assert_not_called()

    def test_leaves_windows_untouched_when_foreground_is_foreign_topmost(
        self
    ):
        user32 = self._sync(
            OTHER_PID,
            hwnds=[1],
            foreground_exstyle=WS_EX_TOPMOST,
            exstyles={1: WS_EX_TOPMOST},
        )

        user32.SetWindowPos.assert_not_called()
        self.assertIsNone(self.result)

    def test_leaves_windows_untouched_when_no_foreground_window(self):
        user32 = self._sync(
            OTHER_PID,
            hwnds=[1],
            foreground=0,
            exstyles={1: WS_EX_TOPMOST},
        )

        user32.SetWindowPos.assert_not_called()
        self.assertIsNone(self.result)

    def test_sets_windows_topmost_when_own_topmost_window_is_foreground(
        self
    ):
        user32 = self._sync(
            RESOLVE_PID, hwnds=[1], foreground_exstyle=WS_EX_TOPMOST
        )

        self.assertEqual(
            [call(1, -1, 0, 0, 0, 0, FLAGS)],
            user32.SetWindowPos.call_args_list,
        )

    def test_returns_foreground_pid(self):
        self._sync(OTHER_PID)

        self.assertEqual(OTHER_PID, self.result)


class TestRaiseResolve(unittest.TestCase):
    def _raise(self, foreground_pid, previous_pid):
        """Run `_raise_resolve` as pid 100 with Resolve at hwnd 7.

        Returns the mock user32.
        """
        user32 = MagicMock()
        menu._raise_resolve(
            foreground_pid=foreground_pid,
            previous_pid=previous_pid,
            own_pid=RESOLVE_PID,
            resolve_hwnd=7,
            user32=user32,
        )
        return user32

    def test_raises_resolve_when_focus_enters_process_from_another(self):
        user32 = self._raise(RESOLVE_PID, OTHER_PID)

        self.assertEqual(
            [
                call(7, -1, 0, 0, 0, 0, ASYNC_FLAGS),
                call(7, -2, 0, 0, 0, 0, ASYNC_FLAGS),
            ],
            user32.SetWindowPos.call_args_list,
        )

    def test_does_not_raise_resolve_when_focus_stays_in_process(self):
        user32 = self._raise(RESOLVE_PID, RESOLVE_PID)

        user32.SetWindowPos.assert_not_called()

    def test_does_not_raise_resolve_when_another_app_is_foreground(self):
        user32 = self._raise(OTHER_PID, RESOLVE_PID)

        user32.SetWindowPos.assert_not_called()


class TestOnResolveExit(unittest.TestCase):
    def test_closes_all_windows_then_quits_application(self):
        with mock.patch.object(
            menu.QtWidgets, "QApplication"
        ) as application:
            menu._on_resolve_exit()

        self.assertEqual(
            [call.closeAllWindows(), call.quit()],
            application.mock_calls,
        )


if __name__ == "__main__":
    unittest.main()
