"""Convert PNG frames to EXR on the farm.

This script is run by Deadline workers to convert TVPaint rendered PNG frames
to EXR format. It mirrors the functionality of ExtractConvertToEXR plugin
but runs as a standalone job between fill and composite jobs.

Usage:
  openpype_console run farm_convert_to_exr.py --convert-context <path>

Convert context (convert_context.json):
  Contains output directory, list of PNG filenames to convert, and EXR settings
  (compression, replace_pngs flag).
"""

import os
import sys
import json
import argparse


def load_convert_context(context_path):
    """Load convert context JSON from file."""
    if not os.path.exists(context_path):
        raise FileNotFoundError(f"Convert context file not found: {context_path}")

    with open(context_path, "r") as f:
        return json.load(f)


def convert_pngs_to_exr(output_dir, filenames, exr_compression, replace_pngs):
    """Convert PNG files to EXR format using oiiotool.

    Args:
        output_dir (str): Directory containing the PNG files.
        filenames (list): List of PNG filenames to convert.
        exr_compression (str): EXR compression type (e.g., "ZIP").
        replace_pngs (bool): Whether to delete PNG files after conversion.

    Raises:
        RuntimeError: If oiiotool is not available or conversion fails.
    """
    from openpype.lib import (
        get_oiio_tool_args,
        ToolNotFoundError,
        run_subprocess,
    )

    try:
        oiio_args = get_oiio_tool_args("oiiotool")
    except ToolNotFoundError:
        raise RuntimeError(
            "OpenImageIO tool is not available on this machine."
        )

    print(f"Converting {len(filenames)} PNG files to EXR")
    print(f"Output directory: {output_dir}")
    print(f"EXR compression: {exr_compression}")
    print(f"Replace PNGs: {replace_pngs}")

    converted_count = 0
    for i, png_filename in enumerate(filenames, 1):
        # Derive EXR filename from PNG filename
        exr_filename = os.path.splitext(png_filename)[0] + ".exr"

        src_filepath = os.path.join(output_dir, png_filename)
        dst_filepath = os.path.join(output_dir, exr_filename)

        # Check source exists
        if not os.path.exists(src_filepath):
            print(f"WARNING: Source PNG not found: {src_filepath}")
            continue

        # Skip if destination already exists
        if os.path.exists(dst_filepath):
            print(f"Skipping {exr_filename} (already exists)")
            if replace_pngs and os.path.exists(src_filepath):
                try:
                    os.remove(src_filepath)
                    print(f"Deleted PNG: {png_filename}")
                except OSError as e:
                    print(f"WARNING: Could not delete {png_filename}: {e}")
            continue

        try:
            # Build oiiotool command
            args = oiio_args + [
                src_filepath,
                "--unpremult",
                "--compression", exr_compression,
                "--colorconvert", "sRGB", "linear",
                "-o", dst_filepath
            ]

            print(f"Converting ({i}/{len(filenames)}): {png_filename} -> {exr_filename}")
            print(f"Running command: {' '.join(args)}")
            run_subprocess(args)

            # Delete source PNG if requested
            if replace_pngs:
                try:
                    os.remove(src_filepath)
                    print(f"  Deleted PNG: {png_filename}")
                except OSError as e:
                    print(f"  WARNING: Could not delete {png_filename}: {e}")

            converted_count += 1

        except RuntimeError as e:
            print(f"ERROR: Failed to convert {png_filename}: {e}")
            raise

    print(f"Conversion complete: {converted_count}/{len(filenames)} files converted")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Convert PNG frames to EXR on the farm"
    )
    parser.add_argument(
        "--convert-context",
        required=True,
        help="Path to convert_context.json"
    )

    args = parser.parse_args()

    try:
        convert_context = load_convert_context(args.convert_context)

        output_dir = convert_context.get("output_dir")
        filenames = convert_context.get("filenames", [])
        exr_compression = convert_context.get("exr_compression", "ZIP")
        replace_pngs = convert_context.get("replace_pngs", True)

        if not output_dir:
            raise ValueError("output_dir not found in convert context")
        if not filenames:
            print("No filenames to convert")
            print("Progress: 100%")
            return

        convert_pngs_to_exr(output_dir, filenames, exr_compression, replace_pngs)
        print("Progress: 100%")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
