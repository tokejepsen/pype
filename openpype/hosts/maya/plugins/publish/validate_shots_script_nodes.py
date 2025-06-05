from maya import cmds

import pyblish.api

from openpype.pipeline.publish import (
    OptionalPyblishPluginMixin,
    ValidateContentsOrder,
    PublishValidationError
)


class ValidateShotsSceneConfigurationScriptNode(
    pyblish.api.ContextPlugin, OptionalPyblishPluginMixin
):
    """Ensure script nodes are correctly named for later extraction."""

    order = ValidateContentsOrder
    label = "Shots Scene Configuration Script Node"
    hosts = ["maya"]
    optional = True

    def process(self, context):
        for instance in context:
            if instance.data["family"] == "shot":
                break

            return

        if not cmds.objExists("sceneConfigurationScriptNode"):
            raise PublishValidationError(
                message=(
                    "`sceneConfigurationScriptNode` does not exist. Check"
                    " naming of nodes."
                ),
                description=(
                    "## Publishing Shots.\n"
                    "The `sceneConfigurationScriptNode` is not found."
                )
            )
