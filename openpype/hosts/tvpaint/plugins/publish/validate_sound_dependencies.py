import os
import tempfile

import pyblish.api

from openpype.pipeline import PublishXmlValidationError
from openpype.hosts.tvpaint.api.lib import (
    execute_george,
    execute_george_through_file,
)


def get_sound_clips_george_script(output_filepath):
    """Generate George script to enumerate all sound clips and their file paths.

    Args:
        output_filepath (str): Path where the script will write the results

    Returns:
        str: George script that loops through sound clips and writes their info
    """
    output_filepath = output_filepath.replace("\\", "/")

    script_lines = [
        # Variable containing full path to output file
        "output_path = \"{}\"".format(output_filepath),
        # Get the current clip ID
        "tv_clipcurrentid",
        "current_clip_id = result",
        # Initialize loop. Use do_loop (not 'loop') to avoid any keyword clash.
        # max_clips is a hard ceiling to prevent infinite loops when the
        # out-of-bounds sentinel value of tv_soundclipinfo is unknown.
        "idx = 0",
        "max_clips = 100",
        "do_loop = 1",
        # Sound clips loop
        "WHILE do_loop",
        "tv_soundclipinfo current_clip_id idx",
        "clip_info = result",
        # -2 means "no current clip without mixer" - the standard sentinel
        # returned by tv_soundclipinfo when the index is out of range.
        # Also guard against "" and "NONE" for robustness across TVPaint versions.
        "IF CMP(clip_info, \"-2\")==1",
        "do_loop = 0",
        "ELSE",
        "IF CMP(clip_info, \"\")==1",
        "do_loop = 0",
        "ELSE",
        "IF CMP(clip_info, \"NONE\")==1",
        "do_loop = 0",
        "ELSE",
        # Write idx and the full result to the output file
        "line = idx'|'clip_info",
        "tv_writetextfile \"strict\" \"append\" '\"'output_path'\"' line",
        "idx = idx + 1",
        # Hard ceiling guard
        "IF CMP(idx, max_clips)==1",
        "do_loop = 0",
        "END",
        "END",
        "END",
        "END",
        "END",
    ]

    return "\n".join(script_lines)


def parse_sound_clips_data(data):
    """Parse sound clips data from George script output.

    Args:
        data (str): Raw output from George script (pipe-delimited lines)

    Returns:
        list: List of dicts with keys 'idx' and 'path'
    """
    clips = []
    lines = data.split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        parts = line.split("|", 1)
        if len(parts) < 2:
            continue

        try:
            idx = int(parts[0])
            path = parts[1].strip()
            clips.append({
                "idx": idx,
                "path": path
            })
        except (ValueError, IndexError):
            # Skip malformed lines
            continue

    return clips


def get_sound_clips(log):
    """Collect all sound clips of the current clip from TVPaint.

    Args:
        log (logging.Logger): Logger used for debug output.

    Returns:
        list: List of dicts with keys 'idx' and 'path'.
    """
    # Create temp file for George script output
    with tempfile.NamedTemporaryFile(
        mode="w", prefix="tvp_sound_", suffix=".txt", delete=False
    ) as tmp_file:
        output_filepath = tmp_file.name

    try:
        george_script = get_sound_clips_george_script(output_filepath)
        log.debug("Executing George script to collect sound clips")
        execute_george_through_file(george_script)

        if not os.path.exists(output_filepath):
            log.debug("No sound clip output file generated")
            return []

        with open(output_filepath, "r") as f:
            data = f.read()

        sound_clips = parse_sound_clips_data(data)
        log.debug(f"Found {len(sound_clips)} sound clips")
        return sound_clips

    finally:
        # Clean up temp file
        if os.path.exists(output_filepath):
            try:
                os.remove(output_filepath)
            except OSError:
                log.warning(f"Failed to clean up temp file: {output_filepath}")


def get_missing_sound_clips(log):
    """Collect sound clips whose linked audio file no longer exists on disk.

    Args:
        log (logging.Logger): Logger used for debug output.

    Returns:
        list: List of dicts with keys 'idx' and 'path' for missing clips.
    """
    missing_files = []
    for clip in get_sound_clips(log):
        clip_path = clip["path"]
        if not os.path.isfile(clip_path):
            missing_files.append({
                "idx": clip["idx"],
                "path": clip_path
            })
            log.warning(
                f"Missing sound clip file: [{clip['idx']}] {clip_path}"
            )
    return missing_files


class DeleteMissingSoundDependencies(pyblish.api.Action):
    """Delete all sound clips whose linked audio file is missing on disk."""

    label = "Delete Missing Sound Clips"
    icon = "trash"
    on = "failed"

    def process(self, context, plugin):
        missing_files = get_missing_sound_clips(self.log)

        if not missing_files:
            self.log.info("No missing sound clips found to delete.")
            return

        # Delete in descending index order so removing one clip does not
        # shift the indices of the clips we still need to remove.
        for entry in sorted(
            missing_files, key=lambda clip: clip["idx"], reverse=True
        ):
            self.log.info(
                "Removing sound clip [{}]: {}".format(
                    entry["idx"], entry["path"]
                )
            )
            execute_george("tv_soundclipremove {}".format(entry["idx"]))

        self.log.info(
            "Removed {} missing sound clip(s).".format(len(missing_files))
        )


class ValidateSoundDependencies(pyblish.api.ContextPlugin):
    """Validate that all sound clips referenced by the scene have existing files.

    This validator prevents farm renders from hanging on TVPaint's native
    "Missing sound dependencies: Alternative Paths" dialog which appears when
    a sound clip's linked audio file no longer exists on disk.

    The dialog only appears once when TVPaint loads a scene with a broken sound
    reference in a headless process, causing Deadline workers to hang with no
    operator to dismiss it. This validator detects such issues before submission.
    """

    label = "Validate Sound Dependencies"
    order = pyblish.api.ValidatorOrder
    hosts = ["tvpaint"]
    optional = False
    actions = [DeleteMissingSoundDependencies]

    def process(self, context):
        """Validate sound clip file dependencies.

        Only runs when the context includes at least one render.farm instance,
        since local (non-farm) renders never reload the scene headlessly.
        """
        # Only validate when submitting to farm
        has_farm_instance = any(
            "render.farm" in instance.data.get("families", [])
            for instance in context
        )

        if not has_farm_instance:
            self.log.debug("No render.farm instance found, skipping sound validation")
            return

        # Collect sound clips whose linked audio file is missing on disk
        missing_files = get_missing_sound_clips(self.log)

        # Raise error if any files are missing
        if missing_files:
            # Format the missing files list for the error message
            missing_list = "\n".join([
                f"  Clip {entry['idx']}: {entry['path']}"
                for entry in missing_files
            ])

            msg = f"Found {len(missing_files)} missing sound clip file(s):\n{missing_list}"

            formatting_data = {
                "missing_files_list": missing_list,
                "missing_count": len(missing_files)
            }

            raise PublishXmlValidationError(
                self, msg, formatting_data=formatting_data
            )
