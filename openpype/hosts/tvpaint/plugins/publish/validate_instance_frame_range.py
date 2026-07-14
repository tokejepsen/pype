import pyblish.api
from openpype.pipeline import PublishXmlValidationError
from openpype.pipeline.publish import get_errored_instances_from_context
from openpype.hosts.tvpaint.api.pipeline import list_instances, write_instances
from openpype.hosts.tvpaint.api.lib import get_layers_pre_post_behavior

class RepairInstanceFrameRange(pyblish.api.Action):
    """Expand the instance frame_end to match the scene mark-out.

    For instances with layers that have non-none post-behavior (repeat, pingpong,
    or hold), this repair sets the instance frame_end to the scene mark-out
    (converted to asset frame space), ensuring all extending/looping layers are
    properly captured.
    """

    label = "Repair"
    icon = "wrench"
    on = "failed"

    def process(self, context, plugin):
        """Expand instance frame_end to accommodate layers with post-behavior."""
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

        # Context conversion parameters
        scene_mark_in = context.data.get("sceneMarkIn", 0)
        scene_mark_out = context.data.get("sceneMarkOut", 0)
        context_frame_start = context.data.get("frameStart", 0)

        # Convert scene_mark_out to asset frame space
        expected_frame_end = context_frame_start + (scene_mark_out - scene_mark_in)
        self.log.debug(
            "Repair: Converting sceneMarkOut={} to frameEnd={} (asset space)".format(
                scene_mark_out, expected_frame_end
            )
        )

        for instance in errored_instances:
            instance_id = instance.data.get("instance_id")
            layers = instance.data.get("layers", [])
            if not layers:
                self.log.debug(
                    "Repair: instance '{}' has no layers, skipping.".format(
                        instance.data.get("name")
                    )
                )
                continue

            # Only consider visible layers (matches validator behaviour)
            layers = [layer for layer in layers if layer.get("visible", True)]
            if not layers:
                self.log.debug(
                    "Repair: instance '{}' has no visible layers, skipping.".format(
                        instance.data.get("name")
                    )
                )
                continue

            # Get layer IDs to check post-behavior
            layer_ids = [
                layer.get("layer_id")
                for layer in layers
                if layer.get("layer_id") is not None
            ]
            if not layer_ids:
                self.log.debug(
                    "Repair: instance '{}' has no valid layer IDs, skipping.".format(
                        instance.data.get("name")
                    )
                )
                continue

            # Get post-behavior for layers
            behavior_by_layer_id = get_layers_pre_post_behavior(layer_ids)

            # Check if any layer has non-none post-behavior
            has_post_behavior = any(
                behavior_by_layer_id.get(layer_id, {}).get("post", "none").lower() != "none"
                for layer_id in layer_ids
            )

            if not has_post_behavior:
                self.log.debug(
                    "Repair: instance '{}' has no layers with post-behavior, "
                    "skipping.".format(instance.data.get("name"))
                )
                continue

            # Find and update the corresponding workfile instance
            for wf_instance in workfile_instances:
                if wf_instance.get("instance_id") == instance_id:
                    creator_attrs = wf_instance.setdefault(
                        "creator_attributes", {}
                    )
                    old_end = creator_attrs.get("frame_end")
                    creator_attrs["frame_end"] = expected_frame_end
                    self.log.info(
                        "Repair: updated instance '{}' frame_end from {} to {}".format(
                            instance.data.get("name"),
                            old_end,
                            expected_frame_end
                        )
                    )
                    break

        write_instances(workfile_instances)
        self.log.info("Repair: done.")


class ValidateInstanceFrameRange(pyblish.api.InstancePlugin):
    """Validate frame range for layers with extending post-behavior.

    If any visible layer has post-behavior that extends content (repeat,
    pingpong, or hold), the instance frame_end must match the full workfile
    frame range (scene_mark_out converted to asset frame space). This ensures
    all extending layers are fully captured.
    """

    label = "Validate Instance Frame Range"
    order = pyblish.api.ValidatorOrder
    hosts = ["tvpaint"]
    families = ["render", "renderLayer", "renderPass", "renderScene"]
    actions = [RepairInstanceFrameRange]

    def process(self, instance):
        layers = instance.data.get("layers")
        if not layers:
            return

        layers = [l for l in layers if l.get("visible", True)]
        if not layers:
            return

        context = instance.context
        scene_mark_in = context.data.get("sceneMarkIn", 0)
        scene_mark_out = context.data.get("sceneMarkOut", scene_mark_in)
        context_frame_start = context.data.get("frameStart", 0)

        # Read frame range from creator_attributes so post-collection UI edits
        # are respected. instance.data["frameStart/End"] are frozen at collect time.
        creator_attributes = instance.data.get("creator_attributes", {})
        if "frame_start" in creator_attributes and "frame_end" in creator_attributes:
            frame_start = creator_attributes["frame_start"]
            frame_end = creator_attributes["frame_end"]
        else:
            frame_start = context_frame_start
            frame_end = context_frame_start + (scene_mark_out - scene_mark_in)

        # Fetch post-behavior for all visible layers in one call
        layer_ids = [l.get("layer_id") for l in layers
                    if l.get("layer_id") is not None]
        behavior_by_layer_id = {}
        if layer_ids:
            behavior_by_layer_id = get_layers_pre_post_behavior(layer_ids)

        # Post-behaviors that extend content beyond the layer's own frame range
        extending_post_behaviors = frozenset(("repeat", "pingpong", "hold"))

        # Check if any visible layer has an extending post-behavior
        has_extending_behavior = any(
            behavior_by_layer_id.get(layer.get("layer_id"), {}).get("post", "none").lower()
            in extending_post_behaviors
            for layer in layers
            if layer.get("layer_id") is not None
        )

        if not has_extending_behavior:
            return

        # If extending behaviors exist, frame_end must cover the full workfile range
        expected_frame_end = context_frame_start + (scene_mark_out - scene_mark_in)
        current_frame_end = creator_attributes.get("frame_end", frame_end)

        if current_frame_end == expected_frame_end:
            return

        # Validation failed: frame_end does not cover full workfile range
        instance_label = instance.data.get("label") or instance.data["name"]

        raise PublishXmlValidationError(
            self,
            "Instance with extending layer post-behaviors must cover full workfile frame range.",
            formatting_data={
                "instance_label": instance_label,
                "current_frame_end": current_frame_end,
                "expected_frame_end": expected_frame_end,
                "scene_mark_in": scene_mark_in,
                "scene_mark_out": scene_mark_out,
            }
        )
