import os
import json

from bson.objectid import ObjectId

import pymel.core as pc

import pyblish.api


class CollectProjection(pyblish.api.InstancePlugin):
    """Collect The geometry, camera and texture for projection."""

    # Offset to be after instance collection.
    order = pyblish.api.CollectorOrder + 0.01
    label = "Collect Projection"
    hosts = ["maya"]
    families = ["projection"]

    def ensure_unique_id(self, id):
        if io.find_one({"_id": id}) is None:
            return id
        else:
            return self.ensure_unique_id(ObjectId())

    def process(self, instance):
        # Collect nodes data.
        material_types = ["lambert", "surfaceShader"]
        cameras = []
        cameras_data = {}
        assignments = []
        for node in instance[:]:
            self.log.info("Processing {}".format(node))
            shading_engine = None
            shape = None
            node = pc.PyNode(node)

            if node.nodeType() == "mesh":
                shape = pc.PyNode(node)
                shading_engine = shape.connections(type="shadingEngine")[0]

            if node.nodeType() == "transform":
                for shape in node.getShapes():
                    self.log.info("Processing {}".format(shape))
                    try:
                        shading_engine = shape.connections(
                            type="shadingEngine"
                        )[0]
                        break
                    except IndexError:
                        continue

            if shading_engine is None:
                continue

            material = shading_engine.connections(type=material_types)[0]

            node_assignments = []
            projection_connections = material.connections(
                type="projection", connections=True
            )
            for attribute, projection in projection_connections:
                projection_cameras = projection.connections(type="camera")
                if not projection_cameras:
                    self.log.warning(
                        "No camera found for projection {}. "
                        "Skipping node.".format(projection)
                    )
                    continue

                cameras.append(projection_cameras[0])

                try:
                    cameras_data[projection_cameras[0].name()].append(
                        shape.name()
                    )
                except KeyError:
                    cameras_data[projection_cameras[0].name()] = [shape.name()]

                file_node = projection.connections(type="file")[0]
                path = file_node.fileTextureName.get()
                assignment = {
                    "path": path,
                    "material": material.name(),
                    "shape": shape.name(),
                    "attribute": attribute.name(includeNode=False),
                    "projection": True
                }
                assignments.append(assignment)
                node_assignments.append(assignment)

            # Non projected materials.
            if not projection_connections:
                material_connections = material.connections(
                    type="file", connections=True
                )
                path = None
                color = None
                attribute = None
                try:
                    file_node = material_connections[0][1]
                    path = file_node.fileTextureName.get()
                    attribute = material_connections[0][0].name(
                        includeNode=False
                    )
                except IndexError:
                    self.log.info(
                        "Could not find any texture on {}".format(
                            material.name()
                        )
                    )
                    color = material.color.get()
                    attribute = "color"

                assignment = {
                    "path": path,
                    "material": material.name(),
                    "shape": shape.name(),
                    "attribute": attribute,
                    "projection": False,
                    "color": color
                }
                assignments.append(assignment)
                node_assignments.append(assignment)

            # Check for supported assignments.
            msg = "Could not find any supported materials on {}".format(
                shape.name()
            )
            assert node_assignments, msg

        # Collect camera instances (Will be validated to a single camera).
        if cameras:
            camera_name = cameras[0].getTransform().name()
            camera_instance = instance.context.create_instance(camera_name)
            camera_instance.data.update(instance.data)
            camera_instance.data["name"] = instance.data["name"] + "_camera"
            camera_instance.data["subset"] += "Camera"
            camera_instance.data["family"] = "camera"
            camera_instance.data["families"] = []
            camera_instance.data["setMembers"] = [camera_name]
            camera_instance.data["versionId"] = self.ensure_unique_id(
                ObjectId()
            )
            camera_instance.data["objectName"] = instance.data["name"]

        # Collect pointcache instance.
        pointcache_instance = instance.context.create_instance(instance[0])
        pointcache_instance[:] = instance[:]
        pointcache_instance.data.update(instance.data)
        pointcache_instance.data["name"] = (
            instance.data["name"] + "_pointcache"
        )
        pointcache_instance.data["subset"] += "Pointcache"
        pointcache_instance.data["family"] = "pointcache"
        pointcache_instance.data["families"] = []
        pointcache_instance.data["versionId"] = self.ensure_unique_id(
            ObjectId()
        )
        pointcache_instance.data["objectName"] = instance.data["name"]

        # Collect image instances.
        version_ids = {}
        paths = []
        for data in assignments:
            if data["path"] in paths:
                continue

            if data["path"] is None:
                continue

            paths.append(data["path"])

            image_instance = instance.context.create_instance(data["path"])
            image_instance.data.update(instance.data)
            name = "{}{}{}".format(
                instance.data["name"],
                data["material"].title(),
                data["attribute"].title()
            )
            image_instance.data["name"] = name
            image_instance.data["label"] = "{} ({})".format(
                name, os.path.basename(data["path"])
            )
            image_instance.data["subsetGroup"] = (
                instance.data["subset"] + "Image"
            )
            image_instance.data["subset"] = name
            image_instance.data["family"] = "image"
            image_instance.data["families"] = []

            if data["path"] not in version_ids:
                version_id = self.ensure_unique_id(ObjectId())
                image_instance.data["versionId"] = version_id
                version_ids[data["path"]] = str(version_id)

            ext = os.path.splitext(data["path"])[1][1:]
            image_instance.data["representations"] = [
                {
                    "name": ext,
                    "ext": ext,
                    "files": os.path.basename(data["path"]),
                    "stagingDir": os.path.dirname(data["path"])
                }
            ]
            self.log.info(image_instance.data["representations"])

        for data in assignments:
            if data["path"] is None:
                continue

            data["versionId"] = version_ids[data["path"]]
            del data["path"]

        # Collect instance data.
        instance.data["jsonData"] = {
            "assignments": assignments,
            "pointcacheVersionId": str(pointcache_instance.data["versionId"])
        }

        if cameras:
            instance.data["jsonData"].update(
                {
                    "cameraVersionId": str(camera_instance.data["versionId"]),
                    "cameraScale": cameras[0].cameraScale.get()
                }
            )

        self.log.info(
            json.dumps(instance.data["jsonData"], sort_keys=True, indent=4)
        )
        instance.data["cameras"] = list(set(cameras))
        instance.data["cameras_data"] = cameras_data
