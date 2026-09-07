# -*- coding: utf-8 -*-
import contextlib
import os

from maya import cmds  # noqa
import pyblish.api

from openpype.pipeline import publish
from openpype.hosts.maya.api import fbx
from openpype.hosts.maya.api.lib import (
    namespaced, get_namespace, strip_namespace, parent_nodes
)


class ExtractFBXAnimation(publish.Extractor):
    """Extract Rig in FBX format from Maya.

    This extracts the rig in fbx with the constraints
    and referenced asset content included.
    This also optionally extract animated rig in fbx with
    geometries included.

    """
    order = pyblish.api.ExtractorOrder
    label = "Extract Animation (FBX)"
    hosts = ["maya"]
    families = ["animation.fbx"]

    # Attributes the rig may drive through a connection on the skeleton
    # hierarchy, which is not duplicated, so they are copied as static values.
    skeleton_display_attributes = [
        "radius",
        "segmentScaleCompensate"
    ]

    # The rig usually hides its bind skeleton, but an exported skeleton
    # hierarchy is expected to be visible and draw its joints as bones.
    skeleton_display_overrides = {
        "drawStyle": 0,
        "visibility": True,
        "overrideEnabled": False
    }

    def process(self, instance):
        # Define output path
        staging_dir = self.staging_dir(instance)

        fbx_exporter = fbx.FBXExtractor(log=self.log)

        start_frame = int(
            cmds.playbackOptions(query=True, animationStartTime=True)
        )
        end_frame = int(
            cmds.playbackOptions(query=True, animationEndTime=True)
        )

        # Export
        instance.data["constraints"] = False
        instance.data["skeletonDefinitions"] = True
        instance.data["referencedAssetsContent"] = True
        # Meshes and their skinning must be exported when the skeleton mesh
        # is included, otherwise only the joints end up in the FBX.
        include_mesh = instance.data.get("skeleton_mesh_included", False)
        # Shapes must always be True to preserve blendshape target
        # geometry and animation
        instance.data["shapes"] = True
        instance.data["skins"] = include_mesh
        instance.data["inputConnections"] = False
        instance.data["lights"] = False

        # The exporter reads the range off the instance, so it is
        # resolved before the export options are set.
        start, end = self.get_frame_range(instance)
        instance.data["frameStartHandle"] = start
        instance.data["frameEndHandle"] = end

        fbx_exporter.set_options_from_instance(instance)

        # The animation range must be widened first, otherwise Maya
        # clamps the playback range to it.
        cmds.playbackOptions(
            animationStartTime=min(start, start_frame),
            animationEndTime=max(end, end_frame),
            minTime=start,
            maxTime=end
        )

        representations = instance.data.setdefault("representations", [])
        skeleton_roots = instance.data.get("skeleton_export_roots", {})

        for skeleton_set, out_members in instance.data.get(
                "animated_skeletons", {}).items():
            filename = "{0}.fbx".format(skeleton_set)
            path = os.path.join(staging_dir, filename)
            path = path.replace("\\", "/")

            # Export from the rig's namespace so that the exported
            # FBX does not include the namespace but preserves the node
            # names as existing in the rig workfile
            namespace = get_namespace(out_members[0])
            relative_out_members = [
                strip_namespace(node, namespace) for node in out_members
            ]

            resolved_roots = skeleton_roots.get(skeleton_set) or []
            exported = False
            with self.visible_display_layers():
                if resolved_roots and not include_mesh:
                    exported = self.export_duplicated_skeleton(
                        fbx_exporter, resolved_roots, path, start, end
                    )
                elif resolved_roots:
                    self.log.warning(
                        "Skeleton mesh is included so the skeleton can not be "
                        "duplicated; the rig groups above the skeleton root "
                        "will be part of the FBX."
                    )

                if not exported:
                    # FBX export selected also writes the ancestors of the
                    # selection, so the roots are un-parented to world to
                    # keep the groups above them out of the export.
                    roots = self.get_reparentable_roots(resolved_roots)
                    with parent_nodes(roots):
                        with namespaced(
                            ":" + namespace,
                            new=False,
                            relative_names=True
                        ) as namespace:
                            fbx_exporter.export(relative_out_members, path)

            representations.append({
                'name': skeleton_set,
                'ext': 'fbx',
                'files': filename,
                "stagingDir": staging_dir,
                "outputName": skeleton_set
            })

            self.log.debug("Extracted FBX animation to: {0}".format(path))

        cmds.playbackOptions(
            animationStartTime=start_frame,
            animationEndTime=end_frame,
            minTime=start_frame,
            maxTime=end_frame
        )

    def get_frame_range(self, instance):
        """Return the frame range including handles for the instance.

        The publisher attributes are preferred because the collected
        instance data can end up holding the asset's frame range.

        Args:
            instance (pyblish.api.Instance): Instance to resolve for.

        Returns:
            tuple: Start and end frame including handles.
        """
        keys = [
            "frameStart", "frameEnd", "handleStart", "handleEnd",
            "frameStartHandle", "frameEndHandle"
        ]
        creator_attributes = instance.data.get("creator_attributes", {})
        sources = [creator_attributes, instance.data, instance.context.data]
        for name, source in zip(
            ["creator attributes", "instance", "context"], sources
        ):
            self.log.debug("Frame range on {0}: {1}".format(
                name, {key: source.get(key) for key in keys}
            ))

        def resolve(key):
            for source in sources:
                value = source.get(key)
                if value is not None:
                    return value
            return None

        frame_start = resolve("frameStart")
        frame_end = resolve("frameEnd")
        if frame_start is None or frame_end is None:
            start = resolve("frameStartHandle")
            end = resolve("frameEndHandle")
        else:
            start = frame_start - (resolve("handleStart") or 0)
            end = frame_end + (resolve("handleEnd") or 0)

        self.log.debug(
            "Exporting frame range: {0} - {1}".format(start, end)
        )
        return int(start), int(end)

    def get_reparentable_roots(self, roots):
        """Filter roots to those Maya allows to un-parent to world.

        Maya refuses to re-parent a referenced node when its parent is
        also referenced, so those roots keep their ancestors in the FBX.

        Args:
            roots (list): Candidate root nodes.

        Returns:
            list: Nodes that can be un-parented to world.
        """
        reparentable = []
        for root in roots:
            parent = cmds.listRelatives(root, parent=True, fullPath=True)
            if not parent:
                continue

            if (
                cmds.referenceQuery(root, isNodeReferenced=True)
                and cmds.referenceQuery(parent[0], isNodeReferenced=True)
            ):
                self.log.warning(
                    "Can not un-parent referenced node {}; its parent "
                    "groups will be included in the FBX.".format(root)
                )
                continue

            reparentable.append(root)

        return reparentable

    def export_duplicated_skeleton(
        self, fbx_exporter, roots, path, start, end
    ):
        """Export a baked world-level duplicate of the skeleton hierarchy.

        A referenced skeleton can not be un-parented, so a duplicate of
        its hierarchy nodes is constrained to the rig and baked. The
        duplicate lives at world level without a namespace, so the FBX
        root is the skeleton root.

        Args:
            fbx_exporter (fbx.FBXExtractor): Exporter to export with.
            roots (list): Skeleton root nodes to duplicate.
            path (str): Filepath to export to.
            start (int): Bake start frame.
            end (int): Bake end frame.

        Returns:
            bool: Whether the export was done.
        """
        duplicate_uuids = []
        constraints = []
        try:
            baked_nodes = []
            for root in roots:
                duplicate = cmds.duplicate(
                    root, returnRootsOnly=True, upstreamNodes=False
                )[0]
                duplicate = cmds.ls(duplicate, long=True)[0]
                duplicate_uuids.append(cmds.ls(duplicate, uuid=True)[0])

                if cmds.listRelatives(duplicate, parent=True):
                    duplicate = cmds.parent(duplicate, world=True)[0]

                # Geometry is not wanted in this code path, but the
                # transforms and locators of the hierarchy are kept.
                clutter = [
                    node for node in cmds.listRelatives(
                        duplicate, allDescendents=True, fullPath=True
                    ) or []
                    if not cmds.objectType(node, isAType="transform")
                    and cmds.objectType(node) != "locator"
                ]
                # Deleting a parent already removed its children.
                clutter = cmds.ls(clutter, long=True)
                if clutter:
                    cmds.delete(clutter)

                source_nodes = self.get_transform_hierarchy(root)
                target_nodes = self.get_transform_hierarchy(duplicate)
                if len(source_nodes) != len(target_nodes):
                    self.log.warning(
                        "Duplicated skeleton hierarchy of {} does not match "
                        "the source hierarchy; exporting from the rig "
                        "instead.".format(root)
                    )
                    return False

                target_nodes = self.strip_namespaces(target_nodes)

                for source, target in zip(source_nodes, target_nodes):
                    self.copy_attributes(
                        source, target, self.skeleton_display_attributes
                    )
                    self.set_attributes(
                        target, self.skeleton_display_overrides
                    )
                    constraints.extend(
                        cmds.parentConstraint(source, target)
                    )
                    constraints.extend(
                        cmds.scaleConstraint(source, target)
                    )
                baked_nodes.extend(target_nodes)

            cmds.bakeResults(
                baked_nodes,
                simulation=True,
                time=(start, end),
                sampleBy=1,
                disableImplicitControl=True,
                preserveOutsideKeys=False,
                sparseAnimCurveBake=False,
                removeBakedAttributeFromLayer=False,
                bakeOnOverrideLayer=False,
                minimizeRotation=True
            )
            cmds.delete(constraints)
            constraints = []

            duplicates = [
                cmds.ls(uuid, long=True)[0] for uuid in duplicate_uuids
            ]
            fbx_exporter.export(duplicates, path)
            return True
        finally:
            if constraints:
                cmds.delete(cmds.ls(constraints))
            existing = []
            for uuid in duplicate_uuids:
                existing.extend(cmds.ls(uuid, long=True))
            if existing:
                cmds.delete(existing)

    def get_transform_hierarchy(self, root):
        """Return the root and all its descendant transforms.

        Joints are transforms too, so groups, locators and joints are
        all collected.

        Args:
            root (str): Root node to collect from.

        Returns:
            list: Long names of the transforms in the hierarchy.
        """
        nodes = cmds.ls(root, long=True)
        nodes += cmds.listRelatives(
            root, allDescendents=True, type="transform", fullPath=True
        ) or []
        return nodes

    @contextlib.contextmanager
    def visible_display_layers(self):
        """Temporarily turn on all display layers in the scene.

        A hidden display layer is exported into the FBX with its
        visibility off, which hides the imported skeleton.
        """
        originals = []
        for layer in cmds.ls(type="displayLayer"):
            plug = "{}.visibility".format(layer)
            value = cmds.getAttr(plug)
            if value:
                continue

            originals.append((plug, value))
            self.set_attribute(plug, True)

        try:
            yield
        finally:
            for plug, value in originals:
                self.set_attribute(plug, value)

    def strip_namespaces(self, nodes):
        """Rename nodes so they no longer carry a namespace.

        Args:
            nodes (list): Nodes to rename.

        Returns:
            list: Long names of the nodes after renaming.
        """
        # Renaming invalidates long paths, so nodes are resolved by uuid.
        uuids = cmds.ls(nodes, uuid=True)
        for uuid in uuids:
            node = cmds.ls(uuid, long=True)[0]
            name = node.rsplit("|", 1)[-1]
            if ":" not in name:
                continue
            cmds.rename(node, name.rsplit(":", 1)[-1])

        return [cmds.ls(uuid, long=True)[0] for uuid in uuids]

    def copy_attributes(self, source, target, attributes):
        """Copy attribute values from source node to target node.

        Values driven by a connection in the rig are not duplicated, so
        they are copied over as static values instead.

        Args:
            source (str): Node to copy the values from.
            target (str): Node to copy the values to.
            attributes (list): Attribute names to copy.
        """
        for attribute in attributes:
            source_attr = "{}.{}".format(source, attribute)
            if not cmds.objExists(source_attr):
                continue

            self.set_attribute(
                "{}.{}".format(target, attribute),
                cmds.getAttr(source_attr)
            )

    def set_attributes(self, node, attributes):
        """Set attribute values on a node.

        Args:
            node (str): Node to set the values on.
            attributes (dict): Attribute names and their values.
        """
        for attribute, value in attributes.items():
            self.set_attribute("{}.{}".format(node, attribute), value)

    def set_attribute(self, attribute, value):
        """Set an attribute value, lifting a lock when there is one.

        Args:
            attribute (str): Attribute to set, as "node.attribute".
            value (Any): Value to set.
        """
        if not cmds.objExists(attribute):
            return

        if cmds.listConnections(
            attribute, source=True, destination=False
        ):
            return

        # The rig may have locked the attribute, which the duplicate
        # inherits, so the lock is lifted for the change.
        locked = cmds.getAttr(attribute, lock=True)
        if locked:
            cmds.setAttr(attribute, lock=False)

        cmds.setAttr(attribute, value)

        if locked:
            cmds.setAttr(attribute, lock=True)
