"""Tests for the Resolve workfile opening logic."""
import importlib.util
import os
import sys
import tempfile
import types
import unittest
import zipfile
from unittest import mock
from unittest.mock import MagicMock

# Load by path, the resolve api package imports opentimelineio at import.
# workio uses relative imports, so register a fake parent package.
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, *[os.pardir] * 5))
WORKIO_PATH = os.path.join(
    REPO_ROOT, "openpype", "hosts", "resolve", "api", "workio.py"
)
PACKAGE = "openpype_resolve_api_stub"

package = types.ModuleType(PACKAGE)
package.__path__ = []
lib_stub = types.ModuleType(f"{PACKAGE}.lib")
lib_stub.get_project_manager = MagicMock()
lib_stub.get_current_project = MagicMock()
bmdvr_stub = types.ModuleType(f"{PACKAGE}.bmdvr")
bmdvr_stub.GetCurrentPage = MagicMock(return_value=None)
bmdvr_stub.GetVersion = MagicMock(return_value=[18, 0, 0])
package.lib = lib_stub
package.bmdvr = bmdvr_stub
sys.modules[PACKAGE] = package
sys.modules[f"{PACKAGE}.lib"] = lib_stub
sys.modules[f"{PACKAGE}.bmdvr"] = bmdvr_stub

spec = importlib.util.spec_from_file_location(
    f"{PACKAGE}.workio", WORKIO_PATH
)
workio = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = workio
spec.loader.exec_module(workio)

LOCAL_DATE = "2026-11-20T11:33:30Z"
LOCAL_TS = 1795174410  # LOCAL_DATE in epoch seconds
OLDER_TS = LOCAL_TS - 100
NEWER_TS = LOCAL_TS + 100
FILEPATH = os.path.join("work", "shot010_v001.drp")
FNAME = "shot010_v001"


class TestReadDrpLastModified(unittest.TestCase):
    def setUp(self):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        self.tempdir = tempdir.name

    def test_returns_last_mod_time_not_other_mod_time_tags(self):
        path = os.path.join(self.tempdir, "a.drp")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "project.xml",
                "<Project><Sm2Timeline><ModTimeInSecs>1</ModTimeInSecs>"
                "</Sm2Timeline>"
                "<LastModTimeInSecs>1795102608</LastModTimeInSecs>"
                "<LastModTimeInSecs>5</LastModTimeInSecs></Project>",
            )

        self.assertEqual(1795102608, workio._read_drp_last_modified(path))

    def test_returns_none_for_bad_zip(self):
        path = os.path.join(self.tempdir, "bad.drp")
        with open(path, "w") as handle:
            handle.write("not a zip")

        self.assertIsNone(workio._read_drp_last_modified(path))


class TestOpenFile(unittest.TestCase):
    def setUp(self):
        self.pm = MagicMock()
        self.project = MagicMock()
        self.project.GetName.return_value = FNAME
        self.pm.LoadProject.return_value = self.project
        self.pm.GetProjectAttributesInCurrentFolder.return_value = {
            FNAME: {"lastModifiedDate": LOCAL_DATE}
        }
        self.drp_ts = OLDER_TS
        self.ask = MagicMock(return_value="local")
        self.critical = MagicMock()

        for patcher in (
            mock.patch.object(workio, "get_project_manager",
                              return_value=self.pm),
            mock.patch.object(
                workio, "_read_drp_last_modified",
                side_effect=lambda path: self.drp_ts,
            ),
            mock.patch.object(workio, "_ask_drp_newer", self.ask),
            mock.patch.object(workio, "_show_critical", self.critical),
            mock.patch.object(workio, "log"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_local_newer_loads_without_import_or_dialog(self):
        self.assertTrue(workio.open_file(FILEPATH))

        self.pm.LoadProject.assert_called_once_with(FNAME)
        self.pm.ImportProject.assert_not_called()
        self.ask.assert_not_called()

    def test_drp_newer_open_local_loads_without_import(self):
        self.drp_ts = NEWER_TS

        self.assertTrue(workio.open_file(FILEPATH))

        self.ask.assert_called_once_with(FNAME, LOCAL_TS, NEWER_TS)
        self.pm.LoadProject.assert_called_once_with(FNAME)
        self.pm.ImportProject.assert_not_called()

    def test_drp_newer_replace_backs_up_and_imports(self):
        self.drp_ts = NEWER_TS
        self.ask.return_value = "replace"
        self.pm.ImportProject.return_value = True

        self.assertTrue(workio.open_file(FILEPATH))

        backup_name = self.project.SetName.call_args[0][0]
        self.assertRegex(backup_name, rf"^{FNAME}_backup_\d{{8}}_\d{{6}}$")
        self.pm.SaveProject.assert_called_once_with()
        self.pm.CloseProject.assert_called_once_with(self.project)
        self.pm.ImportProject.assert_called_once_with(FILEPATH)
        self.assertEqual(
            [mock.call(FNAME), mock.call(FNAME)],
            self.pm.LoadProject.call_args_list,
        )

    def test_drp_newer_replace_failure_shows_error(self):
        self.drp_ts = NEWER_TS
        self.ask.return_value = "replace"
        self.pm.ImportProject.return_value = False

        self.assertFalse(workio.open_file(FILEPATH))

        self.critical.assert_called_once()

    def test_drp_newer_cancel_does_not_load(self):
        self.drp_ts = NEWER_TS
        self.ask.return_value = "cancel"

        self.assertFalse(workio.open_file(FILEPATH))

        self.pm.LoadProject.assert_not_called()
        self.pm.ImportProject.assert_not_called()

    def test_unknown_drp_timestamp_loads_local(self):
        self.drp_ts = None

        self.assertTrue(workio.open_file(FILEPATH))

        self.ask.assert_not_called()
        self.pm.LoadProject.assert_called_once_with(FNAME)

    def test_missing_project_is_imported(self):
        self.pm.GetProjectAttributesInCurrentFolder.return_value = {}
        self.pm.LoadProject.side_effect = [None, self.project]
        self.pm.ImportProject.return_value = True

        self.assertTrue(workio.open_file(FILEPATH))

        self.pm.ImportProject.assert_called_once_with(FILEPATH)
        self.assertEqual(2, self.pm.LoadProject.call_count)
        self.ask.assert_not_called()

    def test_failed_import_shows_error(self):
        self.pm.LoadProject.return_value = None
        self.pm.GetProjectAttributesInCurrentFolder.return_value = {}
        self.pm.ImportProject.return_value = False

        self.assertFalse(workio.open_file(FILEPATH))

        self.critical.assert_called_once()

    def test_attributes_method_missing_falls_back_to_load(self):
        self.drp_ts = NEWER_TS
        self.pm.GetProjectAttributesInCurrentFolder.side_effect = (
            AttributeError("old Resolve")
        )

        self.assertTrue(workio.open_file(FILEPATH))

        self.pm.LoadProject.assert_called_once_with(FNAME)
        self.pm.ImportProject.assert_not_called()
        self.ask.assert_not_called()

    def test_attributes_returning_none_falls_back_to_load(self):
        self.drp_ts = NEWER_TS
        self.pm.GetProjectAttributesInCurrentFolder.return_value = None

        self.assertTrue(workio.open_file(FILEPATH))

        self.pm.LoadProject.assert_called_once_with(FNAME)
        self.ask.assert_not_called()


if __name__ == "__main__":
    unittest.main()
