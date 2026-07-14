# -*- coding: utf-8 -*-
"""Extract data as Maya scene (raw)."""
import os
import contextlib
import tempfile

from maya import cmds
from maya import mel

from openpype.hosts.maya.api.lib import (
    maintained_selection,
    suspended_refresh,
    remove_namespaces_from_file,
)
from openpype.pipeline import AVALON_CONTAINER_ID, publish
from openpype.pipeline.publish import OpenPypePyblishPluginMixin
from openpype.lib import BoolDef, TextDef


def offset_node(node, offset):
    node_type = cmds.nodeType(node)
    if node_type.startswith("animCurve"):
        cmds.keyframe(node, edit=True, relative=True, timeChange=offset)

    elif node_type == "imagePlane":
        node_attr = node + ".frameOffset"
        cmds.setAttr(node_attr, cmds.getAttr(node_attr) + (-offset))

    elif node_type == "timeSliderBookmark":
        for attr in ["timeRangeStart", "timeRangeStop"]:
            node_attr = "{}.{}".format(node, attr)
            cmds.setAttr(node_attr, cmds.getAttr(node_attr) + offset)


@contextlib.contextmanager
def offset_scene(offset):
    # Exit early for easier stacking of context managers.
    if offset is None:
        yield
        return

    nodes = cmds.ls(type=("animCurve", "imagePlane", "timeSliderBookmark"))
    changed_nodes = []
    try:
        for node in nodes:
            offset_node(node, offset)
            changed_nodes.append(node)
        yield
    finally:
        for node in changed_nodes:
            offset_node(node, -offset)


@contextlib.contextmanager
def maintain_timeline(frame_start, frame_end, handle_start, handle_end):
    # Exit early for easier stacking of context managers.
    if None in [frame_start, frame_end, handle_start, handle_end]:
        yield
        return

    data = {
        "minTime": None,
        "maxTime": None,
        "animationStartTime": None,
        "animationEndTime": None
    }
    for key in data.keys():
        kwargs = {key: True, "query": True}
        data[key] = cmds.playbackOptions(**kwargs)

    current_time = cmds.currentTime(query=True)
    render_start_frame = cmds.getAttr("defaultRenderGlobals.startFrame")
    render_end_frame = cmds.getAttr("defaultRenderGlobals.endFrame")

    scene_config_nodes = []
    for node in cmds.ls(type="script"):
        if "sceneConfigurationScriptNode" in node:
            scene_config_nodes.append(node)

    try:
        animation_start_time = frame_start - handle_start
        animation_end_time = frame_end + handle_start

        cmds.playbackOptions(
            minTime=frame_start,
            maxTime=frame_end,
            animationStartTime=animation_start_time,
            animationEndTime=animation_end_time
        )

        for node in scene_config_nodes:
            cmds.setAttr(
                "{}.before".format(node),
                "playbackOptions -min {} -max {} -ast {} -aet {}".format(
                    frame_start,
                    frame_end,
                    animation_start_time,
                    animation_end_time
                ),
                type="string"
            )

        cmds.currentTime(frame_start)

        cmds.setAttr("defaultRenderGlobals.startFrame", frame_start)
        cmds.setAttr("defaultRenderGlobals.endFrame", frame_end)

        yield
    finally:
        cmds.playbackOptions(**data)

        for node in scene_config_nodes:
            cmds.setAttr(
                "{}.before".format(node),
                "playbackOptions -min {} -max {} -ast {} -aet {}".format(
                    data["minTime"],
                    data["maxTime"],
                    data["animationStartTime"],
                    data["animationEndTime"]
                ),
                type="string"
            )

        cmds.currentTime(current_time, edit=True)

        cmds.setAttr("defaultRenderGlobals.startFrame", render_start_frame)
        cmds.setAttr("defaultRenderGlobals.endFrame", render_end_frame)


@contextlib.contextmanager
def maya_scene_context(keep_temp_scene=False):
    """
    Context manager to execute code on a Maya scene and revert changes afterwards.
    Saves the current scene, executes code, then reopens the saved scene to revert.
    Uses a temporary directory for the temp scene file.
    If keep_temp_scene is True, the temp scene file is not deleted.
    """
    cmds.file(save=True, type="mayaAscii")
    original_scene = cmds.file(q=True, sn=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_scene = os.path.join(temp_dir, "__temp_maya_context__.ma")
        cmds.file(rename=temp_scene)
        try:
            yield
            cmds.file(save=True, type="mayaAscii")
        finally:
            if original_scene:
                cmds.file(original_scene, open=True, force=True)
            else:
                cmds.file(new=True, force=True)
            if keep_temp_scene:
                # Move temp_scene to a persistent location if requested
                persistent_path = os.path.join(os.path.expanduser("~"), "__temp_maya_context__.ma")
                try:
                    if os.path.exists(persistent_path):
                        os.remove(persistent_path)
                    os.rename(temp_scene, persistent_path)
                    print(f"Temp scene kept at: {persistent_path}")
                except Exception as e:
                    print(f"Could not keep temp scene: {e}")


def merge_all_anim_layers_to_base():
    """
    Bakes and merges all animation layers
    down to the BaseAnimation layer.
    """

    # 1. Get all animation layers in the scene
    all_layers = cmds.ls(type='animLayer')
    if not all_layers:
        print("No animation layers found to merge.")
        return

    if len(all_layers) == 1:
        print("Only BaseAnimation layer exists or no other layers found.")
        return

    # 3. Use MEL's animLayerMerge to bake and merge the layers
    # NOTE: The direct Python command for baking/merging layers can be complex/buggy.
    # The MEL command 'animLayerMerge' is often more reliable for merging to BaseAnimation.

    # Convert list of layers to a MEL-friendly string format
    layers_string = '{%s}' % ','.join(['"%s"' % layer for layer in all_layers])

    try:
        # The animLayerMerge command bakes the layers' animation onto the
        # BaseAnimation layer (if it's the only one left to merge with)
        # and deletes the merged layers.
        mel_command = f'animLayerMerge {layers_string}'
        mel.eval(mel_command)

        print(f"Successfully merged layers: {all_layers} into BaseAnimation.")

    except Exception as e:
        print(f"Error merging animation layers: {e}")

    # Check that either no animation layers exist or only BaseAnimation remains
    remaining_layers = cmds.ls(type='animLayer')
    msg = f"Failed to merge all layers to BaseAnimation. Remaining layers: {remaining_layers}"
    assert not remaining_layers or remaining_layers == ['BaseAnimation'], msg


def bake_constraints_on_nodes(nodes, start_frame, end_frame):
    # Get all descendants of the selected nodes
    descendants = cmds.listRelatives(nodes, allDescendents=True, fullPath=True) or []
    nodes_to_check = nodes + descendants

    constrained_nodes = []
    constraints_to_delete = []
    for node in nodes_to_check:
        constraints = cmds.listRelatives(node, type="constraint", fullPath=True) or []
        constraints = [c for c in constraints if not cmds.referenceQuery(c, isNodeReferenced=True)]
        if not constraints:
            continue

        targets = set()
        for constraint in constraints:
            target_list = cmds.listConnections(constraint + ".target", source=True, destination=False, fullNodeName=True) or []
            target_list = [t for t in target_list if t not in constraints]
            targets.update(target_list)
        targets.discard(node)

        if targets and all(t in nodes_to_check for t in targets):
            continue

        constrained_nodes.append(node)
        constraints_to_delete.extend(constraints)

    constraints_to_delete = list(set(constraints_to_delete))
    if constrained_nodes:
        cmds.bakeResults(
            constrained_nodes,
            simulation=True,
            t=(start_frame, end_frame),
            sampleBy=1,
            oversamplingRate=1,
            disableImplicitControl=True,
            preserveOutsideKeys=True,
            sparseAnimCurveBake=False,
            removeBakedAttributeFromLayer=False,
            removeBakedAnimFromLayer=False,
            bakeOnOverrideLayer=True,
            minimizeRotation=True,
            controlPoints=False,
            shape=True
        )
        if constraints_to_delete:
            cmds.delete(constraints_to_delete)

        return constraints_to_delete
    else:
        cmds.warning("No constrained nodes found in selection.")

    return []


class ExtractMayaSceneRaw(publish.Extractor, OpenPypePyblishPluginMixin):
    """Extract as Maya Scene (raw).

    This will preserve all references, construction history, etc.
    """

    label = "Maya Scene (Raw)"
    hosts = ["maya"]
    families = ["mayaAscii",
                "mayaScene",
                "setdress",
                "layout",
                "camerarig",
                "shot"]
    scene_type = "ma"
    bake_animation_layers = False
    export_selected_strict = False
    exact_set_members_only = False
    namespaces_to_remove = ""

    @classmethod
    def get_attribute_defs(cls):
        return [
            BoolDef(
                "preserve_references",
                label="Preserve References",
                default=True
            ),
            BoolDef(
                "bake_animation_layers",
                label="Bake Animation Layers",
                default=cls.bake_animation_layers
            ),
            BoolDef(
                "export_selected_strict",
                label="Export Selected Strict",
                default=cls.export_selected_strict
            ),
            BoolDef(
                "exact_set_members_only",
                label="Exact Set Members Only",
                default=cls.export_selected_strict
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
                        "Using {} as scene type".format(self.scene_type))
                    break
                except KeyError:
                    # no preset found
                    pass

        attribute_values = self.get_attr_values_from_data(instance.data)

        # Define extract output file path
        dir_path = self.staging_dir(instance)
        filename = "{0}.{1}".format(instance.name, self.scene_type)
        path = os.path.join(dir_path, filename)

        # Whether to include all nodes in the instance (including those from
        # history) or only use the exact set members
        if attribute_values["exact_set_members_only"]:
            members = instance.data.get("setMembers", list())
            if not members:
                raise RuntimeError("Can't export 'exact set members only' "
                                   "when set is empty.")
        else:
            members = instance[:]

        selection = members
        if set(self.add_for_families).intersection(
                set(instance.data.get("families", []))) or \
                instance.data.get("family") in self.add_for_families:
            selection += self._get_loaded_containers(members)

        namespaces_to_remove = attribute_values.get("namespaces_to_remove", "")
        namespaces_to_remove = [s.strip() for s in namespaces_to_remove.split(",") if s]

        # Ensure scene configuration script node is included in export.
        for node in cmds.ls(type="script"):
            if "sceneConfigurationScriptNode" in node and ":" not in node:
                selection.append(node)

        # Perform extraction
        self.log.debug("Performing extraction ...")

        frame_offset = instance.data.get("frameOffset")
        self.log.debug("frameOffset: {}".format(frame_offset))

        frame_range = [None, None, None, None]
        if instance.data.get("update_timeline", False):
            frame_range = [
                instance.data["frameStart"],
                instance.data["frameEnd"],
                instance.data["handleStart"],
                instance.data["handleEnd"]
            ]
            self.log.debug("Updating timeline to {}.".format(frame_range))

        kwargs = {
            "force": True,
            "typ": "mayaAscii" if self.scene_type == "ma" else "mayaBinary",
            "exportSelected": True,
            "preserveReferences": attribute_values["preserve_references"],
            "constructionHistory": True,
            "shader": True,
            "constraints": True,
            "expressions": True
        }

        if attribute_values["export_selected_strict"]:
            kwargs["exportSelectedStrict"] = True
            kwargs.pop("exportSelected", None)

            # Find animCurve nodes connected to selection
            anim_curves = set()
            for node in selection:
                connections = cmds.listConnections(node, type="animCurve") or []
                anim_curves.update(connections)

            selection += list(anim_curves)

        self.log.debug("Exporting with:\n{}".format(kwargs))
        self.log.debug("Exporting:\n{}".format(selection))
        if attribute_values["bake_animation_layers"]:
            with (maintained_selection(),
                offset_scene(frame_offset),
                suspended_refresh(),
                maintain_timeline(*frame_range),
                maya_scene_context()
                ):
                deleted_constraints = bake_constraints_on_nodes(selection, instance.data["frameStart"], instance.data["frameEnd"])
                merge_all_anim_layers_to_base()

                selection = [node for node in selection if node not in deleted_constraints]

                cmds.select(selection, noExpand=True)
                cmds.file(path, **kwargs)
        else:
            with (maintained_selection(),
                offset_scene(frame_offset),
                suspended_refresh(),
                maintain_timeline(*frame_range)
                ):
                cmds.select(selection, noExpand=True)
                cmds.file(path, **kwargs)

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

        self.log.debug("Extracted instance '%s' to: %s" % (instance.name,
                                                           path))

    @staticmethod
    def _get_loaded_containers(members):
        # type: (list) -> list
        refs_to_include = {
            cmds.referenceQuery(node, referenceNode=True)
            for node in members
            if cmds.referenceQuery(node, isNodeReferenced=True)
        }

        members_with_refs = refs_to_include.union(members)

        obj_sets = cmds.ls("*.id", long=True, type="objectSet", recursive=True,
                           objectsOnly=True)

        loaded_containers = []
        for obj_set in obj_sets:

            if not cmds.attributeQuery("id", node=obj_set, exists=True):
                continue

            id_attr = "{}.id".format(obj_set)
            if cmds.getAttr(id_attr) != AVALON_CONTAINER_ID:
                continue

            set_content = set(cmds.sets(obj_set, query=True))
            if set_content.intersection(members_with_refs):
                loaded_containers.append(obj_set)

        return loaded_containers
