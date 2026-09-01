import pyblish.api

from openpype.pipeline import (
    PublishXmlValidationError,
    OptionalPyblishPluginMixin,
)
from openpype.pipeline.publish import get_errored_instances_from_context
from openpype.hosts.tvpaint.api.pipeline import list_instances, write_instances
from openpype.hosts.tvpaint.api.lib import (
    get_layers_pre_post_behavior,
    get_layers_exposure_frames,
    get_layers_empty_frames,
)
from openpype.hosts.tvpaint.lib import (
    calculate_layer_frame_references,
    calculate_instance_frame_data,
)


def format_frame_ranges(frames):
    """Format a list of frame numbers as compact ranges.

    Args:
        frames (list): Sorted list of frame numbers.

    Returns:
        str: Compact representation, e.g. "1001-1003, 1010"
    """
    if not frames:
        return ""

    frames = sorted(set(frames))
    ranges = []
    start = frames[0]
    end = start

    for i in range(1, len(frames)):
        if frames[i] == end + 1:
            end = frames[i]
        else:
            if start == end:
                ranges.append(str(start))
            else:
                ranges.append("{}-{}".format(start, end))
            start = frames[i]
            end = start

    # Add the last range
    if start == end:
        ranges.append(str(start))
    else:
        ranges.append("{}-{}".format(start, end))

    return ", ".join(ranges)


def resolve_instance_frame_data(instance):
    """Frame data for an instance, honouring live creator attributes.

    Creator attributes are re-resolved here because the collected values
    go stale after a repair or a frame range edit in the publisher.

    Returns:
        dict: Same shape as 'calculate_instance_frame_data'.
    """
    context = instance.context
    creator_attributes = instance.data.get("creator_attributes") or {}
    asset_doc = instance.data.get("assetEntity") or {}
    asset_data = asset_doc.get("data") or {}
    asset_frame_start = asset_data.get("frameStart")
    if asset_frame_start is None:
        asset_frame_start = context.data["frameStart"]

    handle_start = context.data.get("handleStart") or 0
    handle_end = context.data.get("handleEnd") or 0

    return calculate_instance_frame_data(
        creator_attributes.get("frame_start"),
        creator_attributes.get("frame_end"),
        asset_frame_start,
        context.data["sceneMarkIn"],
        context.data["sceneMarkOut"],
        handle_start,
        handle_end
    )


def to_asset_frames(frames, frame_data):
    """Convert scene space frames to asset space."""
    offset = frame_data["frame_start"] - frame_data["mark_in"]
    return [frame + offset for frame in frames]


def get_instance_content_frames(instance):
    """Scene-space frames of an instance range that have rendered content.

    Returns:
        tuple: (range_start, range_end, content_frames) in scene frame space.
            'content_frames' is a set of frames where at least one visible
            layer resolves to a non-empty image.
    """
    layers = [
        l for l in instance.data.get("layers") or []
        if l.get("visible", True)
    ]
    if not layers:
        return (None, None, set())

    layer_ids = [
        l["layer_id"] for l in layers
        if l.get("layer_id") is not None
    ]
    if not layer_ids:
        return (None, None, set())

    context = instance.context
    frame_data = resolve_instance_frame_data(instance)
    range_start = frame_data["mark_in"]
    range_end = frame_data["mark_out"]

    # Cache TVPaint queries per layer id on context.data so multiple instances
    # sharing layers do not re-run george
    behavior_cache = context.data.setdefault("tvpaintLayerBehaviorCache", {})
    exposure_cache = context.data.setdefault("tvpaintLayerExposureCache", {})
    empty_cache = context.data.setdefault("tvpaintLayerEmptyFramesCache", {})

    # Determine which layer_ids are missing from each cache
    missing_behavior = [lid for lid in layer_ids if lid not in behavior_cache]
    missing_exposure = [lid for lid in layer_ids if lid not in exposure_cache]
    missing_empty = [lid for lid in layer_ids if lid not in empty_cache]

    # Query TVPaint only for missing data
    if missing_behavior:
        behavior_result = get_layers_pre_post_behavior(missing_behavior)
        behavior_cache.update(behavior_result)

    if missing_exposure:
        # Build layers_data for the missing ids
        layers_data_for_exposure = [
            l for l in layers if l["layer_id"] in missing_exposure
        ]
        exposure_result = get_layers_exposure_frames(
            missing_exposure, layers_data=layers_data_for_exposure
        )
        exposure_cache.update(exposure_result)

    if missing_empty:
        # Build layers_data for the missing ids
        layers_data_for_empty = [
            l for l in layers if l["layer_id"] in missing_empty
        ]
        empty_result = get_layers_empty_frames(
            missing_empty, layers_data=layers_data_for_empty
        )
        empty_cache.update(empty_result)

    # Build content frames from cached data
    content_frames = set()
    for layer in layers:
        layer_id = layer["layer_id"]
        exposure_frames = exposure_cache.get(layer_id) or []
        if not exposure_frames:
            continue

        behavior = behavior_cache.get(layer_id) or {}
        pre_beh = behavior.get("pre", "none")
        post_beh = behavior.get("post", "none")

        # Mirror extract_sequence.py: loopLayers forces post="repeat"
        if instance.data.get("loopLayers"):
            post_beh = "repeat"

        empty_frames = set(empty_cache.get(layer_id) or [])

        frame_references = calculate_layer_frame_references(
            range_start, range_end,
            layer["frame_start"], layer["frame_end"],
            exposure_frames,
            pre_beh, post_beh
        )

        for frame, reference in frame_references.items():
            if reference is not None and reference not in empty_frames:
                content_frames.add(frame)

    return range_start, range_end, content_frames


class RepairEmptyFrames(pyblish.api.Action):
    """Trim the instance frame range to the frames that have content."""

    label = "Repair"
    icon = "wrench"
    on = "failed"

    def process(self, context, plugin):
        """Trim instance frame ranges to content frames."""
        errored_instances = get_errored_instances_from_context(
            context, plugin=plugin
        )
        if not errored_instances:
            self.log.warning("Repair: No errored instances found.")
            return

        workfile_instances = list_instances()
        if not workfile_instances:
            self.log.warning("Repair: No workfile instances found.")
            return

        any_changed = False

        for instance in errored_instances:
            frame_data = resolve_instance_frame_data(instance)
            content_data = get_instance_content_frames(instance)
            content_frames = content_data[2]
            if not content_frames:
                self.log.warning(
                    "Repair: instance '{}' has no content at all, "
                    "cannot repair automatically.".format(
                        instance.data.get("name")
                    )
                )
                continue

            new_frame_start, new_frame_end = to_asset_frames(
                [min(content_frames), max(content_frames)], frame_data
            )

            # Compute interior gaps before attempting repair
            content_span = set(range(
                min(content_frames), max(content_frames) + 1
            ))
            interior_empty = sorted(content_span - content_frames)

            current_start = frame_data["frame_start"]
            current_end = frame_data["frame_end"]
            if (
                new_frame_start == current_start
                and new_frame_end == current_end
            ):
                msg = (
                    "Repair: instance '{}' frame range {}-{} already "
                    "matches content range".format(
                        instance.data.get("name"),
                        current_start, current_end
                    )
                )
                if interior_empty:
                    interior_asset = to_asset_frames(
                        interior_empty, frame_data
                    )
                    msg += (
                        "; empty frames {} are gaps inside the range "
                        "and must be fixed in TVPaint".format(
                            format_frame_ranges(interior_asset)
                        )
                    )
                self.log.warning(msg)
                continue

            # Find and update the corresponding workfile instance
            instance_id = instance.data.get("instance_id")
            for wf_instance in workfile_instances:
                if wf_instance.get("instance_id") == instance_id:
                    creator_attrs = wf_instance.setdefault(
                        "creator_attributes", {}
                    )
                    creator_attrs["frame_start"] = new_frame_start
                    creator_attrs["frame_end"] = new_frame_end
                    any_changed = True
                    self.log.info(
                        "Repair: updated instance '{}' frame range from "
                        "{}-{} to {}-{}".format(
                            instance.data.get("name"),
                            current_start, current_end,
                            new_frame_start, new_frame_end
                        )
                    )

                    if interior_empty:
                        interior_asset = to_asset_frames(
                            interior_empty, frame_data
                        )
                        self.log.warning(
                            "Repair: instance '{}' still has empty frames "
                            "in the middle: {}. Trimming will not remove "
                            "interior gaps; they must be fixed in "
                            "TVPaint.".format(
                                instance.data.get("name"),
                                format_frame_ranges(interior_asset)
                            )
                        )
                    break

        if any_changed:
            write_instances(workfile_instances)
            self.log.info("Repair: done.")
        else:
            self.log.info("Repair: nothing to repair.")


class ValidateEmptyFrames(
    OptionalPyblishPluginMixin,
    pyblish.api.InstancePlugin
):
    """Validate instance frame range contains no empty frames.

    Every frame of the instance range must resolve to an image on at least
    one visible layer. Frames where all visible layers report "Empty" from
    `tv_exposureinfo` would render as blank images.
    """

    label = "Validate Empty Frames"
    order = pyblish.api.ValidatorOrder
    hosts = ["tvpaint"]
    families = ["render", "renderLayer", "renderPass", "renderScene"]
    optional = True
    actions = [RepairEmptyFrames]

    def process(self, instance):
        if not self.is_active(instance.data):
            return

        frame_data = resolve_instance_frame_data(instance)
        range_start, range_end, content_frames = get_instance_content_frames(
            instance
        )
        if range_start is None:
            return

        # Find frames in range that are empty (no content)
        empty_frames = sorted(
            set(range(range_start, range_end + 1)) - content_frames
        )
        if not empty_frames:
            return

        empty_frames_asset_space = to_asset_frames(
            empty_frames, frame_data
        )
        empty_frames_formatted = format_frame_ranges(empty_frames_asset_space)

        instance_label = instance.data.get("label") or instance.data["name"]

        raise PublishXmlValidationError(
            self,
            "Instance frame range contains empty frames that would"
            " render blank.",
            formatting_data={
                "instance_label": instance_label,
                "frame_start": frame_data["frame_start"],
                "frame_end": frame_data["frame_end"],
                "empty_frames": empty_frames_formatted,
                "empty_frame_count": len(empty_frames),
            }
        )
