import pyblish.api
from openpype.hosts.tvpaint.api.lib import execute_george


class SaveCurrentScene(pyblish.api.ContextPlugin):
    """Save current scene"""

    label = "Save current file"
    order = pyblish.api.ExtractorOrder - 0.49
    hosts = ["tvpaint"]
    families = ["workfile"]

    def process(self, context):
        filepath = context.data["currentFile"]
        george_script = "tv_SaveProject {}".format(filepath.replace("\\", "/"))
        execute_george(george_script)