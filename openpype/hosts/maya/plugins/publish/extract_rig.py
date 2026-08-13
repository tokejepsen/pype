# -*- coding: utf-8 -*-
"""Extract rig as Maya Scene."""
import os

from maya import cmds

from openpype.pipeline import publish
from openpype.hosts.maya.api.lib import (
    maintained_selection,
    remove_namespaces_from_file,
)
from openpype.lib import BoolDef, TextDef
from openpype.pipeline.publish import OpenPypePyblishPluginMixin


class ExtractRig(publish.Extractor, OpenPypePyblishPluginMixin):
    """Extract rig as Maya Scene."""

    label = "Extract Rig (Maya Scene)"
    hosts = ["maya"]
    families = ["rig"]
    scene_type = "ma"
    preserve_references = False
    namespaces_to_remove = ""

    @classmethod
    def get_attribute_defs(cls):
        return [
            BoolDef(
                "preserve_references",
                label="Preserve References",
                tooltip=(
                    "Keep references as references in the published rig "
                    "instead of importing (flattening) them into the file."
                ),
                default=cls.preserve_references
            ),
            TextDef(
                "namespaces_to_remove",
                label="Namespaces to Remove",
                default=cls.namespaces_to_remove,
                placeholder="namespace1, namespace2"
            )
        ]

    def process(self, instance):
        """Plugin entry point."""
        ext_mapping = (
            instance.context.data["project_settings"]["maya"]["ext_mapping"]
        )
        if ext_mapping:
            self.log.debug("Looking in settings for scene type ...")
            # use extension mapping for first family found
            for family in self.families:
                try:
                    self.scene_type = ext_mapping[family]
                    self.log.debug(
                        "Using '.{}' as scene type".format(self.scene_type))
                    break
                except AttributeError:
                    # no preset found
                    pass
        # Define extract output file path
        dir_path = self.staging_dir(instance)
        filename = "{0}.{1}".format(instance.name, self.scene_type)
        path = os.path.join(dir_path, filename)

        # Get attribute values
        attribute_values = self.get_attr_values_from_data(instance.data)
        preserve_references = attribute_values.get(
            "preserve_references", self.preserve_references
        )

        # Perform extraction
        self.log.debug("Performing extraction ...")
        with maintained_selection():
            cmds.select(instance, noExpand=True)
            cmds.file(path,
                      force=True,
                      typ="mayaAscii" if self.scene_type == "ma" else "mayaBinary",  # noqa: E501
                      exportSelected=True,
                      preserveReferences=preserve_references,
                      channels=True,
                      constraints=True,
                      expressions=True,
                      constructionHistory=True)
        namespaces_to_remove = attribute_values.get("namespaces_to_remove", "")
        namespaces_to_remove = [s.strip() for s in namespaces_to_remove.split(",") if s]
        if namespaces_to_remove:
            remove_namespaces_from_file(path, namespaces_to_remove)

        if "representations" not in instance.data:
            instance.data["representations"] = []

        representation = {
            'name': self.scene_type,
            'ext': self.scene_type,
            'files': filename,
            "stagingDir": dir_path
        }
        instance.data["representations"].append(representation)

        self.log.debug("Extracted instance '%s' to: %s", instance.name, path)
