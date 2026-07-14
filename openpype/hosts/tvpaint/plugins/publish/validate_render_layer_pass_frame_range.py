"""Validate render.layer frame range against its render.pass siblings.

Each render.layer should declare a frame range that is within the union of all
its linked render.pass frame ranges. This ensures the render.layer doesn't request
frames that no pass is prepared to render.

Repair action: clamps render.layer frame range to the union of its passes.
"""

import pyblish.api
from openpype.pipeline import PublishXmlValidationError
from openpype.pipeline.publish import get_errored_instances_from_context
from openpype.hosts.tvpaint.api.pipeline import list_instances, write_instances


class RepairRenderLayerPassFrameRange(pyblish.api.Action):
    """Repair render.layer frame range to match its pass siblings' union."""

    label = "Repair"
    icon = "wrench"
    on = "failed"

    def process(self, context, plugin):
        """Update render.layer frame ranges to match pass union."""
        errored_instances = get_errored_instances_from_context(
            context,
            plugin=plugin
        )

        if not errored_instances:
            self.log.warning("Repair: No errored instances found.")
            return

        workfile_instances = list_instances()
        if not workfile_instances:
            self.log.warning("Repair: No workfile instances found.")
            return

        scene_mark_in = context.data.get("sceneMarkIn", 0)
        context_frame_start = context.data.get("frameStart", 0)
        self.log.debug(
            "Repair: sceneMarkIn={} contextFrameStart={}".format(
                scene_mark_in, context_frame_start
            )
        )

        for instance in errored_instances:
            instance_id = instance.data.get("instance_id")
            self.log.debug(
                "Repair: processing render.layer '{}' instance_id={}".format(
                    instance.data.get("name"), instance_id
                )
            )

            # Find all render.pass instances linked to this render.layer
            pass_instances = []
            for other_inst in context:
                if other_inst.data.get("creator_identifier") != "render.pass":
                    continue
                other_render_layer_id = (
                    other_inst.data.get("creator_attributes", {})
                    .get("render_layer_instance_id")
                )
                if other_render_layer_id == instance_id:
                    pass_instances.append(other_inst)
                    self.log.debug(
                        "Repair: found linked pass '{}'".format(
                            other_inst.data.get("name")
                        )
                    )

            if not pass_instances:
                self.log.warning(
                    "Repair: render.layer '{}' has no linked passes, "
                    "skipping.".format(instance.data.get("name"))
                )
                continue

            # Compute union of pass frame ranges (in asset/DB frame space)
            pass_frame_starts = []
            pass_frame_ends = []
            for pass_inst in pass_instances:
                fs = pass_inst.data.get("frameStart")
                fe = pass_inst.data.get("frameEnd")
                if fs is not None and fe is not None:
                    pass_frame_starts.append(fs)
                    pass_frame_ends.append(fe)
                    self.log.debug(
                        "Repair: pass '{}' frameStart={} frameEnd={}".format(
                            pass_inst.data.get("name"), fs, fe
                        )
                    )

            if not pass_frame_starts or not pass_frame_ends:
                self.log.warning(
                    "Repair: Could not determine pass frame ranges for "
                    "render.layer '{}', skipping.".format(
                        instance.data.get("name")
                    )
                )
                continue

            pass_union_start = min(pass_frame_starts)
            pass_union_end = max(pass_frame_ends)
            self.log.debug(
                "Repair: pass union in asset frame space: {}-{}".format(
                    pass_union_start, pass_union_end
                )
            )

            # Find and update the corresponding workfile instance
            matched = False
            for wf_instance in workfile_instances:
                wf_id = wf_instance.get("instance_id")
                if wf_id == instance_id:
                    creator_attributes = wf_instance.get(
                        "creator_attributes", {}
                    )
                    self.log.debug(
                        "Repair: matched! old creator_attributes={}".format(
                            creator_attributes
                        )
                    )
                    creator_attributes["frame_start"] = pass_union_start
                    creator_attributes["frame_end"] = pass_union_end
                    wf_instance["creator_attributes"] = creator_attributes
                    self.log.info(
                        "Repair: updated render.layer '{}' frame range to "
                        "{}-{}".format(
                            instance.data.get("name"),
                            pass_union_start, pass_union_end
                        )
                    )
                    matched = True
                    break

            if not matched:
                self.log.warning(
                    "Repair: could not find workfile instance matching "
                    "instance_id={}".format(instance_id)
                )

        write_instances(workfile_instances)
        self.log.info("Repair: done.")


class ValidateRenderLayerPassFrameRange(pyblish.api.InstancePlugin):
    """Validate render.layer frame range fits within its pass siblings' union.

    Applies to render.layer instances only. Ensures the render.layer's declared
    frame range (from creator_attributes or asset) does not exceed the union of
    all its linked render.pass frame ranges.
    """

    label = "Validate Render Layer Pass Frame Range"
    order = pyblish.api.ValidatorOrder
    hosts = ["tvpaint"]
    families = ["render"]
    actions = [RepairRenderLayerPassFrameRange]

    def process(self, instance):
        # Only validate render.layer instances
        if instance.data.get("creator_identifier") != "render.layer":
            return

        instance_id = instance.data.get("instance_id")
        context = instance.context

        # Find all render.pass instances linked to this render.layer
        pass_instances = []
        for other_inst in context:
            if other_inst.data.get("creator_identifier") != "render.pass":
                continue
            other_render_layer_id = (
                other_inst.data.get("creator_attributes", {})
                .get("render_layer_instance_id")
            )
            if other_render_layer_id == instance_id:
                pass_instances.append(other_inst)

        # If no passes linked, no constraint
        if not pass_instances:
            self.log.info(
                "Render.layer '{}' has no linked passes, skipping validation.".format(
                    instance.data.get("name")
                )
            )
            return

        # Get render.layer frame range (in asset/DB frame space)
        layer_frame_start = instance.data.get("frameStart")
        layer_frame_end = instance.data.get("frameEnd")
        if layer_frame_start is None or layer_frame_end is None:
            self.log.warning(
                "Render.layer '{}' has missing frameStart/frameEnd, skipping.".format(
                    instance.data.get("name")
                )
            )
            return

        # Compute union of pass frame ranges
        pass_frame_starts = []
        pass_frame_ends = []
        for pass_inst in pass_instances:
            fs = pass_inst.data.get("frameStart")
            fe = pass_inst.data.get("frameEnd")
            if fs is not None and fe is not None:
                pass_frame_starts.append(fs)
                pass_frame_ends.append(fe)

        if not pass_frame_starts or not pass_frame_ends:
            self.log.warning(
                "Could not determine pass frame ranges, skipping validation."
            )
            return

        pass_union_start = min(pass_frame_starts)
        pass_union_end = max(pass_frame_ends)

        # Validate: render.layer must be within pass union
        if layer_frame_start < pass_union_start or layer_frame_end > pass_union_end:
            msg = (
                "Render.layer '{}' frame range {}-{} exceeds its render.pass "
                "siblings' frame union {}-{}. "
                "Either extend the passes to match the render.layer, "
                "or use the Repair action to clamp the render.layer to the pass union."
            ).format(
                instance.data.get("name"),
                layer_frame_start, layer_frame_end,
                pass_union_start, pass_union_end
            )
            raise PublishXmlValidationError(instance, msg)
