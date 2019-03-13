# api.py
import os
import sys
import getpass
import pico
from pico import PicoApp
from app.api import forward, Logger
from io_nonsingleton import DbConnector

io = DbConnector()
log = Logger.getLogger(__name__, "aport")
_registered_root = {"_": ""}
self = sys.modules[__name__]
self.SESSION = None

self.AVALON_PROJECT = os.getenv("AVALON_PROJECT", None)
self.AVALON_ASSET = os.getenv("AVALON_ASSET", None)
self.AVALON_TASK = os.getenv("AVALON_TASK", None)
self.AVALON_SILO = os.getenv("AVALON_SILO", None)


@pico.expose()
def get_session():
    # self.SESSION = avalon.session
    if not self.SESSION:
        os.environ["AVALON_PROJECT"] = self.AVALON_PROJECT
        os.environ["AVALON_ASSET"] = self.AVALON_ASSET
        os.environ["AVALON_TASK"] = self.AVALON_TASK
        os.environ["AVALON_SILO"] = self.AVALON_SILO
        io.install()
        self.SESSION = io.Session

    return self.SESSION


@pico.expose()
def publish(send_json_path, get_json_path, gui):
    """
    Runs standalone pyblish and adds link to
    data in external json file

    It is necessary to run `register_plugin_path` if particular
    host is needed

    Args:
        send_json_path (string): path to temp json file with
                                sending context data
        get_json_path (strign): path to temp json file with
                                returning context data

    Returns:
        dict: get_json_path

    Raises:
        Exception: description

    """

    log.info("avalon.session is: \n{}".format(self.SESSION))
    log.info("PUBLISH_PATH: \n{}".format(os.environ["PUBLISH_PATH"]))

    pype_start = os.path.join(os.getenv('PYPE_SETUP_ROOT'),
                              "app", "pype-start.py")

    args = [pype_start, "--publish-gui",
            "-pp", os.environ["PUBLISH_PATH"],
            "-d", "rqst_json_data_path", send_json_path,
            "-d", "post_json_data_path", get_json_path
            ]

    log.debug(args)

    forward([
        sys.executable, "-u"
    ] + args,
        # cwd=cwd
    )

    return {"get_json_path": get_json_path}


@pico.expose()
def context(project, asset, task, app):
    os.environ["AVALON_PROJECT"] = self.AVALON_PROJECT = project
    os.environ["AVALON_ASSET"] = self.AVALON_ASSET = asset
    os.environ["AVALON_TASK"] = self.AVALON_TASK = task
    os.environ["AVALON_SILO"] = self.AVALON_SILO = ''

    get_session()
    log.info('self.SESSION: {}'.format(self.SESSION))

    # http://localhost:4242/pipeline/context?project=this&asset=shot01&task=comp

    update_current_task(task, asset, app)

    project_code = io.find_one({"type": "project"})["data"].get("code", '')

    os.environ["AVALON_PROJECTCODE"] = self.SESSION["AVALON_PROJECTCODE"] = project_code

    parents = io.find_one({"type": 'asset',
                           "name": self.AVALON_ASSET})['data']['parents']

    if parents and len(parents) > 0:
        # hierarchy = os.path.sep.join(hierarchy)
        hierarchy = os.path.join(*parents).replace("\\", "/")

    os.environ["AVALON_HIERARCHY"] = self.SESSION["AVALON_HIERARCHY"] = hierarchy

    fix_paths = {k: v.replace("\\", "/") for k, v in self.SESSION.items()
                 if isinstance(v, str)}

    self.SESSION.update(fix_paths)
    self.SESSION.update({"AVALON_HIERARCHY": hierarchy,
                         "AVALON_PROJECTCODE": project_code,
                         "current_dir": os.getcwd().replace("\\", "/")
                         })

    return self.SESSION


@pico.expose()
def anatomy_fill(data):
    from pype import api as pype
    pype.load_data_from_templates()
    anatomy = pype.Anatomy
    return anatomy.format(data)


@pico.expose()
def deregister_plugin_path():
    if os.getenv("PUBLISH_PATH", None):
        aport_plugin_path = os.pathsep.join(
            [p.replace("\\", "/")
             for p in os.environ["PUBLISH_PATH"].split(os.pathsep)
             if "aport" in p
             or "ftrack" in p])
        os.environ["PUBLISH_PATH"] = aport_plugin_path
    else:
        log.warning("deregister_plugin_path(): No PUBLISH_PATH is registred")

    return "Publish path deregistered"


@pico.expose()
def register_plugin_path(publish_path):
    deregister_plugin_path()
    if os.getenv("PUBLISH_PATH", None):
        os.environ["PUBLISH_PATH"] = os.pathsep.join(
            os.environ["PUBLISH_PATH"].split(os.pathsep) +
            [publish_path.replace("\\", "/")]
        )
    else:
        os.environ["PUBLISH_PATH"] = publish_path

    log.info(os.environ["PUBLISH_PATH"].split(os.pathsep))

    return "Publish registered paths: {}".format(
        os.environ["PUBLISH_PATH"].split(os.pathsep)
    )


def update_current_task(task=None, asset=None, app=None):
    """Update active Session to a new task work area.

    This updates the live Session to a different `asset`, `task` or `app`.

    Args:
        task (str): The task to set.
        asset (str): The asset to set.
        app (str): The app to set.

    Returns:
        dict: The changed key, values in the current Session.

    """

    mapping = {
        "AVALON_ASSET": asset,
        "AVALON_TASK": task,
        "AVALON_APP": app,
    }
    changed = {key: value for key, value in mapping.items() if value}
    if not changed:
        return

    # Update silo when asset changed
    if "AVALON_ASSET" in changed:
        asset_document = io.find_one({"name": changed["AVALON_ASSET"],
                                      "type": "asset"})
        assert asset_document, "Asset must exist"
        silo = asset_document["silo"]
        if silo is None:
            silo = asset_document["name"]
        changed["AVALON_SILO"] = silo
        parents = asset_document['data']['parents']
        hierarchy = ""
        if len(parents) > 0:
            hierarchy = os.path.sep.join(parents)
        changed['AVALON_HIERARCHY'] = hierarchy

    # Compute work directory (with the temporary changed session so far)
    project = io.find_one({"type": "project"},
                          projection={"config.template.work": True})
    template = project["config"]["template"]["work"]
    _session = self.SESSION.copy()
    _session.update(changed)
    changed["AVALON_WORKDIR"] = _format_work_template(template, _session)

    # Update the full session in one go to avoid half updates
    self.SESSION.update(changed)

    # Update the environment
    os.environ.update(changed)

    return changed


def _format_work_template(template, session=None):
    """Return a formatted configuration template with a Session.

    Note: This *cannot* format the templates for published files since the
        session does not hold the context for a published file. Instead use
        `get_representation_path` to parse the full path to a published file.

    Args:
        template (str): The template to format.
        session (dict, Optional): The Session to use. If not provided use the
            currently active global Session.

    Returns:
        str: The fully formatted path.

    """
    if session is None:
        session = self.SESSION

    project = io.find_one({'type': 'project'})

    return template.format(**{
        "root": registered_root(),
        "project": {
            "name": project.get("name", session["AVALON_PROJECT"]),
            "code": project["data"].get("code", ''),
        },
        "silo": session["AVALON_SILO"],
        "hierarchy": session['AVALON_HIERARCHY'],
        "asset": session["AVALON_ASSET"],
        "task": session["AVALON_TASK"],
        "app": session["AVALON_APP"],
        "user": session.get("AVALON_USER", getpass.getuser())
    })


def registered_root():
    """Return currently registered root"""
    return os.path.normpath(
        _registered_root["_"] or
        self.SESSION.get("AVALON_PROJECTS") or ""
    )


app = PicoApp()
app.register_module(__name__)

# remove all Handlers created by pico
for name, handler in [(handler.get_name(), handler)
                      for handler in Logger.logging.root.handlers[:]]:
    if "pype" not in str(name).lower():
        Logger.logging.root.removeHandler(handler)
