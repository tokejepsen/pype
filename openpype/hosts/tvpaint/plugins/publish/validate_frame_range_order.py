import pyblish.api
from openpype.pipeline import (
    PublishValidationError,
    OptionalPyblishPluginMixin,
)


class ValidateFrameRangeOrder(
    OptionalPyblishPluginMixin,
    pyblish.api.InstancePlugin
):
    """Validate that frameStart is not greater than frameEnd.

    Instances with inverted frame ranges (e.g., from stale creator_attributes)
    will be caught here and prevent publication. This prevents the error
    "Submission from old Pype version - missing expectedFiles" that occurs
    when an empty frame range produces zero expected output files.
    """

    label = "Validate Frame Range Order"
    order = pyblish.api.ValidatorOrder
    hosts = ["tvpaint"]
    families = ["render", "review"]
    optional = True

    def process(self, instance):
        if not self.is_active(instance.context.data):
            return

        frame_start = instance.data.get("frameStart")
        frame_end = instance.data.get("frameEnd")
        subset = instance.data.get("subset", "unknown")

        # Skip if frame range not yet set
        if frame_start is None or frame_end is None:
            return

        # Validate frame order: frameStart must not be greater than frameEnd
        if frame_start > frame_end:
            raise PublishValidationError(
                "Instance '{}': frameStart ({}) cannot be greater than frameEnd ({})".format(
                    subset, frame_start, frame_end
                )
            )
