# -*- coding: utf-8 -*-
from maya import cmds  # noqa
import pyblish.api
from openpype.pipeline import OptionalPyblishPluginMixin


class CollectFbxAnimation(pyblish.api.InstancePlugin,
                          OptionalPyblishPluginMixin):
    """Collect Animated Rig Data for FBX Extractor."""

    order = pyblish.api.CollectorOrder + 0.2
    label = "Collect Fbx Animation"
    hosts = ["maya"]
    families = ["animation"]
    optional = True

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

        instance.data["families"].append("animation.fbx")
        instance.data["animated_skeletons"] = {}
        instance.data["skeleton_mesh_included"] = False

        for skeleton_set in skeleton_sets:
            skeleton_content = cmds.sets(skeleton_set, query=True) or []
            set_name = skeleton_set.split(":")[-1]
            mesh_content = []

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
                            "Derived skinned meshes for {}: {}".format(
                                skeleton_set, mesh_content
                            ))
                    else:
                        self.log.warning(
                            "Could not resolve any skinned meshes for {}; "
                            "FBX will contain the skeleton only.".format(
                                skeleton_set
                            ))

                if mesh_content:
                    skeleton_content = skeleton_content + mesh_content
                    instance.data["skeleton_mesh_included"] = True

            self.log.debug(
                "Collected animated skeleton data for {}: {}".format(
                    set_name, skeleton_content
                ))
            if skeleton_content:
                instance.data["animated_skeletons"][set_name] = (
                    skeleton_content
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
