"""Farm render script for TVPaint.

This script is run by Deadline workers to render and composite TVPaint layers.
It's invoked in three modes:
  - Render mode: render all exposure frames for all layers in a single TVPaint session
  - Fill mode: fill reference frames for all layers
  - Composite mode: composite instance-specific layers

Usage:
  render mode: openpype_console run farm_render.py --render-context <path>
  fill mode: openpype_console run farm_render.py --render-context <path> --fill
  composite mode: openpype_console run farm_render.py --composite-context <path>

Render context (used by render and fill modes):
  Contains all layers for this render instance and output dir.

Composite context (used by composite mode):
  Contains instance-specific layers, raw render input dir, and instance output dir.
"""

import os
import shutil
import sys
import json
import subprocess
import argparse
import tempfile
import time


def load_render_context(context_path):
    """Load render context JSON from file."""
    if not os.path.exists(context_path):
        raise FileNotFoundError(f"Render context file not found: {context_path}")

    with open(context_path, "r") as f:
        return json.load(f)


def get_tvpaint_executable(tvpaint_app_name):
    """Get TVPaint executable path.

    Tries to use ApplicationManager first, then falls back to environment variable.
    """
    try:
        from openpype.lib.applications import ApplicationManager
        app_manager = ApplicationManager()
        app = app_manager.applications.get(tvpaint_app_name)
        if app:
            exe_path = app.find_executable()
            if exe_path:
                return str(exe_path)
    except Exception as e:
        print(f"ApplicationManager lookup failed: {e}")

    # Fall back to environment variable
    exe_path = os.environ.get("TVPAINT_EXECUTABLE")
    if exe_path:
        return exe_path

    raise RuntimeError(
        f"Could not find TVPaint executable for {tvpaint_app_name}. "
        "Set TVPAINT_EXECUTABLE environment variable or install via ApplicationManager."
    )


def _get_tvpaint_environment():
    """Environment for headless TVPaint launches.

    OpenPypePlugin.dll connects when WEBSOCKET_URL is set, and the server then
    triggers a blocking "Write to file" dialog.
    """
    env = os.environ.copy()
    env.pop("WEBSOCKET_URL", None)
    return env


def _copy_to_output_dirs(copy_targets, src_dir, filenames_by_frame_index):
    """Copy rendered frames from src_dir to per-instance output directories.

    Used to populate single-layer instance output dirs without a composite job.

    Args:
        copy_targets (list): List of dicts, each with keys:
            - output_dir: destination directory
            - output_template: frame filename template (e.g. "{frame:0>4d}.png")
            - mark_in: first frame index to copy (inclusive)
            - mark_out: last frame index to copy (inclusive)
        src_dir (str): Source directory containing the rendered frame files.
        filenames_by_frame_index (dict): Maps frame index (str) -> source filename.
    """
    for target in copy_targets:
        target_dir = target["output_dir"]
        output_template = target["output_template"]
        target_mark_in = target.get("mark_in")
        target_mark_out = target.get("mark_out")
        os.makedirs(target_dir, exist_ok=True)
        print(f"Copying frames to {target_dir}")
        for frame_idx_str, src_filename in filenames_by_frame_index.items():
            frame_idx = int(frame_idx_str)
            # Skip frames outside this instance's range
            if target_mark_in is not None and frame_idx < target_mark_in:
                continue
            if target_mark_out is not None and frame_idx > target_mark_out:
                continue
            src_path = os.path.join(src_dir, src_filename)
            dst_filename = output_template.format(frame=frame_idx)
            dst_path = os.path.join(target_dir, dst_filename)
            if os.path.exists(dst_path):
                print(f"Skipping {dst_path} (already exists)")
                continue
            if not os.path.exists(src_path):
                print(f"WARNING: Source file not found: {src_path}")
                continue
            try:
                os.link(src_path, dst_path)
            except OSError:
                shutil.copy2(src_path, dst_path)


def render_all_layers(render_context):
    """Render all exposure frames for all layers in a single TVPaint session.

    Builds one George script that cycles through all layers and their exposure frames,
    then exits TVPaint once.

    Args:
        render_context (dict): Render context data with keys:
            - extraction_data_by_layer_id: {layer_id_str: extraction_data}
            - output_dir: output directory for rendered frames
            - scene_file: path to TVPaint scene file
            - copy_to_output_by_layer_id: per-instance copy targets (optional)
            - layers: list of layer metadata dicts with layer_id, position, name
    """
    print("Render mode: rendering all exposure frames for all layers in single TVPaint session")

    # Get TVPaint executable early - fail fast if not available
    tvpaint_exe = get_tvpaint_executable(os.environ["AVALON_APP_NAME"])
    print(f"TVPaint executable: {tvpaint_exe}")

    # Get extraction data for all layers
    extraction_data_by_layer_id = render_context["extraction_data_by_layer_id"]
    if not extraction_data_by_layer_id:
        print("ERROR: No layers in extraction data")
        sys.exit(1)

    # Build lookup from layer_id -> (position, name) for stable layer resolution
    layer_metadata = {}
    for layer_info in render_context.get("layers", []):
        lid = layer_info["layer_id"]
        layer_metadata[lid] = (layer_info["position"], layer_info["name"])
        layer_metadata[str(lid)] = (layer_info["position"], layer_info["name"])

    # Build list of all (layer_id, exposure_frames) to render
    all_layers_with_exposures = []
    total_exposure_frames = 0

    for layer_id_str, extr_data in extraction_data_by_layer_id.items():
        layer_id = int(layer_id_str)
        frame_references = extr_data.get("frame_references", {})
        filenames_by_frame_index = extr_data.get("filenames_by_frame_index", {})

        # Find exposure frames (frame_idx == ref_idx)
        exposure_frames = sorted([
            int(frame_idx) for frame_idx, ref_idx in frame_references.items()
            if int(frame_idx) == ref_idx
        ])

        if exposure_frames:
            # Validate layer has metadata
            if layer_id_str not in layer_metadata:
                raise RuntimeError(
                    f"Layer {layer_id} is in extraction_data_by_layer_id but missing from "
                    f"render_context['layers']. Cannot resolve stable layer position."
                )
            all_layers_with_exposures.append((layer_id, exposure_frames, extr_data))
            total_exposure_frames += len(exposure_frames)
            position, name = layer_metadata[layer_id_str]
            print(f"Layer {layer_id} (position {position}, name '{name}'): {len(exposure_frames)} exposure frames")

    if total_exposure_frames == 0:
        print("No exposure frames to render")
        print("Progress: 100%")
        return

    print(f"Total exposure frames to render: {total_exposure_frames}")

    # Create verification file to track actual layer selections
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        verify_path = f.name
    verify_path_george = verify_path.replace("\\", "/")
    expected_verifications = []

    # Build George script
    george_lines = []
    output_dir = render_context["output_dir"]
    expected_output_paths = []

    # Load project file once
    scene_file = render_context.get("scene_file")
    if not scene_file:
        raise RuntimeError(
            "Render context has no 'scene_file'. TVPaint would hang on startup "
            "screen with no project loaded, preventing tv_quit from being reached."
        )
    scene_file_escaped = scene_file.replace("\\", "/")
    george_lines.append(
        "tv_LoadProject '\"'\"{}\"'\"'".format(scene_file_escaped)
    )

    # Normalize to 0-based frame indexing (render context assumes tv_startframe 0)
    george_lines.append("tv_startframe 0")

    # Declare verification file path as George variable
    george_lines.append(f'verify_path = "{verify_path_george}"')

    # Render each layer's exposure frames
    for layer_id, exposure_frames, extr_data in all_layers_with_exposures:
        filenames_by_frame_index = extr_data.get("filenames_by_frame_index", {})
        position, name = layer_metadata[str(layer_id)]

        # Resolve layer by position (stable across sessions) instead of session-scoped layer_id
        george_lines.append(f'tv_LayerGetID {position}')
        george_lines.append('lid = result')
        george_lines.append('tv_layerset lid')
        george_lines.append('tv_LayerInfo lid')
        george_lines.append('PARSE result visible position opacity name type startFrame endFrame prelighttable postlighttable selected editable sencilState')
        george_lines.append("line = position'|'name")
        george_lines.append('tv_writetextfile "strict" "append" \'"\'verify_path\'"\' line')
        expected_verifications.append(f"{position}|{name}")

        george_lines.append('tv_SaveMode "PNG"')

        # Render each exposure frame
        for frame_idx in exposure_frames:
            filename = filenames_by_frame_index.get(str(frame_idx))
            if not filename:
                print(f"WARNING: No filename for layer {layer_id} frame {frame_idx}")
                continue

            output_path = os.path.normpath(
                os.path.join(output_dir, filename)
            ).replace("\\", "/")
            expected_output_paths.append(output_path)
            george_lines.append(f'tv_layerimage {frame_idx}')
            george_lines.append('tv_saveimage "{}"'.format(output_path))

    # Exit TVPaint when rendering is complete
    george_lines.append('tv_quit')

    # Write George script to temp file
    print("Writing George script with all layers...")
    with tempfile.NamedTemporaryFile(mode='w', suffix='.grg', delete=False) as f:
        f.write("\n".join(george_lines))
        george_script_path = f.name

    total_frames = len(expected_output_paths)

    try:
        print(f"Running TVPaint: {tvpaint_exe}")
        print(f"George script: {george_script_path}")
        print("Progress: 0%")

        # Run TVPaint with George script
        process = subprocess.Popen(
            [tvpaint_exe, f"script={george_script_path}"],
            env=_get_tvpaint_environment()
        )

        last_progress = 0
        while True:
            # Check if process has finished
            returncode = process.poll()
            if returncode is not None:
                if returncode != 0:
                    raise RuntimeError(
                        f"TVPaint render failed with return code {returncode}"
                    )
                break

            # Count how many expected output files exist
            if total_frames > 0:
                done = sum(
                    1 for p in expected_output_paths if os.path.exists(p)
                )
                current_progress = int(done / total_frames * 100)
                if current_progress != last_progress:
                    print(f"Progress: {current_progress}%")
                    last_progress = current_progress

            time.sleep(0.5)

        print("TVPaint render completed successfully")

        # Validate layer selections were correct
        if not os.path.exists(verify_path):
            raise RuntimeError(
                f"Layer verification file not found: {verify_path}. "
                "TVPaint may have failed to write layer selection data."
            )

        with open(verify_path, "r") as f:
            actual_verifications = [line.strip() for line in f if line.strip()]

        if len(actual_verifications) != len(expected_verifications):
            raise RuntimeError(
                f"Layer verification mismatch: expected {len(expected_verifications)} layers, "
                f"got {len(actual_verifications)}.\n"
                f"Expected: {expected_verifications}\n"
                f"Actual: {actual_verifications}"
            )

        for i, (expected, actual) in enumerate(zip(expected_verifications, actual_verifications)):
            if expected != actual:
                raise RuntimeError(
                    f"Layer verification failed at index {i}:\n"
                    f"Expected: {expected}\n"
                    f"Actual: {actual}\n"
                    f"Full expected: {expected_verifications}\n"
                    f"Full actual: {actual_verifications}"
                )

        print(f"Layer verification passed: all {len(expected_verifications)} layers matched")

        # Validate output files exist
        missing_files = []
        for output_path in expected_output_paths:
            if not os.path.exists(output_path):
                missing_files.append(os.path.basename(output_path))

        assert not missing_files, f"Missing output files: {missing_files}"

        # After successful render, copy frames to any per-instance output dirs
        # (only for layers with no reference frames to fill; if references exist,
        # fill_all_references will do the copy after filling is complete)
        copy_to_output_by_layer_id = render_context.get("copy_to_output_by_layer_id", {})

        for layer_id, _, extr_data in all_layers_with_exposures:
            frame_references = extr_data.get("frame_references", {})
            filenames_by_frame_index = extr_data.get("filenames_by_frame_index", {})

            # Check if this layer has reference frames to fill
            has_references_to_fill = any(
                int(k) != v for k, v in frame_references.items() if v is not None
            )

            if not has_references_to_fill:
                copy_targets = (
                    copy_to_output_by_layer_id.get(layer_id)
                    or copy_to_output_by_layer_id.get(str(layer_id))
                    or []
                )
                if copy_targets:
                    print(f"Copying {len(filenames_by_frame_index)} frames for layer {layer_id} "
                          f"to {len(copy_targets)} instance output dir(s)")
                    _copy_to_output_dirs(copy_targets, output_dir, filenames_by_frame_index)

    finally:
        # Clean up George script
        if os.path.exists(george_script_path):
            os.remove(george_script_path)
        # Clean up verification file
        if os.path.exists(verify_path):
            os.remove(verify_path)


def fill_all_references(render_context):
    """Fill reference frames for all layers using os.link or shutil.copy.

    Reads extraction data and filenames from render_context, and fills all
    non-exposure frames by copying from exposure frames.
    After filling, copies all frames to any per-instance output dirs.

    Args:
        render_context (dict): Render context data with keys:
            - extraction_data_by_layer_id: extraction data for all layers
            - output_dir: shared raw render directory
            - copy_to_output_by_layer_id: per-instance copy targets (optional)
    """
    print("Fill mode: filling reference frames for all layers")

    extraction_data_by_layer_id = render_context["extraction_data_by_layer_id"]
    output_dir = render_context["output_dir"]

    if not extraction_data_by_layer_id:
        print("ERROR: No layers in extraction data")
        sys.exit(1)

    # Fill references for each layer
    for layer_id_str, extr_data in extraction_data_by_layer_id.items():
        layer_id = int(layer_id_str)
        filenames_by_frame_index = extr_data.get("filenames_by_frame_index", {})

        # JSON deserializes all keys as strings; convert back to int
        frame_references = {
            int(k): (int(v) if v is not None else None)
            for k, v in extr_data.get("frame_references", {}).items()
        }

        # Build filepaths from filenames in output_dir
        filepaths_by_frame = {}
        for frame_idx, filename in filenames_by_frame_index.items():
            frame_idx_int = int(frame_idx)
            source_path = os.path.join(output_dir, filename)
            filepaths_by_frame[frame_idx_int] = source_path

        # Fill reference frames (copy exposure frames to fill non-exposure frames)
        print(f"Filling reference frames for layer {layer_id}")
        for frame_idx, ref_idx in frame_references.items():
            if ref_idx is None or frame_idx == ref_idx:
                continue
            src_filepath = filepaths_by_frame[ref_idx]
            dst_filepath = filepaths_by_frame[frame_idx]

            # Skip if destination already exists
            if os.path.exists(dst_filepath):
                continue

            try:
                os.link(src_filepath, dst_filepath)
            except OSError:
                shutil.copy(src_filepath, dst_filepath)

    print("Fill completed for all layers")

    # After filling, copy all frames to any per-instance output dirs
    copy_to_output_by_layer_id = render_context.get("copy_to_output_by_layer_id", {})

    for layer_id_str, extr_data in extraction_data_by_layer_id.items():
        layer_id = int(layer_id_str)
        filenames_by_frame_index = extr_data.get("filenames_by_frame_index", {})

        copy_targets = (
            copy_to_output_by_layer_id.get(layer_id)
            or copy_to_output_by_layer_id.get(str(layer_id))
            or []
        )
        if copy_targets:
            print(f"Copying {len(filenames_by_frame_index)} frames for layer {layer_id} "
                  f"to {len(copy_targets)} instance output dir(s)")
            _copy_to_output_dirs(copy_targets, output_dir, filenames_by_frame_index)

    print("Progress: 100%")


def composite_layers(composite_context):
    """Composite instance-specific rendered layers.

    Reads rendered layer files from raw_render_dir and writes composited output
    to output_dir. Assumes all reference frames have already been filled by
    prior fill_references jobs.

    Args:
        composite_context (dict): Composite context data with keys:
            - raw_render_dir: directory containing rendered layer frames
            - output_dir: directory for final composited output
            - layers: list of layers to composite
            - extraction_data_by_layer_id: extraction data for this instance's layers
            - mark_in, mark_out: frame range
            - ignore_layers_transparency: boolean flag
    """
    print("Composite mode: compositing layers")

    from openpype.hosts.tvpaint.lib import composite_rendered_layers

    raw_render_dir = composite_context["raw_render_dir"]
    output_dir = composite_context["output_dir"]
    layers = composite_context["layers"]
    extraction_data_by_layer_id = composite_context["extraction_data_by_layer_id"]
    mark_in = composite_context["mark_in"]
    mark_out = composite_context["mark_out"]
    ignore_transparency = composite_context.get("ignore_layers_transparency", False)

    # Reconstruct filepaths for each layer (from raw_render_dir)
    # Reference frames have already been filled by prior fill_references jobs
    filepaths_by_layer_id = {}

    for layer_id_str, extr_data in extraction_data_by_layer_id.items():
        filenames_by_frame_index = extr_data.get("filenames_by_frame_index", {})
        frame_references = extr_data.get("frame_references", {})

        # Build filepaths from filenames in raw_render_dir
        # Only include frames where frame_references is non-null (layer exists at that frame)
        filepaths_by_frame = {}
        for frame_idx, filename in filenames_by_frame_index.items():
            # Skip frames where layer is absent (frame_references is None)
            if frame_references.get(frame_idx) is None:
                continue
            frame_idx_int = int(frame_idx)
            # Read from raw_render_dir, where render jobs wrote the files
            source_path = os.path.join(raw_render_dir, filename)
            filepaths_by_frame[frame_idx_int] = source_path

        filepaths_by_layer_id[int(layer_id_str)] = filepaths_by_frame

    # Build output filepaths for final composited frames (write to output_dir)
    from openpype.hosts.tvpaint.lib import get_frame_filename_template
    output_template = get_frame_filename_template(mark_out)
    output_filepaths_by_frame = {}
    for frame_idx in range(mark_in, mark_out + 1):
        filename = output_template.format(frame=frame_idx)
        output_path = os.path.join(output_dir, filename)
        output_filepaths_by_frame[frame_idx] = output_path

    # Perform compositing
    composite_rendered_layers(
        layers,
        filepaths_by_layer_id,
        mark_in,
        mark_out,
        output_filepaths_by_frame,
        ignore_transparency
    )

    print("Compositing completed")
    print("Progress: 100%")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="TVPaint farm render script"
    )

    # Mutually exclusive: render-context (for render/fill) OR composite-context (for composite)
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--render-context",
        help="Path to render_context.json (for render or fill mode)"
    )
    mode_group.add_argument(
        "--composite-context",
        help="Path to composite_context.json for composite mode"
    )

    # Fill flag: only valid with --render-context
    parser.add_argument(
        "--fill",
        action="store_true",
        help="Fill reference frames mode (used with --render-context)"
    )

    args = parser.parse_args()

    try:
        if args.composite_context:
            # Composite mode
            composite_context = load_render_context(args.composite_context)
            composite_layers(composite_context)
        elif args.fill:
            # Fill mode: --render-context --fill
            render_context = load_render_context(args.render_context)
            fill_all_references(render_context)
        else:
            # Render mode: --render-context
            render_context = load_render_context(args.render_context)
            render_all_layers(render_context)

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
