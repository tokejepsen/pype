import os

import pyblish.api
from openpype.pipeline import OpenPypePyblishPluginMixin


class CollectTranscode(pyblish.api.InstancePlugin, OpenPypePyblishPluginMixin):
    """Collect Transcode"""

    order = pyblish.api.CollectorOrder
    label = "Collect Transcode"
    hosts = ["traypublisher"]
    families = ["transcode"]

    def process(self, instance):
        creator_attributes = instance.data["creator_attributes"]

        editorial_path = creator_attributes["editorial_file"]
        _, ext = os.path.splitext(editorial_path)
        representation = {
            "name": ext[1:],
            "ext": ext,
            "files": os.path.basename(editorial_path),
            "stagingDir": os.path.dirname(editorial_path),
        }
        self.log.info(representation)
        instance.data["representations"].append(representation)

        audio_path = creator_attributes["audio_file"]
        if audio_path:
            representation = {
                "name": "audio",
                "ext": os.path.splitext(audio_path)[1],
                "files": os.path.basename(audio_path),
                "stagingDir": os.path.dirname(audio_path),
            }
            self.log.info(representation)
            instance.data["representations"].append(representation)
