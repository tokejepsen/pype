# -*- coding: utf-8 -*-
from maya import cmds  # noqa
import pyblish.api
from openpype.lib import BoolDef
from openpype.pipeline import OptionalPyblishPluginMixin
from openpype.hosts.maya.api.lib import get_namespace


class CollectFbxAnimation(pyblish.api.InstancePlugin,
                          OptionalPyblishPluginMixin):
    """Collect Animated Rig Data for FBX Extractor."""

    order = pyblish.api.CollectorOrder + 0.2
    label = "Collect Fbx Animation"
    hosts = ["maya"]
    families = ["animation"]
    optional = True
    export_from_skeleton_root = False

    @classmethod
    def get_attribute_defs(cls):
        defs = super(CollectFbxAnimation, cls).get_attribute_defs()
        defs.append(
            BoolDef(
                "export_from_skeleton_root",
                label="Export from skeleton root",
                tooltip=(
                    "Export the FBX starting from the top-most skeleton "
                    "root node (joint, locator or group) instead of the "
                    "rig root group."
                ),
                default=cls.export_from_skeleton_root
            )
        )
        return defs

    def process(self, instance):
        if not self.is_active(instance.data):
            return
        skeleton_sets = [
            i for i in instance
            if i.endswith("skeletonAnim_SET")
        ]
        if not skeleton_sets:
            return

        include_mesh = instance.data.get("includeSkeletonMesh", False)
        self.log.debug(
            "includeSkeletonMesh attribute: {}".format(include_mesh)
        )

        attr_values = self.get_attr_values_from_data(instance.data)
        export_from_skeleton_root = attr_values.get(
            "export_from_skeleton_root", self.export_from_skeleton_root
        )
        self.log.debug(
            "export_from_skeleton_root attribute: {}".format(
                export_from_skeleton_root
            )
        )

        instance.data["families"].append("animation.fbx")
        instance.data["animated_skeletons"] = {}
        instance.data["skeleton_mesh_included"] = False
        instance.data["skeleton_export_roots"] = {}

        for skeleton_set in skeleton_sets:
            skeleton_content = cmds.sets(skeleton_set, query=True) or []
            set_name = skeleton_set.split(":")[-1]
            mesh_content = []

            skeleton_roots = skeleton_content
            if export_from_skeleton_root:
                resolved_roots = self.get_skeleton_roots(skeleton_content)
                if resolved_roots:
                    skeleton_roots = resolved_roots
                    instance.data["skeleton_export_roots"][set_name] = (
                        resolved_roots
                    )
                    self.log.debug(
                        "Resolved skeleton roots for {}: {}".format(
                            skeleton_set, skeleton_roots
                        ))
                else:
                    self.log.warning(
                        "No skeleton root found under {}; using raw set "
                        "members instead.".format(skeleton_set)
                    )

            if include_mesh:
                # Try sibling skeletonMesh_SET first
                mesh_set = skeleton_set.replace(
                    "skeletonAnim_SET", "skeletonMesh_SET"
                )
                if cmds.objExists(mesh_set):
                    mesh_content = cmds.sets(mesh_set, query=True) or []
                    if mesh_content:
                        self.log.debug(
                            "Using mesh set {} with members: {}".format(
                                mesh_set, mesh_content
                            ))

                # If mesh set is empty or missing, derive from skin clusters
                if not mesh_content:
                    mesh_content = self.get_skinned_meshes(skeleton_content)
                    if mesh_content:
                        self.log.debug(
                            "Derived meshes for {}: {}".format(
                                skeleton_set, mesh_content
                            ))

                # Always collect blendshape-deformed meshes
                namespace = get_namespace(skeleton_set)
                blendshape_meshes = self.get_blendshape_meshes(namespace)
                # Deduplicate against already collected meshes
                for mesh in blendshape_meshes:
                    if mesh not in mesh_content:
                        mesh_content.append(mesh)
                if blendshape_meshes:
                    self.log.debug(
                        "Added blendshape meshes for {}: {}".format(
                            skeleton_set, blendshape_meshes
                        ))

                if not mesh_content:
                    self.log.warning(
                        "Could not resolve any meshes for {}; "
                        "FBX will contain the skeleton only.".format(
                            skeleton_set
                        ))

            # Build final export list: resolved roots + meshes
            out_members = skeleton_roots[:]
            if mesh_content:
                out_members = out_members + mesh_content
                instance.data["skeleton_mesh_included"] = True

            self.log.debug(
                "Collected animated skeleton data for {}: {}".format(
                    set_name, out_members
                ))
            if out_members:
                instance.data["animated_skeletons"][set_name] = (
                    out_members
                )

    def get_skinned_meshes(self, nodes):
        """Derive skinned mesh transforms from skeleton joints.

        Args:
            nodes (list): Nodes to search for joints.

        Returns:
            list: Long names of transform nodes for skinned meshes.
        """
        if not nodes:
            return []

        # The skeleton set may only contain the root group, so include
        # descendant joints as well.
        joints = cmds.ls(nodes, type="joint", long=True) or []
        joints += cmds.listRelatives(
            nodes, allDescendents=True, type="joint", fullPath=True
        ) or []
        joints = list(set(joints))
        if not joints:
            return []

        # Find skin clusters connected to these joints
        skin_clusters = cmds.listConnections(
            joints,
            type="skinCluster",
            source=False,
            destination=True
        ) or []

        # Deduplicate skin clusters
        skin_clusters = list(set(skin_clusters))

        # Get geometry from each skin cluster
        meshes = []
        for skin_cluster in skin_clusters:
            geometry = cmds.skinCluster(
                skin_cluster,
                query=True,
                geometry=True
            ) or []
            for node in geometry:
                # Convert shape to transform if needed
                if cmds.objectType(node, isAType="shape"):
                    parents = cmds.listRelatives(
                        node,
                        parent=True,
                        fullPath=True
                    ) or []
                    if parents:
                        meshes.append(parents[0])
                else:
                    meshes.append(node)

        # Deduplicate while preserving order
        seen = set()
        result = []
        for mesh in meshes:
            if mesh not in seen:
                seen.add(mesh)
                result.append(mesh)

        return result

    def is_skeleton_content(self, node):
        """Check whether a node and its hierarchy are skeleton only.

        Args:
            node (str): Node to check.

        Returns:
            bool: True when the node is a transform and its hierarchy
                contains only transforms (joints included) and locators.
        """
        if not cmds.objectType(node, isAType="transform"):
            return False

        hierarchy = [node]
        hierarchy += cmds.listRelatives(
            node, allDescendents=True, fullPath=True
        ) or []
        for child in hierarchy:
            if cmds.objectType(child, isAType="transform"):
                continue
            if cmds.objectType(child) == "locator":
                continue
            return False

        return True

    def is_locator(self, node):
        """Check whether a node is a transform holding a locator shape.

        Args:
            node (str): Node to check.

        Returns:
            bool: True when the node has a locator shape.
        """
        shapes = cmds.listRelatives(node, shapes=True, fullPath=True) or []
        return any(
            cmds.objectType(shape) == "locator" for shape in shapes
        )

    def get_skeleton_roots(self, nodes):
        """Resolve the top-most skeleton roots from the given nodes.

        Gathers all joints directly in the node list and all descendant
        joints, then filters to keep only the top-most joints (those that
        are not children of another candidate joint). Each top-most joint
        is then promoted upwards as long as its parent only holds
        skeleton content (transforms and locators), so a motion root
        locator or a joints-only group becomes the root. Promotion only
        passes through locators and nodes that are members of `nodes`,
        so rig groups above the skeleton stay out of the export.

        Args:
            nodes (list): Nodes to search for joints.

        Returns:
            list: Short unique names of top-most skeleton root nodes.
        """
        if not nodes:
            return []

        # Gather candidate joints: direct joints + all descendant joints
        joints = cmds.ls(nodes, type="joint", long=True) or []
        joints += cmds.listRelatives(
            nodes, allDescendents=True, type="joint", fullPath=True
        ) or []
        joints = sorted(set(joints))
        if not joints:
            return []

        # Keep only top-most joints: discard any joint that is a
        # descendant of another candidate joint
        top_joints = []
        for joint in joints:
            is_child = False
            for other in joints:
                if other != joint and joint.startswith(other + "|"):
                    is_child = True
                    break
            if not is_child:
                top_joints.append(joint)

        # Promote each top-most joint to the highest ancestor that still
        # only contains skeleton content
        members = set(cmds.ls(nodes, long=True) or [])
        promoted_roots = []
        for root in top_joints:
            while True:
                parents = cmds.listRelatives(
                    root, parent=True, fullPath=True
                ) or []
                if not parents:
                    break
                parent = parents[0]
                # Only set members and locators are promoted to, so the
                # rig groups above the skeleton stay out of the export.
                if parent not in members and not self.is_locator(parent):
                    break
                if not self.is_skeleton_content(parent):
                    break
                root = parent
            promoted_roots.append(root)

        # Promotion can produce duplicates or nested roots, so filter to
        # the top-most nodes again
        promoted_roots = sorted(set(promoted_roots))
        top_roots = []
        for root in promoted_roots:
            is_child = False
            for other in promoted_roots:
                if other != root and root.startswith(other + "|"):
                    is_child = True
                    break
            if not is_child:
                top_roots.append(root)

        return cmds.ls(top_roots)

    def _to_transforms(self, nodes):
        """Convert shapes to transforms and deduplicate.

        Args:
            nodes (list): Nodes (shapes or transforms) to convert.

        Returns:
            list: Long names of transform nodes, deduplicated.
        """
        meshes = []
        for node in nodes:
            # Convert shape to transform if needed
            if cmds.objectType(node, isAType="shape"):
                parents = cmds.listRelatives(
                    node,
                    parent=True,
                    fullPath=True
                ) or []
                if parents:
                    meshes.append(parents[0])
            else:
                # Normalize to long path for consistent deduplication
                long_names = cmds.ls(node, long=True) or []
                if long_names:
                    meshes.append(long_names[0])

        # Deduplicate while preserving order
        seen = set()
        result = []
        for mesh in meshes:
            if mesh not in seen:
                seen.add(mesh)
                result.append(mesh)

        return result

    def get_blendshape_meshes(self, namespace):
        """Derive mesh transforms for blendShape deformed and target geo.

        Args:
            namespace (str): Namespace to limit search, empty string for root.

        Returns:
            list: Long names of transform nodes for deformed and target
                  blendshape meshes.
        """
        # Don't scan entire scene for blendShapes if no namespace given
        if not namespace:
            return []

        # List blendShape nodes in the namespace (including nested)
        prefix = "{}:".format(namespace)
        blendshape_nodes = [
            node for node in cmds.ls(type="blendShape") or []
            if node.rsplit("|", 1)[-1].startswith(prefix)
        ]

        # Collect deformed geometry
        deformed_nodes = []
        for blendshape_node in blendshape_nodes:
            geometry = cmds.blendShape(
                blendshape_node,
                query=True,
                geometry=True
            ) or []
            deformed_nodes.extend(geometry)

        # Collect source/target geometry
        source_nodes = []
        for blendshape_node in blendshape_nodes:
            sources = cmds.listConnections(
                blendshape_node,
                source=True,
                destination=False,
                type="mesh",
                shapes=True
            ) or []
            source_nodes.extend(sources)

        # Convert and deduplicate both lists together
        all_nodes = deformed_nodes + source_nodes
        return self._to_transforms(all_nodes)
