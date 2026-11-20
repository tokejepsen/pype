"""Host API required Work Files tool"""

import os
import re
import zipfile
from datetime import datetime, timezone
from openpype.lib import Logger
from .lib import (
    get_project_manager,
    get_current_project
)


log = Logger.get_logger(__name__)

_DRP_APP_VERSION_RE = re.compile(rb'DbAppVer="([\d.]+)"')
_DRP_LAST_MODIFIED_RE = re.compile(
    rb"<LastModTimeInSecs>\s*(\d+)\s*</LastModTimeInSecs>"
)
_qt_app = None


def _get_qt_app():
    global _qt_app
    from qtpy import QtWidgets

    _qt_app = (
        QtWidgets.QApplication.instance()
        or QtWidgets.QApplication([])
    )
    return _qt_app


def _show_critical(message):
    from qtpy import QtWidgets

    _get_qt_app()
    QtWidgets.QMessageBox.critical(None, "OpenPype", message)


def _format_timestamp(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _ask_drp_newer(fname, local_ts, drp_ts):
    """Ask what to do when the workfile is newer than the Resolve project.

    Returns "local", "replace" or "cancel".
    """
    from qtpy import QtWidgets

    _get_qt_app()
    box = QtWidgets.QMessageBox(None)
    box.setIcon(QtWidgets.QMessageBox.Warning)
    box.setWindowTitle("OpenPype")
    box.setText(
        f'The workfile on disk for "{fname}" is newer than the copy in '
        "the Resolve database.\n\n"
        f"Resolve database: {_format_timestamp(local_ts)}\n"
        f"Workfile on disk: {_format_timestamp(drp_ts)}\n\n"
        '"Replace local with workfile" keeps the current Resolve project '
        f'as a backup project named "{fname}_backup_<timestamp>".'
    )
    open_local = box.addButton(
        "Open local", QtWidgets.QMessageBox.AcceptRole
    )
    replace = box.addButton(
        "Replace local with workfile", QtWidgets.QMessageBox.DestructiveRole
    )
    cancel = box.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)
    box.setEscapeButton(cancel)
    box.exec_()

    clicked = box.clickedButton()
    if clicked == open_local:
        return "local"
    if clicked == replace:
        return "replace"
    return "cancel"


def _read_drp_last_modified(filepath):
    """Return the last modified time (epoch seconds) stored in a drp.

    Returns None if it is unknown.
    """
    try:
        with zipfile.ZipFile(filepath) as archive:
            with archive.open("project.xml") as project_xml:
                content = project_xml.read()
    except (OSError, KeyError, zipfile.BadZipFile):
        log.debug(
            f"Could not read last modified time from {filepath}",
            exc_info=True
        )
        return None
    match = _DRP_LAST_MODIFIED_RE.search(content)
    return int(match.group(1)) if match else None


def _get_local_project_info(pm, fname):
    """Return (exists, last modified epoch seconds) of a project in the DB.

    `exists` is False when it is unknown, e.g. on Resolve versions without
    `GetProjectAttributesInCurrentFolder`.
    """
    try:
        attributes = pm.GetProjectAttributesInCurrentFolder()
    except Exception:
        attributes = None
    if not isinstance(attributes, dict) or fname not in attributes:
        return False, None

    try:
        value = attributes[fname]["lastModifiedDate"]
        local_ts = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).astimezone(timezone.utc).timestamp()
    except (KeyError, TypeError, ValueError, AttributeError):
        log.debug(
            f"Could not read last modified date of `{fname}`", exc_info=True
        )
        return True, None
    return True, local_ts


def _replace_local_project(pm, fname, filepath):
    """Import the workfile over the local project, keeping a local backup."""
    backup_name = f"{fname}_backup_{datetime.now():%Y%m%d_%H%M%S}"
    try:
        project = pm.LoadProject(fname)
        if not project.SetName(backup_name):
            raise RuntimeError(f"Failed to rename project to {backup_name}")
        if not pm.SaveProject():
            raise RuntimeError("Failed to save renamed project")
        pm.CloseProject(project)
        if not pm.ImportProject(filepath):
            raise RuntimeError(f'Resolve failed to import "{filepath}"')
        project = pm.LoadProject(fname)
        log.info(
            f"Project replaced from {filepath}, previous project kept as "
            f"`{backup_name}`. Loaded {project.GetName()}..."
        )
    except Exception as exc:
        message = (
            f'Failed to replace local project "{fname}" with the workfile: '
            f"{exc}"
        )
        log.error(message, exc_info=True)
        _show_critical(message)
        return False
    return True


def _read_drp_app_version(filepath):
    """Return the Resolve version a drp was saved with as an int tuple.

    Returns None if the version is unknown.
    """
    try:
        with zipfile.ZipFile(filepath) as archive:
            with archive.open("project.xml") as project_xml:
                header = project_xml.read(512)
    except (OSError, KeyError, zipfile.BadZipFile):
        log.debug(
            f"Could not read Resolve version from {filepath}", exc_info=True
        )
        return None
    match = _DRP_APP_VERSION_RE.search(header)
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split(b"."))


def file_extensions():
    return [".drp"]


def has_unsaved_changes():
    get_project_manager().SaveProject()
    return False


def save_file(filepath):
    pm = get_project_manager()
    file = os.path.basename(filepath)
    fname, _ = os.path.splitext(file)
    project = get_current_project()
    name = project.GetName()

    response = False
    if name == "Untitled Project":
        response = pm.CreateProject(fname)
        log.info("New project created: {}".format(response))
        pm.SaveProject()
    elif name != fname:
        response = project.SetName(fname)
        log.info("Project renamed: {}".format(response))

    exported = pm.ExportProject(fname, filepath)
    log.info("Project exported: {}".format(exported))


def open_file(filepath):
    """
    Loading project
    """

    from . import bmdvr

    pm = get_project_manager()
    page = bmdvr.GetCurrentPage()
    if page is not None:
        # Save current project only if Resolve has an active page, otherwise
        # we consider Resolve being in a pre-launch state (no open UI yet)
        project = pm.GetCurrentProject()
        print(f"Saving current project: {project}")
        pm.SaveProject()

    file = os.path.basename(filepath)
    fname, _ = os.path.splitext(file)

    exists, local_ts = _get_local_project_info(pm, fname)
    if exists:
        drp_ts = _read_drp_last_modified(filepath)
        if local_ts is None or drp_ts is None:
            log.info(
                f"Could not compare timestamps of `{fname}` (local: "
                f"{local_ts}, workfile: {drp_ts}), opening local project."
            )
        elif drp_ts <= local_ts:
            log.info(f"Local project `{fname}` is up to date.")
        else:
            log.info(f"Workfile of `{fname}` is newer than local project.")
            choice = _ask_drp_newer(fname, local_ts, drp_ts)
            if choice == "cancel":
                return False
            if choice == "replace":
                return _replace_local_project(pm, fname, filepath)

    try:
        # load project from input path
        project = pm.LoadProject(fname)
        log.info(f"Project {project.GetName()} opened...")

    except AttributeError:
        log.warning((f"Project with name `{fname}` does not exist! It will "
                     f"be imported from {filepath} and then loaded..."))
        if pm.ImportProject(filepath):
            # load project from input path
            project = pm.LoadProject(fname)
            log.info(f"Project imported/loaded {project.GetName()}...")
            return True

        message = f'Resolve failed to import "{filepath}".'
        drp_version = _read_drp_app_version(filepath)
        if drp_version:
            running_version = None
            try:
                running_version = tuple(
                    int(part) for part in bmdvr.GetVersion()[:3]
                )
            except Exception:
                log.debug("Could not get running Resolve version.",
                          exc_info=True)
            if running_version and drp_version[:3] > running_version:
                message += (
                    "\n\nThe workfile was saved with DaVinci Resolve "
                    f"{'.'.join(map(str, drp_version[:3]))}, but Resolve "
                    f"{'.'.join(map(str, running_version))} is running. "
                    "Resolve cannot open projects saved with a newer "
                    "version."
                )
        log.error(message)

        _show_critical(message)
        return False
    return True


def current_file():
    pm = get_project_manager()
    file_ext = file_extensions()[0]
    workdir_path = os.getenv("AVALON_WORKDIR")
    project = pm.GetCurrentProject()
    project_name = project.GetName()
    file_name = project_name + file_ext

    # create current file path
    current_file_path = os.path.join(workdir_path, file_name)

    # return current file path if it exists
    return os.path.normpath(current_file_path)


def work_root(session):
    return os.path.normpath(session["AVALON_WORKDIR"]).replace("\\", "/")
