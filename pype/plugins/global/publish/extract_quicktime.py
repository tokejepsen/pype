import os
import pyblish.api
import subprocess
from pype.vendor import clique


class ExtractQuicktimeEXR(pyblish.api.InstancePlugin):
    """Resolve any dependency issies

    This plug-in resolves any paths which, if not updated might break
    the published file.

    The order of families is important, when working with lookdev you want to
    first publish the texture, update the texture paths in the nodes and then
    publish the shading network. Same goes for file dependent assets.
    """

    label = "Extract Quicktime"
    order = pyblish.api.ExtractorOrder
    families = ["imagesequence", "render", "write", "source"]
    host = ["shell"]
    exclude_families = ["clip"]

    def process(self, instance):
        if [ef for ef in self.exclude_families
                for f in instance.data["families"]
                if f in ef]:
            self.log.info('ignoring: {}'.format(instance))
            return
        fps = instance.data.get("fps")
        start = instance.data.get("startFrame")
        stagingdir = os.path.normpath(instance.data.get("stagingDir"))

        collected_frames = os.listdir(stagingdir)
        collections, remainder = clique.assemble(collected_frames)

        full_input_path = os.path.join(
            stagingdir, collections[0].format('{head}{padding}{tail}')
        )
        self.log.info("input {}".format(full_input_path))

        config_data = instance.context.data['output_repre_config']

        proj_name = os.environ.get('AVALON_PROJECT', '__default__')

        for key in config_data:

            profile = config_data.get(key)

            filename = collections[0].format('{head}')
            if not filename.endswith('.'):
                filename += "."
            movFile = filename + key
            full_output_path = os.path.join(stagingdir, movFile)
            self.log.info("output {}".format(full_output_path))

            input_args = []
            # overrides output file
            input_args.append("-y")
            # preset's input data
            input_args.extend(profile.get('input', []))
            # necessary input data
            input_args.append("-i {}".format(full_input_path))
            if instance.data.get("audio"):
                input_args.append(
                    "-i {}".format(instance.data.get("audio")))
            self.log.info("USING AUDIO {}".format(instance.data.get("audio")))
            input_args.append("-framerate {}".format(fps))
            input_args.append("-start_number {}".format(start))

            output_args = []
            # preset's output data
            output_args.extend(profile.get('output', []))
            # output filename
            output_args.append(full_output_path)
            mov_args = [
                "ffmpeg",
                " ".join(input_args),
                " ".join(output_args)
            ]
            subprocess_mov = " ".join(mov_args)
            sub_proc = subprocess.Popen(subprocess_mov)
            sub_proc.wait()

            if "files" not in instance.data:
                instance.data["files"] = list()
            instance.data["files"].append(movFile)
