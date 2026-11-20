from collections import defaultdict
from functools import partial
import glob
import os
import platform
import re
import sys
import time

from qtpy import QtWidgets, QtCore, QtGui

from openpype.lib import Logger
from openpype.tools.utils import host_tools
from openpype.pipeline import registered_host

if platform.system() == "Windows":
    from ctypes import wintypes
    import ctypes

log = Logger.get_logger(__name__)

_RESOLVE_EXECUTABLE = "resolve.exe"

# Resolve 18+ includes the major version in the title, e.g.
# 'DaVinci Resolve 20 - Untitled Project'. Older builds and the Studio
# edition drop or move those parts, so keep both optional.
_RESOLVE_TITLE_RE = re.compile(
    r"^DaVinci Resolve(?: Studio)?(?: [\d\.]+)? - "
)

_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_GWL_EXSTYLE = -20
_WS_EX_TOPMOST = 0x8
_SWP_FLAGS = 0x0013  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
_SWP_ASYNCWINDOWPOS = 0x4000

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0x0

_UNTITLED_PROJECT = "Untitled Project"

# Matches a disk database entry in Resolve's dblist.conf, e.g.
# 'Local Database:C\Users\me\...\Resolve Project Library:*:::DISK'
_DBLIST_DISK_RE = re.compile(
    r"^[^:]*:(?P<path>.+?):[^:]*:[^:]*:[^:]*:DISK\s*$"
)
# Resolve strips the colon of the drive letter, 'C\Users' is 'C:\Users'.
_DBLIST_DRIVE_RE = re.compile(r"^([A-Za-z])([\\/])")

_SAVE_STATUS_STYLE = "color: #888888; font-size: 10px;"
_SAVE_STATUS_WARNING_STYLE = "color: #e0a030; font-size: 10px;"

_AUTO_EXPORT_INTERVAL_MS = 5000
# Seconds Project.db has to be unchanged before exporting, so we do not
# export in the middle of an edit with Live Save.
_AUTO_EXPORT_DEBOUNCE = 10
# Minimum seconds between two export attempts.
_AUTO_EXPORT_MIN_INTERVAL = 60


def _list_top_level_hwnds(user32):
    """Visible, titled top-level windows as {title: [hwnd, ...]}."""
    IsWindowVisible = user32.IsWindowVisible
    GetParent = user32.GetParent
    GetWindowTextLength = user32.GetWindowTextLengthW
    GetWindowText = user32.GetWindowTextW
    EnumWindows = user32.EnumWindows
    EnumWindows.argtypes = [
        ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
        wintypes.LPARAM
    ]

    results = defaultdict(list)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum_proc(hwnd, lParam):
        if not IsWindowVisible(hwnd) or GetParent(hwnd):
            return True

        length = GetWindowTextLength(hwnd)
        if length == 0:
            return True

        buf = ctypes.create_unicode_buffer(length + 1)
        GetWindowText(hwnd, buf, length + 1)
        title = buf.value.strip()
        if title:
            results[title].append(hwnd)
        return True

    EnumWindows(_enum_proc, 0)
    return dict(results)


def _is_resolve_title(title):
    if not _RESOLVE_TITLE_RE.match(title):
        return False
    elif title.endswith("File Explorer"):
        return False
    return True


def _get_window_area(hwnd, user32):
    GetWindowRect = user32.GetWindowRect
    GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    GetWindowRect.restype = wintypes.BOOL
    rect = wintypes.RECT()
    if not GetWindowRect(hwnd, ctypes.byref(rect)):
        return 0
    return (rect.right - rect.left) * (rect.bottom - rect.top)


def _get_pid_from_hwnd(hwnd, user32):
    GetWindowThreadProcessId = user32.GetWindowThreadProcessId
    GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
    ]
    GetWindowThreadProcessId.restype = wintypes.DWORD
    pid = wintypes.DWORD()
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _get_process_image_name(pid, kernel32):
    """Lowercased executable file name of process `pid`, or None."""
    handle = kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        return None

    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(
            handle, 0, buf, ctypes.byref(size)
        ):
            return None
        return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(handle)


def _is_pid_running(pid, kernel32):
    handle = kernel32.OpenProcess(
        _SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        return False

    try:
        # A signaled process handle means the process has exited.
        return kernel32.WaitForSingleObject(handle, 0) != _WAIT_OBJECT_0
    finally:
        kernel32.CloseHandle(handle)


def _list_resolve_hwnds(user32, kernel32, all_hwnds=None):
    """HWNDs of all top-level windows owned by a Resolve process."""
    if all_hwnds is None:
        all_hwnds = _list_top_level_hwnds(user32)

    image_names = {}
    owned = []
    for hwnds in all_hwnds.values():
        for hwnd in hwnds:
            pid = _get_pid_from_hwnd(hwnd, user32)
            if pid not in image_names:
                image_names[pid] = _get_process_image_name(pid, kernel32)
            if image_names[pid] == _RESOLVE_EXECUTABLE:
                owned.append(hwnd)
    return owned


def _any_resolve_running(user32, kernel32):
    return bool(_list_resolve_hwnds(user32, kernel32))


def _sync_topmost(hwnds, pids, user32):
    """Keep `hwnds` topmost only while a window owned by `pids` is focused."""
    foreground = user32.GetForegroundWindow()
    if not foreground:
        return None

    foreground_pid = _get_pid_from_hwnd(foreground, user32)

    # Foreign topmost foregrounds (Alt-Tab switcher, Start menu) would make
    # ours topmost via insert-after.
    is_foreground_topmost = bool(
        user32.GetWindowLongW(foreground, _GWL_EXSTYLE) & _WS_EX_TOPMOST
    )
    if is_foreground_topmost and foreground_pid not in pids:
        return None

    topmost = foreground_pid in pids
    for hwnd in hwnds:

        # Windows can silently clear the bit on owned windows, so read the
        # actual style rather than caching.
        is_topmost = bool(
            user32.GetWindowLongW(hwnd, _GWL_EXSTYLE) & _WS_EX_TOPMOST
        )
        if is_topmost == topmost:
            continue

        if topmost:
            user32.SetWindowPos(
                hwnd, _HWND_TOPMOST, 0, 0, 0, 0, _SWP_FLAGS
            )
        else:
            user32.SetWindowPos(
                hwnd, _HWND_NOTOPMOST, 0, 0, 0, 0, _SWP_FLAGS
            )

            # NOTOPMOST alone leaves the window above the newly active app.
            user32.SetWindowPos(hwnd, foreground, 0, 0, 0, 0, _SWP_FLAGS)

    return foreground_pid


def _raise_resolve(
    foreground_pid, previous_pid, own_pid, resolve_hwnd, user32
):
    """Raise Resolve to the top of non-topmost windows when focus enters
    this process from another."""
    if foreground_pid == own_pid and previous_pid != own_pid:
        # Windows ignores HWND_TOP for a background process's window;
        # toggling topmost leaves it at the top of the non-topmost band.
        # Async, so this process never waits on Resolve's thread.
        flags = _SWP_FLAGS | _SWP_ASYNCWINDOWPOS
        user32.SetWindowPos(
            resolve_hwnd, _HWND_TOPMOST, 0, 0, 0, 0, flags
        )
        user32.SetWindowPos(
            resolve_hwnd, _HWND_NOTOPMOST, 0, 0, 0, 0, flags
        )


def _find_resolve_hwnd(user32, kernel32):
    """HWND of Resolve's main window, or None if it cannot be found.

    Matches on the owning process first, since the window title changes
    between Resolve versions and editions. Falls back to the title.
    """
    all_hwnds = _list_top_level_hwnds(user32)
    owned = _list_resolve_hwnds(user32, kernel32, all_hwnds)
    if owned:
        # Resolve can own floating viewers; the main window is the largest.
        return max(owned, key=partial(_get_window_area, user32=user32))

    return next(
        (
            hwnds[0]
            for title, hwnds in all_hwnds.items()
            if _is_resolve_title(title)
        ),
        None,
    )


def _on_resolve_exit():
    """Close every window and quit the application."""
    QtWidgets.QApplication.closeAllWindows()
    QtWidgets.QApplication.quit()


def _load_user32():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = wintypes.LONG
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    return user32


def _load_kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [
        wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def _install_window_management(menu, user32, kernel32):
    """Make the menu follow Resolve and close together with it.

    The menu runs in its own process, so it is only topmost while Resolve
    (or this process) is the foreground application.
    """
    resolve_hwnd = _find_resolve_hwnd(user32, kernel32)
    resolve_pid = (
        _get_pid_from_hwnd(resolve_hwnd, user32)
        if resolve_hwnd is not None
        else None
    )

    def monitor_resolve():
        if resolve_pid is not None:
            running = _is_pid_running(resolve_pid, kernel32)
        else:
            # Without a window there is no process to tie the menu to, so
            # it closes once no Resolve is left running.
            running = _any_resolve_running(user32, kernel32)

        if not running:
            _on_resolve_exit()

    # Started before the window check, so an unowned menu still closes
    # with Resolve instead of outliving it.
    exit_timer = QtCore.QTimer(menu)
    exit_timer.timeout.connect(monitor_resolve)
    exit_timer.start(1000)
    menu._exit_timer = exit_timer

    if resolve_hwnd is None:
        # Better a standalone menu than no menu at all.
        log.warning(
            "Could not find Resolve's main window, the OpenPype menu will "
            "not follow it."
        )
        return

    own_pid = os.getpid()
    owner_pids = {own_pid, resolve_pid}
    previous_pid = None

    def sync_topmost():
        nonlocal previous_pid
        hwnds = [
            int(widget.winId())
            for widget in QtWidgets.QApplication.topLevelWidgets()
            if widget.isVisible()
        ]
        foreground_pid = _sync_topmost(hwnds, owner_pids, user32)
        if foreground_pid is None:
            return
        _raise_resolve(
            foreground_pid, previous_pid, own_pid, resolve_hwnd, user32
        )
        previous_pid = foreground_pid

    topmost_timer = QtCore.QTimer(menu)
    topmost_timer.timeout.connect(sync_topmost)
    topmost_timer.start(250)
    menu._topmost_timer = topmost_timer


def load_stylesheet():
    path = os.path.join(os.path.dirname(__file__), "menu_style.qss")
    if not os.path.exists(path):
        print("Unable to load stylesheet, file not found in resources")
        return ""

    with open(path, "r") as file_stream:
        stylesheet = file_stream.read()
    return stylesheet


class Spacer(QtWidgets.QWidget):
    def __init__(self, height, *args, **kwargs):
        super(Spacer, self).__init__(*args, **kwargs)

        self.setFixedHeight(height)

        real_spacer = QtWidgets.QWidget(self)
        real_spacer.setObjectName("Spacer")
        real_spacer.setFixedHeight(height)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(real_spacer)

        self.setLayout(layout)


def _get_resolve_app_dirs():
    """Resolve's (preferences, support) directories, None if unknown."""
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        base = os.path.join(appdata, "Blackmagic Design", "DaVinci Resolve")
        return (
            os.path.join(base, "Preferences"), os.path.join(base, "Support")
        )
    if system == "Darwin":
        base = os.path.expanduser(
            "~/Library/Application Support/Blackmagic Design/DaVinci Resolve"
        )
        return (
            os.path.join(base, "Preferences"), os.path.join(base, "Support")
        )
    base = os.path.expanduser("~/.local/share/DaVinciResolve")
    return os.path.join(base, "Preferences"), base


def parse_dblist_roots(text):
    """Disk database roots listed in the text of Resolve's dblist.conf."""
    roots = []
    for line in text.splitlines():
        match = _DBLIST_DISK_RE.match(line.strip())
        if not match:
            continue
        path = match.group("path")
        path = _DBLIST_DRIVE_RE.sub(r"\1:\2", path, count=1)
        if path not in roots:
            roots.append(path)
    return roots


def get_project_library_roots(app_dirs=None):
    """Candidate disk database roots: dblist.conf entries + the defaults."""
    if app_dirs is None:
        app_dirs = _get_resolve_app_dirs()
    if not app_dirs:
        return []

    preferences_dir, support_dir = app_dirs
    roots = []
    try:
        with open(
            os.path.join(preferences_dir, "dblist.conf"),
            "r", encoding="utf-8", errors="replace"
        ) as stream:
            roots.extend(parse_dblist_roots(stream.read()))
    except OSError:
        log.debug("Could not read Resolve's dblist.conf.", exc_info=True)

    for name in ("Resolve Project Library", "Resolve Disk Database"):
        default_root = os.path.join(support_dir, name)
        if default_root not in roots:
            roots.append(default_root)
    return roots


def find_project_db(project_name, roots):
    """Path to the `Project.db` of a disk database project, or None.

    Projects live in
    `<root>/Resolve Projects/Users/<user>/Projects/[<folder>/...]/<name>`.
    If several match, the most recently modified one is returned.
    """
    candidates = []
    for root in roots:
        pattern = os.path.join(
            glob.escape(root),
            "Resolve Projects", "Users", "*", "Projects", "**",
            glob.escape(project_name), "Project.db"
        )
        candidates.extend(glob.glob(pattern, recursive=True))

    if not candidates:
        return None

    def _mtime(path):
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0

    return max(candidates, key=_mtime)


class ProjectDbLocator:
    """Finds `Project.db` of a project by name, caching the result."""

    def __init__(self, get_roots=get_project_library_roots):
        self._get_roots = get_roots
        self._cache = {}

    def __call__(self, project_name):
        cached = self._cache.get(project_name)
        if cached and os.path.exists(cached):
            return cached

        self._cache.pop(project_name, None)
        path = find_project_db(project_name, self._get_roots())
        if path:
            self._cache[project_name] = path
        return path


class WorkfileAutoExporter:
    """Exports the current project to its workfile when Resolve saved it.

    Resolve has no save callback, so `tick` is polled. A save is detected
    by `Project.db` becoming newer than the workfile `.drp`.

    All dependencies are injectable callables:
        get_project_name: () -> current project name or None.
        get_workfile_path: () -> path of the project's workfile or None.
        find_project_db: (project name) -> `Project.db` path or None.
        export: (workfile path) -> None, exports the project.
        clock: () -> current time in seconds.
        getmtime / exists: like `os.path.getmtime` / `os.path.exists`.
        on_exported: () -> None, called after an automatic export.
        get_db_type: () -> type of the current project database ('Disk',
            'PostgreSQL', ...) or None. Only disk databases have a
            `Project.db` to watch.
        on_unavailable: (reason) -> None, called when automatic export
            turns out to be impossible for the project. Only called when
            the project or reason changes.
        on_available: () -> None, called when automatic export becomes
            possible again after `on_unavailable`.
    """

    def __init__(
        self,
        get_project_name,
        get_workfile_path,
        find_project_db,
        export,
        clock=time.time,
        getmtime=os.path.getmtime,
        exists=os.path.exists,
        debounce=_AUTO_EXPORT_DEBOUNCE,
        min_interval=_AUTO_EXPORT_MIN_INTERVAL,
        on_exported=None,
        get_db_type=None,
        on_unavailable=None,
        on_available=None,
    ):
        self._get_project_name = get_project_name
        self._get_workfile_path = get_workfile_path
        self._find_project_db = find_project_db
        self._export = export
        self._clock = clock
        self._getmtime = getmtime
        self._exists = exists
        self._debounce = debounce
        self._min_interval = min_interval
        self._on_exported = on_exported
        self._get_db_type = get_db_type
        self._on_unavailable = on_unavailable
        self._on_available = on_available

        self._project_name = None
        self._last_attempt_time = None
        self._last_db_mtime = None
        # Reason last reported through `on_unavailable` for the project.
        self._unavailable_reason = None
        # Whether `on_unavailable` was reported and not yet cleared, this
        # survives project switches so `on_available` can clear it.
        self._unavailable_reported = False

    def _switch_project(self, project_name):
        if project_name != self._project_name:
            self._project_name = project_name
            self._last_attempt_time = None
            self._last_db_mtime = None
            self._unavailable_reason = None

    def _set_unavailable_reason(self, reason):
        """Report availability of automatic export, only on changes.

        Args:
            reason (str or None): Why automatic export is impossible for
                the current project, None if it is possible.
        """
        if reason is None:
            self._unavailable_reason = None
            if self._unavailable_reported:
                self._unavailable_reported = False
                if self._on_available is not None:
                    self._on_available()
            return

        if reason == self._unavailable_reason:
            return
        self._unavailable_reason = reason
        self._unavailable_reported = True
        log.info(
            f"Automatic workfile export unavailable for project "
            f"'{self._project_name}': {reason}"
        )
        if self._on_unavailable is not None:
            self._on_unavailable(reason)

    def record_export(self):
        """Remember a just finished export (also a manual one).

        Exporting can touch `Project.db`, which must not trigger another
        export.
        """
        try:
            project_name = self._get_project_name()
            if not project_name or project_name == _UNTITLED_PROJECT:
                return
            self._switch_project(project_name)
            self._last_attempt_time = self._clock()
            db_path = self._find_project_db(project_name)
            if db_path:
                self._last_db_mtime = self._getmtime(db_path)
        except Exception:
            log.warning(
                "Could not record workfile export state.", exc_info=True
            )

    def tick(self):
        """Export if needed, returns True if the workfile was exported.

        Never raises, so a timer driving it keeps running.
        """
        try:
            return self._tick()
        except Exception:
            log.warning("Automatic workfile export failed.", exc_info=True)
            return False

    def _tick(self):
        project_name = self._get_project_name()
        if not project_name or project_name == _UNTITLED_PROJECT:
            return False
        self._switch_project(project_name)

        workfile_path = self._get_workfile_path()
        # Only projects already saved once through the pipeline are exported.
        if not workfile_path or not self._exists(workfile_path):
            return False

        db_type = self._get_db_type() if self._get_db_type else None
        if db_type and str(db_type).lower() != "disk":
            self._set_unavailable_reason(f"{db_type} database")
            return False

        db_path = self._find_project_db(project_name)
        if not db_path:
            self._set_unavailable_reason("local project file not found")
            return False
        self._set_unavailable_reason(None)

        db_mtime = self._getmtime(db_path)
        # A newer workfile can come from a colleague through the file sync,
        # never overwrite it.
        if db_mtime <= self._getmtime(workfile_path):
            return False
        # Export itself may have touched the db.
        if db_mtime == self._last_db_mtime:
            return False

        now = self._clock()
        if now - db_mtime < self._debounce:
            return False
        if (
            self._last_attempt_time is not None
            and now - self._last_attempt_time < self._min_interval
        ):
            return False

        # Set before exporting so a failure backs off as well.
        self._last_attempt_time = now
        log.info(f"Project changed, exporting workfile: {workfile_path}")
        self._export(workfile_path)
        self.record_export()
        if self._on_exported is not None:
            self._on_exported()
        return True


def _get_current_project_name():
    from openpype.hosts.resolve.api.lib import get_current_project

    project = get_current_project()
    return project.GetName() if project else None


def _get_current_db_type():
    from openpype.hosts.resolve.api.lib import get_project_manager

    database = get_project_manager().GetCurrentDatabase()
    return database.get("DbType") if database else None


def _get_current_workfile_path():
    return registered_host().get_current_workfile()


def _export_workfile(filepath):
    registered_host().save_workfile(filepath)


def _install_auto_export(menu):
    """Periodically export the project to its workfile, see
    `WorkfileAutoExporter`."""
    exporter = WorkfileAutoExporter(
        get_project_name=_get_current_project_name,
        get_workfile_path=_get_current_workfile_path,
        find_project_db=ProjectDbLocator(),
        export=_export_workfile,
        on_exported=lambda: menu.set_save_status("Auto-saved"),
        get_db_type=_get_current_db_type,
        on_unavailable=menu.set_auto_save_warning,
        on_available=lambda: menu.set_auto_save_warning(None),
    )
    menu.auto_exporter = exporter

    timer = QtCore.QTimer(menu)
    timer.timeout.connect(exporter.tick)
    timer.start(_AUTO_EXPORT_INTERVAL_MS)
    menu._auto_export_timer = timer


class OpenPypeMenu(QtWidgets.QWidget):
    def __init__(self, *args, **kwargs):
        super(OpenPypeMenu, self).__init__(*args, **kwargs)

        self.setObjectName("OpenPypeMenu")

        flags = (
            QtCore.Qt.Window
            | QtCore.Qt.CustomizeWindowHint
            | QtCore.Qt.WindowTitleHint
            | QtCore.Qt.WindowCloseButtonHint
        )
        if platform.system() != "Windows":
            # On Windows the topmost state is managed dynamically so the
            # menu only sits above Resolve, see _install_window_management.
            flags |= QtCore.Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)

        self.setWindowTitle("OpenPype")
        self.auto_exporter = None
        self._auto_save_warning = None
        self._save_status = ""
        save_current_btn = QtWidgets.QPushButton("Save current file", self)
        workfiles_btn = QtWidgets.QPushButton("Workfiles ...", self)
        # Temporary disable buttons while not fully tested.
        """
        create_btn = QtWidgets.QPushButton("Create ...", self)
        publish_btn = QtWidgets.QPushButton("Publish ...", self)
        load_btn = QtWidgets.QPushButton("Load ...", self)
        inventory_btn = QtWidgets.QPushButton("Manager ...", self)
        subsetm_btn = QtWidgets.QPushButton("Subset Manager ...", self)
        libload_btn = QtWidgets.QPushButton("Library ...", self)
        experimental_btn = QtWidgets.QPushButton(
            "Experimental tools ...", self
        )
        # rename_btn = QtWidgets.QPushButton("Rename", self)
        # set_colorspace_btn = QtWidgets.QPushButton(
        #     "Set colorspace from presets", self
        # )
        # reset_resolution_btn = QtWidgets.QPushButton(
        #     "Set Resolution from presets", self
        # )
        """

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 20, 10, 20)

        layout.addWidget(save_current_btn)

        self._save_status_label = QtWidgets.QLabel("", self)
        self._save_status_label.setObjectName("SaveStatus")
        self._save_status_label.setAlignment(QtCore.Qt.AlignCenter)
        self._save_status_label.setWordWrap(True)
        self._save_status_label.setStyleSheet(_SAVE_STATUS_STYLE)
        layout.addWidget(self._save_status_label)

        layout.addWidget(Spacer(15, self))

        layout.addWidget(workfiles_btn)
        # Temporary disable buttons while not fully tested.
        """
        layout.addWidget(create_btn)
        layout.addWidget(publish_btn)
        layout.addWidget(load_btn)
        layout.addWidget(inventory_btn)
        layout.addWidget(subsetm_btn)

        layout.addWidget(Spacer(15, self))

        layout.addWidget(libload_btn)

        # layout.addWidget(Spacer(15, self))

        # layout.addWidget(rename_btn)

        # layout.addWidget(Spacer(15, self))

        # layout.addWidget(set_colorspace_btn)
        # layout.addWidget(reset_resolution_btn)
        layout.addWidget(Spacer(15, self))
        layout.addWidget(experimental_btn)
        """

        self.setLayout(layout)

        save_current_btn.clicked.connect(self.on_save_current_clicked)
        save_current_btn.setShortcut(QtGui.QKeySequence.Save)
        workfiles_btn.clicked.connect(self.on_workfile_clicked)
        # Temporary disable buttons while not fully tested.
        """
        create_btn.clicked.connect(self.on_create_clicked)
        publish_btn.clicked.connect(self.on_publish_clicked)
        load_btn.clicked.connect(self.on_load_clicked)
        inventory_btn.clicked.connect(self.on_inventory_clicked)
        subsetm_btn.clicked.connect(self.on_subsetm_clicked)
        libload_btn.clicked.connect(self.on_libload_clicked)
        # rename_btn.clicked.connect(self.on_rename_clicked)
        # set_colorspace_btn.clicked.connect(self.on_set_colorspace_clicked)
        # reset_resolution_btn.clicked.connect(self.on_set_resolution_clicked)
        experimental_btn.clicked.connect(self.on_experimental_clicked)
        """

    def on_save_current_clicked(self):
        host = registered_host()
        current_file = host.get_current_workfile()
        if not current_file:
            print("Current project is not saved. "
                  "Please save once first via workfiles tool.")
            host_tools.show_workfiles()
            return

        print(f"Saving current file to: {current_file}")
        host.save_workfile(current_file)
        if self.auto_exporter is not None:
            self.auto_exporter.record_export()
        self.set_save_status("Saved")

    def set_save_status(self, prefix):
        """Show '<prefix> HH:MM' under the save button."""
        self._save_status = "{} {}".format(prefix, time.strftime("%H:%M"))
        self._update_save_status_label()

    def set_auto_save_warning(self, reason):
        """Warn that auto-save is unavailable, None clears the warning."""
        self._auto_save_warning = (
            "Auto-save off ({}) - use Save current file".format(reason)
            if reason else None
        )
        self._update_save_status_label()

    def _update_save_status_label(self):
        label = self._save_status_label
        if not self._auto_save_warning:
            label.setText(self._save_status)
            label.setToolTip("")
            label.setStyleSheet(_SAVE_STATUS_STYLE)
            return

        lines = [self._save_status] if self._save_status else []
        lines.append(self._auto_save_warning)
        label.setText("\n".join(lines))
        label.setToolTip(
            "Resolve's automatic export of the project to the .drp "
            "workfile only works with local disk databases.\n"
            "Save the .drp manually with the 'Save current file' button."
        )
        label.setStyleSheet(_SAVE_STATUS_WARNING_STYLE)

    def on_workfile_clicked(self):
        print("Clicked Workfile")
        host_tools.show_workfiles()

    def on_create_clicked(self):
        print("Clicked Create")
        host_tools.show_creator()

    def on_publish_clicked(self):
        print("Clicked Publish")
        host_tools.show_publish(parent=None)

    def on_load_clicked(self):
        print("Clicked Load")
        host_tools.show_loader(use_context=True)

    def on_inventory_clicked(self):
        print("Clicked Inventory")
        host_tools.show_scene_inventory()

    def on_subsetm_clicked(self):
        print("Clicked Subset Manager")
        host_tools.show_subset_manager()

    def on_libload_clicked(self):
        print("Clicked Library")
        host_tools.show_library_loader()

    def on_rename_clicked(self):
        print("Clicked Rename")

    def on_set_colorspace_clicked(self):
        print("Clicked Set Colorspace")

    def on_set_resolution_clicked(self):
        print("Clicked Set Resolution")

    def on_experimental_clicked(self):
        host_tools.show_experimental_tools_dialog()


def launch_pype_menu():
    app = (
        QtWidgets.QApplication.instance()
        or QtWidgets.QApplication(sys.argv)
    )

    pype_menu = OpenPypeMenu()

    stylesheet = load_stylesheet()
    pype_menu.setStyleSheet(stylesheet)

    pype_menu.show()

    _install_auto_export(pype_menu)

    if platform.system() == "Windows":
        _install_window_management(
            pype_menu, _load_user32(), _load_kernel32()
        )

    sys.exit(app.exec_())
