"""Host API required Work Files tool"""

import os
import re
import zipfile
from openpype.lib import Logger
from .lib import (
    get_project_manager,
    get_current_project
)


log = Logger.get_logger(__name__)

_DRP_APP_VERSION_RE = re.compile(rb'DbAppVer="([\d.]+)"')
_qt_app = None


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

        from qtpy import QtWidgets

        global _qt_app
        _qt_app = (
            QtWidgets.QApplication.instance()
            or QtWidgets.QApplication([])
        )
        QtWidgets.QMessageBox.critical(None, "OpenPype", message)
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
