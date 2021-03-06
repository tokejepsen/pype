import pyblish.api


class ValidateVersion(pyblish.api.InstancePlugin):
    """Validate instance version.

    Pype is not allowing overwiting previously published versions.
    """

    order = pyblish.api.ValidatorOrder

    label = "Validate Version"
    hosts = ["nuke", "maya", "blender"]

    def process(self, instance):
        version = instance.data.get("version")
        latest_version = instance.data.get("latestVersion")

        if latest_version is not None:
            msg = ("Version `{0}` that you are"
                   " trying to publish, already"
                   " exists in the"
                   " database.").format(
                   version, latest_version)
            assert (int(version) > int(latest_version)), msg
