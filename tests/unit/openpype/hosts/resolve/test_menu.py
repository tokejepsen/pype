"""Tests for the Resolve menu topmost-window sync and workfile auto export."""
import importlib.util
import os
import tempfile
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


class TestParseDblistRoots(unittest.TestCase):
    def test_returns_unique_disk_roots_with_drive_colon_restored(self):
        text = "\n".join([
            "Local Database:C\\Users\\admin\\AppData\\Roaming\\Blackmagic "
            "Design\\DaVinci Resolve\\Support\\Resolve Project Library"
            ":*:::DISK",
            "Studio:10.0.0.5:resolve_db:postgres:secret:PG",
            "Copy:C\\Users\\admin\\AppData\\Roaming\\Blackmagic "
            "Design\\DaVinci Resolve\\Support\\Resolve Project Library"
            ":*:::DISK",
        ])

        self.assertEqual(
            [
                "C:\\Users\\admin\\AppData\\Roaming\\Blackmagic Design"
                "\\DaVinci Resolve\\Support\\Resolve Project Library"
            ],
            menu.parse_dblist_roots(text),
        )


def _make_project_db(root, *project_parts):
    folder = os.path.join(
        root, "Resolve Projects", "Users", "guest", "Projects",
        *project_parts
    )
    os.makedirs(folder)
    path = os.path.join(folder, "Project.db")
    with open(path, "w"):
        pass
    return path


class TestFindProjectDb(unittest.TestCase):
    def setUp(self):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        self.root = tempdir.name

    def test_finds_project_directly_in_projects(self):
        expected = _make_project_db(self.root, "shot010")

        self.assertEqual(
            os.path.normcase(expected),
            os.path.normcase(menu.find_project_db("shot010", [self.root])),
        )

    def test_finds_project_in_nested_folder(self):
        expected = _make_project_db(self.root, "Folder", "shot010")

        self.assertEqual(
            os.path.normcase(expected),
            os.path.normcase(menu.find_project_db("shot010", [self.root])),
        )

    def test_returns_none_when_project_is_missing(self):
        _make_project_db(self.root, "other")

        self.assertIsNone(menu.find_project_db("shot010", [self.root]))

    def test_project_name_with_glob_characters_is_matched_literally(self):
        _make_project_db(self.root, "x")
        expected = _make_project_db(self.root, "shot[x]")

        self.assertEqual(
            os.path.normcase(expected),
            os.path.normcase(menu.find_project_db("shot[x]", [self.root])),
        )


class TestProjectDbLocator(unittest.TestCase):
    def test_caches_path_and_searches_again_when_it_disappears(self):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        get_roots = MagicMock(return_value=[tempdir.name])
        locator = menu.ProjectDbLocator(get_roots=get_roots)
        first = _make_project_db(tempdir.name, "shot010")

        self.assertEqual(first, locator("shot010"))
        self.assertEqual(first, locator("shot010"))
        self.assertEqual(1, get_roots.call_count)

        os.remove(first)
        moved = _make_project_db(tempdir.name, "Folder", "shot010")

        self.assertEqual(
            os.path.normcase(moved), os.path.normcase(locator("shot010"))
        )


DEBOUNCE = 10
MIN_INTERVAL = 60


class TestWorkfileAutoExporter(unittest.TestCase):
    """Drives `WorkfileAutoExporter` with a fake clock and filesystem.

    Project `<name>` has its workfile at `<name>.drp` and its database at
    `<name>/Project.db`; a file exists when it has an entry in `mtimes`.
    """

    def setUp(self):
        self.now = 1000.0
        self.project = "shot010"
        self.mtimes = {}
        self.export = MagicMock()
        self.on_exported = MagicMock()
        self.db_type = "Disk"
        self.on_unavailable = MagicMock()
        self.on_available = MagicMock()
        self.exporter = menu.WorkfileAutoExporter(
            get_project_name=lambda: self.project,
            get_workfile_path=lambda: self._drp(self.project),
            find_project_db=lambda name: (
                self._db(name) if self._db(name) in self.mtimes else None
            ),
            export=self.export,
            clock=lambda: self.now,
            getmtime=lambda path: self.mtimes[path],
            exists=lambda path: path in self.mtimes,
            debounce=DEBOUNCE,
            min_interval=MIN_INTERVAL,
            on_exported=self.on_exported,
            get_db_type=lambda: self.db_type,
            on_unavailable=self.on_unavailable,
            on_available=self.on_available,
        )
        patcher = mock.patch.object(menu, "log")
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _drp(project):
        return f"{project}.drp" if project else None

    @staticmethod
    def _db(project):
        return f"{project}/Project.db"

    def _set_files(self, db=None, drp=None, project=None):
        project = project or self.project
        if db is not None:
            self.mtimes[self._db(project)] = db
        if drp is not None:
            self.mtimes[self._drp(project)] = drp

    def _export_writes_drp(self, path):
        self.mtimes[path] = self.now

    def test_exports_when_db_is_newer_than_workfile_and_settled(self):
        self._set_files(db=900, drp=800)

        self.assertTrue(self.exporter.tick())

        self.export.assert_called_once_with("shot010.drp")
        self.on_exported.assert_called_once_with()

    def test_does_not_export_when_workfile_is_newer_than_db(self):
        self._set_files(db=800, drp=900)

        self.assertFalse(self.exporter.tick())

        self.export.assert_not_called()

    def test_does_not_export_when_workfile_does_not_exist(self):
        self._set_files(db=900)

        self.assertFalse(self.exporter.tick())

        self.export.assert_not_called()

    def test_waits_for_debounce_before_exporting(self):
        self._set_files(db=995, drp=800)

        self.assertFalse(self.exporter.tick())
        self.export.assert_not_called()

        self.now = 1005.0
        self.assertTrue(self.exporter.tick())
        self.export.assert_called_once_with("shot010.drp")

    def test_db_touched_by_export_does_not_retrigger_but_new_save_does(self):
        self._set_files(db=900, drp=800)

        def export(path):
            # Exporting writes the workfile and then touches the db.
            self.mtimes[path] = self.now
            self.mtimes[self._db(self.project)] = self.now + 1

        self.export.side_effect = export

        self.assertTrue(self.exporter.tick())

        self.now = 1100.0
        self.assertFalse(self.exporter.tick())
        self.assertEqual(1, self.export.call_count)

        self._set_files(db=1200)
        self.now = 1300.0
        self.assertTrue(self.exporter.tick())
        self.assertEqual(2, self.export.call_count)

    def test_respects_min_interval_between_exports(self):
        self._set_files(db=900, drp=800)
        self.export.side_effect = self._export_writes_drp
        self.assertTrue(self.exporter.tick())

        self._set_files(db=1020)
        self.now = 1035.0
        self.assertFalse(self.exporter.tick())
        self.assertEqual(1, self.export.call_count)

        self.now = 1000.0 + MIN_INTERVAL
        self.assertTrue(self.exporter.tick())
        self.assertEqual(2, self.export.call_count)

    def test_failed_export_returns_false_and_backs_off(self):
        self._set_files(db=900, drp=800)
        self.export.side_effect = RuntimeError("export failed")

        self.assertFalse(self.exporter.tick())
        self.on_exported.assert_not_called()

        self.now = 1030.0
        self.assertFalse(self.exporter.tick())
        self.assertEqual(1, self.export.call_count)

        self.now = 1000.0 + MIN_INTERVAL
        self.exporter.tick()
        self.assertEqual(2, self.export.call_count)

    def test_does_not_export_untitled_or_missing_project(self):
        for project in (None, "Untitled Project"):
            with self.subTest(project=project):
                self.project = project
                self._set_files(db=900, drp=800, project=str(project))

                self.assertFalse(self.exporter.tick())

        self.export.assert_not_called()

    def test_switching_project_resets_export_state(self):
        self._set_files(db=900, drp=800)
        self.export.side_effect = self._export_writes_drp
        self.assertTrue(self.exporter.tick())

        self.project = "shot020"
        self._set_files(db=900, drp=800)
        self.now = 1010.0

        self.assertTrue(self.exporter.tick())
        self.export.assert_called_with("shot020.drp")

    def test_postgresql_database_reports_unavailable_once(self):
        self.db_type = "PostgreSQL"
        self._set_files(db=900, drp=800)

        self.assertFalse(self.exporter.tick())
        self.now = 1100.0
        self.assertFalse(self.exporter.tick())

        self.export.assert_not_called()
        self.on_unavailable.assert_called_once()
        self.assertIn("PostgreSQL", self.on_unavailable.call_args[0][0])
        self.on_available.assert_not_called()

    def test_missing_project_db_reports_unavailable(self):
        self._set_files(drp=800)

        self.assertFalse(self.exporter.tick())

        self.on_unavailable.assert_called_once_with(
            "local project file not found"
        )

    def test_reports_available_when_project_db_appears(self):
        self._set_files(drp=800)
        self.exporter.tick()

        self._set_files(db=900)
        self.exporter.tick()
        self.exporter.tick()

        self.on_unavailable.assert_called_once()
        self.on_available.assert_called_once_with()

    def test_switching_to_available_project_reports_available(self):
        self._set_files(drp=800)
        self.exporter.tick()

        self.project = "shot020"
        self._set_files(db=900, drp=800)
        self.exporter.tick()

        self.on_unavailable.assert_called_once()
        self.on_available.assert_called_once_with()

    def test_no_workfile_or_untitled_project_reports_nothing(self):
        self.db_type = "PostgreSQL"
        for project in ("shot010", "Untitled Project"):
            with self.subTest(project=project):
                self.project = project
                self._set_files(db=900)

                self.assertFalse(self.exporter.tick())

        self.on_unavailable.assert_not_called()
        self.on_available.assert_not_called()


class TestOpenPypeMenuSaveStatus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = (
            menu.QtWidgets.QApplication.instance()
            or menu.QtWidgets.QApplication([])
        )

    def setUp(self):
        self.widget = menu.OpenPypeMenu()
        self.addCleanup(self.widget.deleteLater)
        self.label = self.widget._save_status_label

    def test_warning_is_shown_under_save_status_and_can_be_cleared(self):
        self.widget.set_save_status("Saved")
        saved = self.label.text()

        self.widget.set_auto_save_warning("PostgreSQL database")

        lines = self.label.text().split("\n")
        self.assertEqual(saved, lines[0])
        self.assertTrue(saved.startswith("Saved "))
        self.assertIn("PostgreSQL database", lines[1])

        self.widget.set_auto_save_warning(None)

        self.assertEqual(saved, self.label.text())


if __name__ == "__main__":
    unittest.main()
