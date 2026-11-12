from collections import defaultdict
from functools import partial
import os
import platform
import re
import sys

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

    if platform.system() == "Windows":
        _install_window_management(
            pype_menu, _load_user32(), _load_kernel32()
        )

    sys.exit(app.exec_())
