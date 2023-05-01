import os

from openpype.lib.attribute_definitions import FileDef, EnumDef
from openpype.hosts.traypublisher.api.plugin import TrayPublishCreator
from openpype.pipeline import (
    CreatedInstance,
    CreatorError
)


class TranscodeCreator(TrayPublishCreator):
    """Creates a transcode of the input editorial file."""

    identifier = "transcode"
    label = "Transcode"
    family = "transcode"
    description = "Transcode an editorial file."
    editorial_extensions = [".xml", ".otio"]
    audio_extensions = [".wav"]

    def apply_settings(self, project_settings, system_settings):
        creator_settings = (
            project_settings["traypublisher"]["create"]["TranscodeCreator"]
        )
        self.presets = creator_settings["presets"]
        self.preset_names = []
        for key in self.presets.keys():
            self.preset_names.append({"value": key, "label": key})

    def get_detail_description(self):
        return """# Transcode an editorial file.

        This will transcode an editorial file to the destination file format
        and codec.
        """

    def get_icon(self):
        return "fa.copy"

    def create(self, subset_name, instance_data, pre_create_data):
        editorial_file = None
        if pre_create_data["editorial_file"]["filenames"]:
            editorial_file = os.path.join(
                pre_create_data["editorial_file"]["directory"],
                pre_create_data["editorial_file"]["filenames"][0]
            )
        else:
            raise CreatorError("No editorial file specified.")

        audio_file = None
        if pre_create_data["audio_file"]["filenames"]:
            audio_file = os.path.join(
                pre_create_data["audio_file"]["directory"],
                pre_create_data["audio_file"]["filenames"][0]
            )

        preset = self.presets[pre_create_data["preset"]]
        instance_data["creator_attributes"] = {
            "editorial_file": editorial_file,
            "audio_file": audio_file,
            "arguments": preset["arguments"],
            "output_extension": preset["output_extension"]
        }

        new_instance = CreatedInstance(
            self.family, subset_name, instance_data, self
        )
        self._store_new_instance(new_instance)

    def get_pre_create_attr_defs(self):
        return [
            FileDef(
                "editorial_file",
                folders=False,
                extensions=self.editorial_extensions,
                allow_sequences=False,
                single_item=True,
                label="Editorial File",
            ),
            FileDef(
                "audio_file",
                folders=False,
                extensions=self.audio_extensions,
                allow_sequences=False,
                single_item=True,
                label="Audio File",
            ),
            EnumDef(
                "preset",
                items=self.preset_names,
                label="Preset"
            )
        ]
