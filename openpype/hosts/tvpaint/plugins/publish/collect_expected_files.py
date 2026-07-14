import os
import pyblish.api

from openpype.pipeline.publish import get_instance_staging_dir
from openpype.hosts.tvpaint.lib import get_frame_filename_template


class CollectExpectedFiles(pyblish.api.InstancePlugin):
    """Collect expected output files for TVPaint render instances.

    Sets a preliminary list of expected PNG files on farm instances.
    This ensures that expectedFiles is always populated before submission,
    preventing AssertionError in ProcessSubmittedJobOnFarm if the
    SubmitTVPaintDeadline plugin fails or is skipped.

    The SubmitTVPaintDeadline plugin will later overwrite this with the
    authoritative file paths using the resolved output directory.
    """

    label = "Collect Expected Files"
    order = pyblish.api.CollectorOrder + 0.5999
    hosts = ["tvpaint"]
    families = ["render"]

    def process(self, instance):
        # Only process farm instances
        if "render.farm" not in instance.data.get("families", []):
            return

        # Skip if already set (idempotent)
        if instance.data.get("expectedFiles"):
            self.log.debug(
                f"expectedFiles already set on {instance.data.get('subset')}, skipping"
            )
            return

        context = instance.context

        # Get scene frame range
        scene_mark_in = context.data.get("sceneMarkIn", 0)
        scene_mark_out = context.data.get("sceneMarkOut", 0)

        # Get instance frame range
        frame_start = instance.data.get("frameStart")
        frame_end = instance.data.get("frameEnd")

        if frame_start is None or frame_end is None:
            self.log.warning(
                f"Instance {instance.data.get('subset')} missing frameStart/frameEnd, "
                "skipping expectedFiles collection"
            )
            return

        # Compute mark_in/mark_out in TVPaint's render coordinate system
        # This matches the formula used in submit_tvpaint_deadline.py
        asset_doc = instance.data.get("assetEntity", {})
        project_frame_start = asset_doc.get("data", {}).get("frameStart", scene_mark_in)

        mark_in = int(scene_mark_in + (frame_start - project_frame_start))
        mark_out = int(scene_mark_in + (frame_end - project_frame_start))

        # Resolve preliminary output directory
        # Prefer instance.data["outputDir"] if set, otherwise use staging dir as placeholder
        output_dir = instance.data.get("outputDir")
        if not output_dir:
            output_dir = get_instance_staging_dir(instance)

        if not output_dir:
            self.log.warning(
                f"Could not resolve output directory for {instance.data.get('subset')}"
            )
            return

        # Build list of expected PNG files
        output_template = get_frame_filename_template(mark_out)
        expected_files = [
            os.path.join(output_dir, output_template.format(frame=frame_idx))
            for frame_idx in range(mark_in, mark_out + 1)
        ]

        instance.data["expectedFiles"] = expected_files

        self.log.info(
            f"Set expectedFiles for {instance.data.get('subset')}: "
            f"{len(expected_files)} files in {output_dir}"
        )
