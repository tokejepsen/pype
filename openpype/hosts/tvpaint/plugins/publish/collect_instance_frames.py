import pyblish.api

from openpype.hosts.tvpaint.lib import calculate_instance_frame_data


class CollectOutputFrameRange(pyblish.api.InstancePlugin):
    """Resolve instance frame range in asset and scene space.

    This plugin is the single source of truth for per-instance frame
    ranges. It calls the shared helper to compute both asset-space
    values (frameStart, frameEnd, handleStart, handleEnd) and
    TVPaint scene-space values (instanceMarkIn, instanceMarkOut)
    and stores them on instance.data for downstream plugins.
    """

    label = "Collect output frame range"
    order = pyblish.api.CollectorOrder + 0.4999
    hosts = ["tvpaint"]
    families = ["review", "render"]

    def process(self, instance):
        asset_doc = instance.data.get("assetEntity")
        if not asset_doc:
            return

        context = instance.context

        creator_attributes = instance.data.get("creator_attributes") or {}
        frame_start = creator_attributes.get("frame_start")
        frame_end = creator_attributes.get("frame_end")

        asset_frame_start = asset_doc["data"]["frameStart"]

        handle_start = context.data.get("handleStart")
        if handle_start is None:
            handle_start = asset_doc["data"].get("handleStart", 0)

        handle_end = context.data.get("handleEnd")
        if handle_end is None:
            handle_end = asset_doc["data"].get("handleEnd", 0)

        scene_mark_in = context.data["sceneMarkIn"]
        scene_mark_out = context.data["sceneMarkOut"]

        frame_data = calculate_instance_frame_data(
            frame_start,
            frame_end,
            asset_frame_start,
            scene_mark_in,
            scene_mark_out,
            handle_start,
            handle_end
        )

        instance.data["fps"] = asset_doc["data"]["fps"]
        instance.data["frameStart"] = frame_data["frame_start"]
        instance.data["frameEnd"] = frame_data["frame_end"]
        instance.data["handleStart"] = frame_data["handle_start"]
        instance.data["handleEnd"] = frame_data["handle_end"]
        instance.data["frameStartHandle"] = frame_data["frame_start_handle"]
        instance.data["frameEndHandle"] = frame_data["frame_end_handle"]
        instance.data["instanceMarkIn"] = frame_data["mark_in"]
        instance.data["instanceMarkOut"] = frame_data["mark_out"]

        self.log.info(
            "Resolved {}: asset {}-{}, handles {}-{}, scene {}-{}".format(
                instance.data["subset"],
                frame_data["frame_start"],
                frame_data["frame_end"],
                frame_data["frame_start_handle"],
                frame_data["frame_end_handle"],
                frame_data["mark_in"],
                frame_data["mark_out"]
            )
        )
