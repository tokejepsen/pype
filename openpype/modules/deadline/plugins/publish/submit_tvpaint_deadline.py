"""Submit TVPaint render layers to Deadline for farm rendering.

This plugin submits TVPaint render instances to Deadline with a four-tier
job topology:
1. Render jobs per layer (chunked by frame range) - releases TVPaint license immediately
2. Fill jobs per layer (depends on corresponding render job) - fills reference frames
3. Composite jobs per instance (depends on fill jobs) - composes layers into final output
4. Integration job (from submit_publish_job.py) - publishes representations

All files are stored in the shared output_dir (accessible to farm workers).
No auxiliary files are uploaded to Deadline.
"""

import os
import json
import copy

import attr
import pyblish.api

from openpype.lib import NumberDef
from openpype.pipeline import legacy_io
from openpype.pipeline.publish import get_instance_staging_dir
from openpype.settings import get_project_settings
from openpype.hosts.tvpaint.lib import get_frame_filename_template
from openpype_modules.deadline import abstract_submit_deadline
from openpype_modules.deadline.abstract_submit_deadline import DeadlineJobInfo


@attr.s
class TVPaintPluginInfo(object):
    """Deadline PluginInfo for TVPaint render tasks."""

    Arguments: str = attr.ib(default=None)
    SingleFramesOnly: str = attr.ib(default="True")


class TVPaintSubmitDeadline(abstract_submit_deadline.AbstractSubmitDeadline):
    """Submit TVPaint render to Deadline.

    Renders layers to Deadline with frame chunking, then composites results.
    """

    label = "Submit TVPaint to Deadline"
    hosts = ["tvpaint"]
    families = ["render.farm"]
    optional = True
    active = True
    use_published = True

    # Presets
    priority = 50
    render_group = "tvpaint"
    # Farm render script module path (machine-independent reference)
    farm_render_module = "openpype.hosts.tvpaint.scripts.farm_render"
    output_directory_template_name = "work_renders"

    @classmethod
    def get_attribute_defs(cls):
        return [
            NumberDef(
                "priority",
                label="Priority",
                default=cls.priority,
                decimals=0,
                minimum=1,
                maximum=250
            ),
        ]

    def process(self, instance):
        """Override base process to use replace_in_path=False.

        TVPaint render output filenames don't contain the scene file name
        (they are named like '{layer}_{frame}.png'), so path replacement is
        not needed. Calling from_published_scene(replace_in_path=True) on an
        instance without expectedFiles set crashes in
        replace_with_published_scene_path.
        """
        self._instance = instance
        context = instance.context
        self._deadline_url = context.data.get("defaultDeadline")
        self._deadline_url = instance.data.get(
            "deadlineUrl", self._deadline_url)

        assert self._deadline_url, "Requires Deadline Webservice URL"

        file_path = None
        if self.use_published:
            # replace_in_path=False: TVPaint output paths don't embed the
            # scene filename, so no substitution is needed.
            file_path = self.from_published_scene(replace_in_path=False)

        if not file_path:
            self.log.warning("Falling back to workfile")
            file_path = context.data["currentFile"]

        self.scene_path = file_path
        self.log.info("Using {} for render/export.".format(file_path))

        self.job_info = self.get_job_info()
        self.plugin_info = self.get_plugin_info()
        self.aux_files = self.get_aux_files()

        self.process_submission()

    def get_job_info(self):
        """Return base DeadlineJobInfo template.

        This is used as the template for all render and composite jobs.
        """
        instance = self._instance
        context = instance.context

        job_info = DeadlineJobInfo(Plugin="OpenPype")

        # Set basic job properties
        job_info.Pool = instance.data.get("pool", "")
        job_info.SecondaryPool = instance.data.get("secondaryPool", "")
        job_info.Group = "none"
        job_info.Priority = instance.data.get("priority", self.priority)

        # Set environment
        job_info.EnvironmentKeyValue.update(self._get_environment_variables())
        job_info.add_render_job_env_var()

        # Add expected output files
        expected_files = instance.data.get("expectedFiles", [])
        for filepath in expected_files:
            job_info.OutputDirectory += os.path.dirname(filepath)
            job_info.OutputFilename += os.path.basename(filepath)

        return job_info

    def get_plugin_info(self):
        """Return base PluginInfo template.

        This returns a basic template. In process_submission(), we override
        the Arguments and SingleFramesOnly for each specific job.
        """
        plugin_info = TVPaintPluginInfo(
            Arguments="",  # Overridden per-job
            SingleFramesOnly="True"  # Overridden per-job
        )
        return attr.asdict(plugin_info)

    def get_aux_files(self):
        """Return empty list - no auxiliary files uploaded.

        All files are stored in shared project directory and accessed
        directly by farm workers, matching the Nuke pattern.
        """
        return []

    def _get_environment_variables(self):
        """Build environment variables for farm job."""
        keys = [
            "AVALON_PROJECT",
            "AVALON_ASSET",
            "AVALON_TASK",
            "AVALON_APP_NAME",
            "FTRACK_API_KEY",
            "FTRACK_API_USER",
            "FTRACK_SERVER",
        ]

        env_vars = dict(
            {key: os.environ[key] for key in keys if key in os.environ},
            **legacy_io.Session
        )

        # Add all OPENPYPE_* environment variables (except OPENPYPE_VERSION)
        for key, value in os.environ.items():
            if key.lower().startswith("openpype_") and key != "OPENPYPE_VERSION":
                env_vars[key] = value

        env_vars["OPENPYPE_LOG_NO_COLORS"] = "1"

        return env_vars

    def _get_output_dir_for(self, instance):
        """Get output directory for a given instance.

        Args:
            instance: The publish instance to get output directory for.

        Returns:
            str: The output directory path.
        """
        output_dir = instance.data.get("outputDir")

        if not output_dir:
            # Try to use anatomy render template to resolve output directory
            try:
                context = instance.context
                anatomy = context.data.get("anatomy")
                if anatomy:
                    template_data = copy.deepcopy(
                        instance.data.get("anatomyData", {})
                    )
                    # Ensure required keys are present in template data
                    template_data.setdefault("family", instance.data.get("family", "render"))
                    template_data.setdefault("subset", instance.data.get("subset", "render"))
                    template_data.setdefault("version", instance.data.get("version", 1))

                    # Resolve render folder using anatomy template
                    render_templates = anatomy.templates_obj[self.output_directory_template_name]
                    if "folder" in render_templates:
                        base_folder = render_templates["folder"].format_strict(
                            template_data
                        )
                        current_file = context.data.get("currentFile", "")
                        workfile_basename = os.path.splitext(
                            os.path.basename(current_file)
                        )[0]
                        subset = instance.data.get("subset", "render")
                        output_dir = os.path.join(
                            base_folder, workfile_basename, instance.data["subset"]
                        )
                        self.log.info(
                            f"Resolved output dir from anatomy render template: "
                            f"{output_dir}"
                        )
            except Exception as e:
                self.log.warning(
                    f"Failed to resolve output dir from anatomy template: {e}"
                )

            # Fall back to staging dir if anatomy resolution failed
            if not output_dir:
                output_dir = get_instance_staging_dir(instance)

        # Create output directory if needed
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        return output_dir

    def _get_output_dir(self):
        """Get shared output directory from instance data."""
        return self._get_output_dir_for(self._instance)

    def _get_batch_name(self):
        """Return a batch name derived from the scene filename."""
        context = self._instance.context
        scene_file = context.data.get("currentFile", "") or self.scene_path or ""
        batch_name = os.path.basename(scene_file)
        if not batch_name:
            batch_name = "TVPaint"
        return batch_name

    def _write_render_context(self, context_data, output_dir, filename="render_context.json"):
        """Write a context JSON file to the output directory.

        This file contains all information needed for farm workers to
        render and composite layers.
        """
        render_context_path = os.path.join(output_dir, filename)

        # Write JSON file
        with open(render_context_path, "w") as f:
            json.dump(context_data, f, indent=2)

        self.log.info(f"Wrote render context to {render_context_path}")

        # Return forward-slash normalized path for Deadline
        return render_context_path.replace("\\", "/")

    def _get_scene_file(self):
        """Get published TVPaint scene file path."""
        instance = self._instance
        context = instance.context

        # Use from_published_scene() if use_published is True
        if self.use_published:
            published_scene = self.from_published_scene(replace_in_path=True)
            if published_scene:
                self.log.info(f"Using published scene: {published_scene}")
                return published_scene.replace("\\", "/")

        # Fall back to working file
        current_file = context.data.get("currentFile", "")
        return current_file.replace("\\", "/")

    def _get_exr_conversion_settings(self, instance):
        """Get EXR conversion settings from project settings.

        Reads ExtractConvertToEXR plugin settings from the project.

        Args:
            instance: Publish instance.

        Returns:
            dict with keys {enabled, exr_compression, replace_pngs} or None if not found.
        """
        try:
            context = instance.context
            project_name = context.data.get("projectName") or legacy_io.active_project()

            if not project_name:
                self.log.warning("Could not determine project name for EXR settings")
                return None

            settings = get_project_settings(project_name)
            exr_settings = (
                settings
                .get("tvpaint", {})
                .get("publish", {})
                .get("ExtractConvertToEXR", {})
            )

            return {
                "enabled": exr_settings.get("enabled", False),
                "exr_compression": exr_settings.get("exr_compression", "ZIP"),
                "replace_pngs": exr_settings.get("replace_pngs", True),
            }
        except Exception as e:
            self.log.warning(f"Failed to get EXR conversion settings: {e}")
            return None

    def _submit_exr_conversion_job(
        self,
        instance,
        depends_on_job_id,
        output_dir,
        mark_in,
        mark_out,
        exr_settings
    ):
        """Submit EXR conversion job that depends on previous render/fill/composite job.

        Args:
            instance: Publish instance.
            depends_on_job_id (str): Job ID this conversion job depends on.
            output_dir (str): Output directory containing PNG files.
            mark_in (int): Start frame.
            mark_out (int): End frame.
            exr_settings (dict): Settings with keys {exr_compression, replace_pngs}.

        Returns:
            str: Submitted EXR conversion job ID.
        """
        # Build list of PNG filenames from output_dir
        output_template = get_frame_filename_template(mark_out)
        png_filenames = []
        for frame_idx in range(mark_in, mark_out + 1):
            png_filename = output_template.format(frame=frame_idx)
            png_filenames.append(png_filename)

        # Write convert_context.json
        convert_context_data = {
            "output_dir": output_dir,
            "filenames": png_filenames,
            "exr_compression": exr_settings.get("exr_compression", "ZIP"),
            "replace_pngs": exr_settings.get("replace_pngs", True),
        }

        convert_context_path = self._write_render_context(
            convert_context_data, output_dir, filename="convert_context.json"
        )

        # Submit EXR conversion job
        inst_subset = instance.data.get("subset", "")
        base_job_info = self.get_job_info()
        batch_name = self._get_batch_name()

        exr_job_info = copy.deepcopy(base_job_info)
        exr_job_info.Name = f"Convert to EXR - {inst_subset}"
        exr_job_info.BatchName = batch_name
        exr_job_info.Frames = "0"  # Single task
        exr_job_info.ChunkSize = 1
        exr_job_info.JobDependencies = depends_on_job_id
        exr_job_info.IsFrameDependent = False

        # Plugin info with convert arguments
        plugin_info = TVPaintPluginInfo(
            Arguments=(
                f"run_module openpype.hosts.tvpaint.scripts.farm_convert_to_exr"
                f" --convert-context \"{convert_context_path}\""
            ),
            SingleFramesOnly="True"  # Single task
        )

        # Add asset dependency for convert context
        exr_job_info.AssetDependency += convert_context_path

        # Build and submit payload
        payload = self.assemble_payload(
            job_info=exr_job_info,
            plugin_info=attr.asdict(plugin_info),
            aux_files=self.get_aux_files()
        )

        exr_job_id = self.submit(payload)
        self.log.info(f"Submitted EXR conversion job {exr_job_id} for {inst_subset}")

        # Update instance data to reflect converted EXR files.
        # When replace_pngs is False, keep both PNG and EXR so that
        # prepare_representations creates two representations.
        exr_filenames = [f.replace(".png", ".exr") for f in png_filenames]
        exr_paths = [os.path.join(output_dir, f) for f in exr_filenames]
        if exr_settings.get("replace_pngs", True):
            instance.data["expectedFiles"] = exr_paths
        else:
            png_paths = [os.path.join(output_dir, f) for f in png_filenames]
            instance.data["expectedFiles"] = png_paths + exr_paths

        return exr_job_id

    def _get_render_layer_group_id(self, inst):
        """Return the render-layer group key for an instance.

        Render pass instances are grouped with their parent render layer so
        that all passes in the same layer share a single render job.

        Returns:
            str: The group key (render layer instance_id, or the instance's
                 own subset name when no parent layer exists).
        """
        creator_identifier = inst.data.get("creator_identifier", "")
        if creator_identifier == "render.layer":
            # The render layer IS the group root — its own instance_id is the key.
            return inst.data.get("instance_id") or inst.data.get("subset", "")
        if creator_identifier == "render.pass":
            render_layer_id = (
                inst.data.get("creator_attributes", {})
                .get("render_layer_instance_id")
            )
            if render_layer_id:
                return render_layer_id
        # render.scene and anything else: each instance is its own group.
        return inst.data.get("subset", "")

    def _submit_shared_render_jobs(self, context):
        """Submit render jobs grouped by render layer.

        All render passes that belong to the same render layer are rendered in
        a single TVPaint job.  Optionally a single fill job is added when any
        layer in the group has reference frames.

        Topology per render-layer group:
          - 1 render job  (renders all unique layers in the group)
          - 0-1 fill job  (if any layer has reference frames)
          - per-instance composite jobs are submitted in process_submission()

        Returns:
            dict with keys:
                composite_dependency_job_ids_by_instance_subset
                skip_composite_by_instance_label
                render_info_by_instance_subset
        """
        farm_instances = [
            inst for inst in context
            if "render.farm" in inst.data.get("families", [])
            and inst.data["active"]
        ]

        if not farm_instances:
            return None

        context_obj = context
        scene_mark_in_global = context_obj.data["sceneMarkIn"]

        base_job_info = self.get_job_info()
        batch_name = self._get_batch_name()
        scene_file = self._get_scene_file()

        # --- 1. Group instances by render layer ----------------------------
        # group_id -> {"instances": [...], "render_layer_inst": inst|None}
        render_layer_groups = {}
        for inst in farm_instances:
            group_id = self._get_render_layer_group_id(inst)
            if group_id not in render_layer_groups:
                render_layer_groups[group_id] = {
                    "instances": [],
                    "render_layer_inst": None,
                }
            render_layer_groups[group_id]["instances"].append(inst)
            if inst.data.get("creator_identifier") == "render.layer":
                render_layer_groups[group_id]["render_layer_inst"] = inst

        self.log.info(
            f"Grouped {len(farm_instances)} farm instances into "
            f"{len(render_layer_groups)} render-layer group(s)"
        )

        # --- 2. Per-group: compute data, submit render + fill jobs ----------
        # group_id -> {last_job_id, shared_render_dir, render_context_path,
        #               render_context_data, mark_in, mark_out,
        #               full_extraction_data}
        render_layer_group_results = {}

        for group_id, group_data in render_layer_groups.items():
            instances = group_data["instances"]
            # Prefer the render.layer instance as the reference; fall back to first.
            ref_inst = group_data["render_layer_inst"] or instances[0]
            ref_subset = ref_inst.data.get("subset", group_id)

            # Compute frame range per instance (all instances).
            # For the shared render job, use union of non-render.layer instances only.
            per_instance_ranges_local = {}
            ranges = []
            pass_only_ranges = []

            for inst in instances:
                asset_doc = inst.data.get("assetEntity") or {}
                project_frame_start = (
                    asset_doc.get("data", {}).get("frameStart")
                    or scene_mark_in_global
                )
                inst_fs = inst.data.get("frameStart", project_frame_start)
                inst_fe = inst.data.get(
                    "frameEnd",
                    project_frame_start + (
                        context_obj.data["sceneMarkOut"] - scene_mark_in_global
                    )
                )
                inst_mi = int(scene_mark_in_global + (inst_fs - project_frame_start))
                inst_mo = int(scene_mark_in_global + (inst_fe - project_frame_start))
                ranges.append((inst_mi, inst_mo))
                per_instance_ranges_local[inst.data.get("subset", "")] = (inst_mi, inst_mo)

                # Collect non-render.layer instances for render job range computation
                if inst.data.get("creator_identifier") != "render.layer":
                    pass_only_ranges.append((inst_mi, inst_mo))

            # Build per-layer pass ranges: each layer uses the union of ranges
            # from all pass instances that include it.
            pass_range_by_layer_id = {}
            for inst in instances:
                if inst.data.get("creator_identifier") == "render.layer":
                    continue
                inst_subset = inst.data.get("subset", "")
                # Use range from per_instance_ranges_local (always present at this point)
                if inst_subset not in per_instance_ranges_local:
                    continue
                inst_mi, inst_mo = per_instance_ranges_local[inst_subset]
                for layer in inst.data.get("layers", []):
                    lid = layer["layer_id"]
                    if lid not in pass_range_by_layer_id:
                        pass_range_by_layer_id[lid] = (inst_mi, inst_mo)
                    else:
                        ex_mi, ex_mo = pass_range_by_layer_id[lid]
                        pass_range_by_layer_id[lid] = (
                            min(ex_mi, inst_mi), max(ex_mo, inst_mo)
                        )

            # Render job uses pass-only union (render.layer instances excluded).
            # If no passes exist (standalone render.layer), use all instances.
            if pass_only_ranges:
                mark_in = min(r[0] for r in pass_only_ranges)
                mark_out = max(r[1] for r in pass_only_ranges)
                self.log.info(
                    f"Render-layer group '{ref_subset}': computed render job range "
                    f"from {len(pass_only_ranges)} pass instance(s): {mark_in}-{mark_out}"
                )
            else:
                mark_in = min(r[0] for r in ranges)
                mark_out = max(r[1] for r in ranges)
                self.log.info(
                    f"Render-layer group '{ref_subset}': no passes found, "
                    f"using all instance range: {mark_in}-{mark_out}"
                )

            # Collect the union of all unique TVPaint layers in the group.
            all_layers_by_id = {}
            for inst in instances:
                for layer in inst.data.get("layers", []):
                    all_layers_by_id[layer["layer_id"]] = layer
            all_layers = list(all_layers_by_id.values())

            if not all_layers:
                self.log.warning(
                    f"Render-layer group '{group_id}' has no layers — skipping"
                )
                continue

            self.log.info(
                f"Render-layer group '{ref_subset}': {len(instances)} instance(s), "
                f"{len(all_layers)} unique layer(s), frames {mark_in}-{mark_out}"
            )

            # Compute extraction data for ALL layers in this group.
            result = self._collect_extraction_data(
                instance=ref_inst,
                layers=all_layers,
                mark_in=mark_in,
                mark_out=mark_out,
            )
            full_extraction_data = result["extraction_data_by_layer_id"]

            # Trim each layer's extraction data to its actual pass range.
            # Avoids the fill job creating hold-frame hard links for static
            # layers that only need 1 frame.
            for layer_id_key in list(full_extraction_data.keys()):
                lid = (
                    int(layer_id_key)
                    if isinstance(layer_id_key, str)
                    else layer_id_key
                )
                layer_mi, layer_mo = pass_range_by_layer_id.get(
                    lid, (mark_in, mark_out)
                )
                extr_data = full_extraction_data[layer_id_key]
                extr_data["frame_references"] = {
                    k: v
                    for k, v in extr_data["frame_references"].items()
                    if layer_mi <= int(k) <= layer_mo
                }
                extr_data["filenames_by_frame_index"] = {
                    k: v
                    for k, v in extr_data["filenames_by_frame_index"].items()
                    if layer_mi <= int(k) <= layer_mo
                }

            # Shared render output dir = render layer instance's output dir.
            shared_render_dir = self._get_output_dir_for(ref_inst)

            # Build copy_to_output_by_layer_id for single-layer pass instances.
            # These skip the composite job and have their frames copied directly
            # from the shared render dir to their own output dir.
            copy_to_output_by_layer_id = {}
            skip_composite_by_instance_label_local = {}

            for inst in instances:
                inst_layers = inst.data.get("layers", [])
                if len(inst_layers) != 1:
                    continue
                layer_id = inst_layers[0]["layer_id"]
                inst_output_dir = self._get_output_dir_for(inst)

                # Only skip composite when the instance has its own output dir.
                if inst_output_dir == shared_render_dir:
                    continue

                extr_key = (
                    layer_id if layer_id in full_extraction_data
                    else str(layer_id) if str(layer_id) in full_extraction_data
                    else None
                )
                if extr_key is None:
                    continue

                # Use per-instance frame range for this copy target, trimmed
                # to the layer's actual content range.  A layer that only spans
                # part of the shot has null frame_references outside its active
                # range — those frames are never rendered, so we must not
                # include them in expectedFiles or the copy target.
                inst_subset = inst.data.get("subset", "")
                inst_mi, inst_mo = per_instance_ranges_local.get(
                    inst_subset, (mark_in, mark_out)
                )

                # Determine actual content range from non-null frame_references.
                extr_data = full_extraction_data[extr_key]
                non_null_frames = [
                    int(k)
                    for k, v in extr_data.get("frame_references", {}).items()
                    if v is not None and inst_mi <= int(k) <= inst_mo
                ]
                if non_null_frames:
                    copy_mi = min(non_null_frames)
                    copy_mo = max(non_null_frames)
                else:
                    copy_mi, copy_mo = inst_mi, inst_mo

                output_template = get_frame_filename_template(copy_mo)
                copy_to_output_by_layer_id.setdefault(layer_id, []).append({
                    "output_dir": inst_output_dir,
                    "output_template": output_template,
                    "mark_in": copy_mi,
                    "mark_out": copy_mo,
                })
                skip_composite_by_instance_label_local[inst_subset] = None

                # Update per_instance_ranges_local so that render_info (and
                # therefore expectedFiles / EXR conversion) uses the trimmed
                # range rather than the full shot range.
                if copy_mi != inst_mi or copy_mo != inst_mo:
                    per_instance_ranges_local[inst_subset] = (copy_mi, copy_mo)
                    self.log.info(
                        f"Single-layer instance '{inst_subset}': trimmed frame "
                        f"range from {inst_mi}-{inst_mo} to {copy_mi}-{copy_mo} "
                        f"(layer has no content outside that range)"
                    )

                self.log.info(
                    f"Single-layer instance '{inst_subset}' will skip composite; "
                    f"frames {copy_mi}-{copy_mo} copied to {inst_output_dir}"
                )

            # Write render_context.json into the shared render dir.
            render_context_data = {
                "scene_file": scene_file,
                "output_dir": shared_render_dir,
                "extraction_data_by_layer_id": full_extraction_data,
                "layers": [dict(layer) for layer in all_layers],
                "copy_to_output_by_layer_id": copy_to_output_by_layer_id,
            }
            render_context_path = self._write_render_context(
                render_context_data, shared_render_dir
            )

            # Submit 1 render job for the whole group.
            job_info = copy.deepcopy(base_job_info)
            job_info.Name = f"Render - {ref_subset}"
            job_info.BatchName = batch_name
            job_info.Frames = "0"
            job_info.ChunkSize = 1
            job_info.Group = self.render_group

            plugin_info = TVPaintPluginInfo(
                Arguments=(
                    f"run_module {self.farm_render_module}"
                    f" --render-context \"{render_context_path}\""
                ),
                SingleFramesOnly="True",
            )
            job_info.AssetDependency += render_context_path
            job_info.AssetDependency += scene_file

            payload = self.assemble_payload(
                job_info=job_info,
                plugin_info=attr.asdict(plugin_info),
                aux_files=self.get_aux_files(),
            )
            render_job_id = self.submit(payload)
            self.log.info(
                f"Submitted render job {render_job_id} for group '{ref_subset}'"
            )

            # Submit 0-1 fill job if any layer has reference frames.
            has_any_references = any(
                any(
                    int(k) != v and v is not None
                    for k, v in extr_data.get("frame_references", {}).items()
                )
                for extr_data in full_extraction_data.values()
            )

            last_job_id = render_job_id

            if has_any_references:
                fill_job_info = copy.deepcopy(base_job_info)
                fill_job_info.Name = f"Fill References - {ref_subset}"
                fill_job_info.BatchName = batch_name
                fill_job_info.Frames = "0"
                fill_job_info.ChunkSize = 1
                fill_job_info.JobDependencies = render_job_id
                fill_job_info.IsFrameDependent = False

                fill_plugin_info = TVPaintPluginInfo(
                    Arguments=(
                        f"run_module {self.farm_render_module}"
                        f" --render-context \"{render_context_path}\""
                        f" --fill"
                    ),
                    SingleFramesOnly="True",
                )
                fill_job_info.AssetDependency += render_context_path

                fill_payload = self.assemble_payload(
                    job_info=fill_job_info,
                    plugin_info=attr.asdict(fill_plugin_info),
                    aux_files=self.get_aux_files(),
                )
                fill_job_id = self.submit(fill_payload)
                last_job_id = fill_job_id
                self.log.info(
                    f"Submitted fill job {fill_job_id} for group '{ref_subset}'"
                )
            else:
                self.log.info(
                    f"Group '{ref_subset}' has no reference frames to fill"
                )

            render_layer_group_results[group_id] = {
                "last_job_id": last_job_id,
                "shared_render_dir": shared_render_dir,
                "render_context_path": render_context_path,
                "render_context_data": render_context_data,
                "mark_in": mark_in,
                "mark_out": mark_out,
                "full_extraction_data": full_extraction_data,
                "per_instance_ranges": per_instance_ranges_local,
                "skip_composite_by_instance_label_local": (
                    skip_composite_by_instance_label_local
                ),
            }

        if not render_layer_group_results:
            raise RuntimeError("No render jobs were submitted")

        # --- 3. Build per-instance render info -----------------------------
        composite_dependency_job_ids_by_instance_subset = {}
        skip_composite_by_instance_label = {}
        render_info_by_instance_subset = {}

        for inst in farm_instances:
            inst_subset = inst.data.get("subset", "")
            inst_layers = inst.data.get("layers", [])
            group_id = self._get_render_layer_group_id(inst)
            group_result = render_layer_group_results.get(group_id)

            if not group_result:
                self.log.warning(
                    f"No group result for instance '{inst_subset}' (group '{group_id}') "
                    "— skipping"
                )
                continue

            last_job_id = group_result["last_job_id"]
            full_extraction_data = group_result["full_extraction_data"]

            # Per-instance extraction data: only the layers this instance uses.
            inst_extraction_data = {}
            for layer in inst_layers:
                lid = layer["layer_id"]
                if lid in full_extraction_data:
                    inst_extraction_data[lid] = full_extraction_data[lid]
                elif str(lid) in full_extraction_data:
                    inst_extraction_data[str(lid)] = full_extraction_data[str(lid)]

            # Get per-instance frame range if available, else use group union
            per_instance_ranges = group_result.get("per_instance_ranges", {})
            if inst_subset in per_instance_ranges:
                per_inst_mi, per_inst_mo = per_instance_ranges[inst_subset]
            else:
                per_inst_mi, per_inst_mo = group_result["mark_in"], group_result["mark_out"]

            render_info_by_instance_subset[inst_subset] = {
                "render_context_path": group_result["render_context_path"],
                "render_context_data": group_result["render_context_data"],
                "shared_render_dir": group_result["shared_render_dir"],
                "output_dir": self._get_output_dir_for(inst),
                "mark_in": per_inst_mi,
                "mark_out": per_inst_mo,
                "layers": inst_layers,
                "extraction_data_by_layer_id": inst_extraction_data,
            }

            composite_dependency_job_ids_by_instance_subset[inst_subset] = last_job_id

            # Propagate skip-composite info from the group result.
            if inst_subset in group_result["skip_composite_by_instance_label_local"]:
                skip_composite_by_instance_label[inst_subset] = last_job_id
                self.log.info(
                    f"Instance '{inst_subset}' will depend on job {last_job_id} "
                    "instead of composite"
                )

        return {
            "composite_dependency_job_ids_by_instance_subset": (
                composite_dependency_job_ids_by_instance_subset
            ),
            "skip_composite_by_instance_label": skip_composite_by_instance_label,
            "render_info_by_instance_subset": render_info_by_instance_subset,
        }

    def _collect_extraction_data(self, layers=None, mark_in=None, mark_out=None, instance=None):
        """Collect layer extraction data using TVPaint lib functions.

        This gathers the frame information needed for rendering each layer.

        Args:
            layers: List of layer dicts. If None, uses instance.data["layers"].
            mark_in: TVPaint scene-space start frame. Derived from the instance's
                frameStart when not provided.
            mark_out: TVPaint scene-space end frame. Derived from the instance's
                frameEnd when not provided.
            instance: Publish instance to use. If None, uses self._instance.
        """
        from openpype.hosts.tvpaint.api.lib import (
            get_layers_data,
            get_groups_data,
            get_layers_pre_post_behavior,
            get_layers_exposure_frames,
        )
        from openpype.hosts.tvpaint.lib import (
            calculate_layers_extraction_data,
        )

        if instance is None:
            instance = self._instance
        context = instance.context

        # Get frame range in TVPaint scene space.
        # instance.data["frameStart"]/"frameEnd"] are in project frame space;
        # convert back to scene space using the global scene mark origin.
        if mark_in is None or mark_out is None:
            asset_doc = instance.data.get("assetEntity") or {}
            project_frame_start = (
                asset_doc.get("data", {}).get("frameStart")
                or context.data["sceneMarkIn"]
            )
            scene_mark_in_global = context.data["sceneMarkIn"]
            instance_frame_start = instance.data.get("frameStart", project_frame_start)
            instance_frame_end = instance.data.get(
                "frameEnd",
                project_frame_start + (
                    context.data["sceneMarkOut"] - scene_mark_in_global
                )
            )
            if mark_in is None:
                mark_in = scene_mark_in_global + (
                    instance_frame_start - project_frame_start
                )
            if mark_out is None:
                mark_out = scene_mark_in_global + (
                    instance_frame_end - project_frame_start
                )

        # Get layers - from parameter or instance data
        if layers is None:
            layers = instance.data.get("layers", [])
        if not layers:
            raise RuntimeError("No layers provided")

        # Get layer IDs and precompute behavior/exposure
        layer_ids = [layer["layer_id"] for layer in layers]

        behavior_by_layer_id = get_layers_pre_post_behavior(layer_ids)

        exposure_frames_by_layer_id = get_layers_exposure_frames(
            layer_ids, layers
        )

        # Calculate extraction data for each layer
        extraction_data_by_layer_id = calculate_layers_extraction_data(
            layers,
            exposure_frames_by_layer_id,
            behavior_by_layer_id,
            mark_in,
            mark_out
        )

        return {
            "mark_in": mark_in,
            "mark_out": mark_out,
            "layers": layers,
            "behavior_by_layer_id": behavior_by_layer_id,
            "exposure_frames_by_layer_id": exposure_frames_by_layer_id,
            "extraction_data_by_layer_id": extraction_data_by_layer_id,
        }

    def process_submission(self):
        """Submit composite job for this instance.

        Render and fill jobs are submitted once per context by _submit_shared_render_jobs().
        Each instance then submits a composite job (unless it's single-layer and can skip).

        Topology (per render instance):
        - 1 render job (renders all instance layers in one TVPaint session)
        - 0-1 fill job (fills references if any layer has them)
        - 0-1 composite job (skipped for single-layer instances)
        - Integration job (from submit_publish_job.py) depends on composite or last render/fill job

        Returns:
            str: Composite job ID (or render/fill job ID for skipped composite)
        """
        instance = self._instance
        context = instance.context

        # Submit shared render jobs once (guarded by context data)
        if "tvpaint_shared_render_jobs" not in context.data:
            self.log.info("Submitting shared render jobs...")
            shared_data = self._submit_shared_render_jobs(context)
            if shared_data:
                context.data["tvpaint_shared_render_jobs"] = shared_data

        shared_data = context.data.get("tvpaint_shared_render_jobs")
        if not shared_data:
            raise RuntimeError("Failed to submit shared render jobs")

        # Check if this instance should skip composite (single-layer)
        inst_subset = instance.data.get("subset", "")
        skip_composite_by_instance_label = shared_data.get("skip_composite_by_instance_label", {})
        composite_dependency_job_ids = shared_data.get("composite_dependency_job_ids_by_instance_subset", {})
        render_info = shared_data.get("render_info_by_instance_subset", {}).get(inst_subset)

        if inst_subset in skip_composite_by_instance_label:
            # Single-layer instance - skip composite job
            last_job_id = skip_composite_by_instance_label[inst_subset]

            if not last_job_id:
                self.log.warning(
                    f"Instance {inst_subset} marked for skip but no job ID — "
                    f"falling through to composite submission"
                )
                # Fall through to composite submission below
            else:
                self.log.info(
                    f"Skipping composite job for {inst_subset} (single-layer). "
                    f"Using job {last_job_id} as deadline submission."
                )

                # Set expected output files
                output_dir = render_info["output_dir"] if render_info else self._get_output_dir_for(instance)
                mark_in = render_info["mark_in"] if render_info else 0
                mark_out = render_info["mark_out"] if render_info else 0

                output_template = get_frame_filename_template(mark_out)
                instance.data["expectedFiles"] = [
                    os.path.join(output_dir, output_template.format(frame=frame_idx))
                    for frame_idx in range(mark_in, mark_out + 1)
                ]
                instance.data["outputDir"] = output_dir
                instance.data["toBeRenderedOn"] = "deadline"

                # Check if EXR conversion should be applied
                exr_settings = self._get_exr_conversion_settings(instance)
                if exr_settings and exr_settings.get("enabled"):
                    self.log.info(f"Submitting EXR conversion job for {inst_subset}")
                    last_job_id = self._submit_exr_conversion_job(
                        instance=instance,
                        depends_on_job_id=last_job_id,
                        output_dir=output_dir,
                        mark_in=mark_in,
                        mark_out=mark_out,
                        exr_settings=exr_settings
                    )

                # Fetch the job dict for integration
                try:
                    from openpype_modules.deadline.abstract_submit_deadline import requests_get
                    job_url = "{}/api/jobs?JobID={}".format(
                        self._deadline_url, last_job_id
                    )
                    job_response = requests_get(job_url)
                    jobs = job_response.json()
                    dep_job_dict = jobs[0] if jobs else {"_id": last_job_id, "Props": {}}
                except Exception as e:
                    self.log.warning(
                        f"Could not fetch job dict for {last_job_id}: {e}. Using stub."
                    )
                    dep_job_dict = {"_id": last_job_id, "Props": {}}

                instance.data["deadlineSubmissionJob"] = dep_job_dict
                return last_job_id

        # Not skipping composite - submit composite job
        if not render_info:
            raise RuntimeError(f"No render info found for instance {inst_subset}")

        # Get render info for this instance
        render_context_path = render_info["render_context_path"]
        output_dir = render_info["output_dir"]
        mark_in = render_info["mark_in"]
        mark_out = render_info["mark_out"]
        inst_layers = render_info["layers"]

        # Get composite dependency job for this instance
        last_job_id = composite_dependency_job_ids.get(inst_subset)
        if not last_job_id:
            raise RuntimeError(f"No composite dependency job found for instance {inst_subset}")

        self.log.info(
            f"Submitting composite job for {inst_subset} depending on job {last_job_id}"
        )

        # Write composite_context.json to instance's output directory
        render_context_data = render_info["render_context_data"]
        extraction_data_by_layer_id = render_info["extraction_data_by_layer_id"]

        composite_context_data = {
            "raw_render_dir": render_info["shared_render_dir"],
            "output_dir": output_dir,
            "mark_in": mark_in,
            "mark_out": mark_out,
            "layers": [
                dict(layer) for layer in inst_layers
                if layer["layer_id"] in extraction_data_by_layer_id
            ],
            "extraction_data_by_layer_id": extraction_data_by_layer_id,
            "ignore_layers_transparency": instance.data.get(
                "ignoreLayersTransparency", False
            ),
        }

        composite_context_path = self._write_render_context(
            composite_context_data, output_dir, filename="composite_context.json"
        )

        # Get base job info
        base_job_info = self.get_job_info()
        batch_name = self._get_batch_name()

        # Submit composite job
        composite_job_info = copy.deepcopy(base_job_info)
        composite_job_info.Name = f"Composite - {inst_subset}"
        composite_job_info.BatchName = batch_name
        composite_job_info.Frames = "0"  # Single task
        composite_job_info.ChunkSize = 1
        composite_job_info.JobDependencies = last_job_id
        composite_job_info.IsFrameDependent = False

        # Plugin info with composite arguments
        plugin_info = TVPaintPluginInfo(
            Arguments=(
                f"run_module {self.farm_render_module}"
                f" --composite-context \"{composite_context_path}\""
            ),
            SingleFramesOnly="True"  # Single task
        )

        # Add asset dependency for composite context
        composite_job_info.AssetDependency += composite_context_path

        # Build and submit payload
        payload = self.assemble_payload(
            job_info=composite_job_info,
            plugin_info=attr.asdict(plugin_info),
            aux_files=self.get_aux_files()
        )

        composite_job_id = self.submit(payload)
        self.log.info(f"Submitted composite job {composite_job_id} for {inst_subset}")

        # Update instance data
        output_template = get_frame_filename_template(mark_out)
        instance.data["expectedFiles"] = [
            os.path.join(output_dir, output_template.format(frame=frame_idx))
            for frame_idx in range(mark_in, mark_out + 1)
        ]
        instance.data["outputDir"] = output_dir
        instance.data["toBeRenderedOn"] = "deadline"

        # Check if EXR conversion should be applied
        last_job_id = composite_job_id
        exr_settings = self._get_exr_conversion_settings(instance)
        if exr_settings and exr_settings.get("enabled"):
            self.log.info(f"Submitting EXR conversion job for {inst_subset}")
            last_job_id = self._submit_exr_conversion_job(
                instance=instance,
                depends_on_job_id=composite_job_id,
                output_dir=output_dir,
                mark_in=mark_in,
                mark_out=mark_out,
                exr_settings=exr_settings
            )

        # The last submit() call sets instance.data["deadlineSubmissionJob"]
        return last_job_id
