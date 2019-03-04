# api.py
import os
import sys
import tempfile

import pico
from pico import PicoApp
# from pico.decorators import request_args, set_cookie, delete_cookie, stream
# from pico.decorators import header, cookie
#
# from werkzeug.exceptions import Unauthorized, ImATeapot, BadRequest

from avalon import api as avalon
# from avalon import io
#
# import pyblish.api as pyblish

from app.api import forward
from pype import api as pype


log = pype.Logger.getLogger(__name__, "aport")


SESSION = avalon.session
# if not SESSION:
#     io.install()

log.warning(os.getenv('AVALON_WORKDIR').replace("\\", "/"))


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

    log.info("avalon.session is: \n{}".format(SESSION))
    log.info("PUBLISH_PATH: \n{}".format(os.environ["PUBLISH_PATH"]))

    pype_start = os.path.join(os.getenv('PYPE_SETUP_ROOT'),
                              "app", "pype-start.py")

    publish = "--publish-gui" if gui else "--publish"

    args = [pype_start, "--publish-gui",
            "-pp", os.environ["PUBLISH_PATH"],
            "-d", "rqst_json_data_path", send_json_path,
            "-d", "post_json_data_path", get_json_path
            ]

    log.debug(args)
    # cwd = os.path.normpath(cwd)
    # if os.path.exists(cwd):
    #     log.warning("cwd this path exists")
    #     log.warning(cwd)
    # start standalone pyblish qml
    forward([
        sys.executable, "-u"
    ] + args,
        # cwd=cwd
    )

    return {"get_json_path": get_json_path}


@pico.expose()
def context(project, asset, task, app):
    # http://localhost:4242/pipeline/context?project=this&asset=shot01&task=comp

    os.environ["AVALON_PROJECT"] = project

    avalon.update_current_task(task, asset, app)

    project_code = pype.get_project_code()
    pype.set_project_code(project_code)
    hierarchy = pype.get_hierarchy()
    pype.set_hierarchy(hierarchy)
    fix_paths = {k: v.replace("\\", "/") for k, v in SESSION.items()
                 if isinstance(v, str)}
    SESSION.update(fix_paths)
    SESSION.update({"AVALON_HIERARCHY": hierarchy,
                    "AVALON_PROJECTCODE": project_code,
                    "current_dir": os.getcwd().replace("\\", "/")
                    })

    return SESSION


@pico.expose()
def anatomy_fill(data):
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


app = PicoApp()
app.register_module(__name__)

# remove all Handlers created by pico
for name, handler in [(handler.get_name(), handler)
                      for handler in pype.Logger.logging.root.handlers[:]]:
    if "pype" not in str(name).lower():
        print(name)
        print(handler)
        pype.Logger.logging.root.removeHandler(handler)
