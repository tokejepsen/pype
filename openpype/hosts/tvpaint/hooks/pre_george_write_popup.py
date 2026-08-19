from openpype.hosts.tvpaint.lib import disable_george_write_popup
from openpype.lib.applications import PreLaunchHook, LaunchTypes


class TvpaintGeorgeWritePopup(PreLaunchHook):
    """Disable TVPaint's modal "Write to file" permission popup.

    OpenPype stores metadata through George file writes, which block on that
    popup.
    """

    app_groups = {"tvpaint"}
    launch_types = {LaunchTypes.local, LaunchTypes.farm_render}

    def execute(self):
        results = disable_george_write_popup()
        if not results:
            self.log.warning("No TVPaint config.ini found.")

        for config_path, key_found in results.items():
            if key_found:
                self.log.info(
                    "Disabled George write popup in \"{}\".".format(
                        config_path
                    )
                )
            else:
                self.log.warning(
                    "\"georgecanwritefiledisplaypopup\" not found in "
                    "\"{}\".".format(config_path)
                )
