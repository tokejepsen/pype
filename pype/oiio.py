import os
import OpenImageIO as oiio
from pypeapp import Logger
import pype.api as pyapi

log = Logger().get_logger(__name__, "nukestudio")

# SOURCE
src_dir = "C:/Users/jezsc/_PYPE_testing/projects/J01_jakub_test/shots/105/105_0021/work/Compositing/renders/nuke/renderCompositingMain"

# DESTINATION
dst_dir = r"C:/Users/jezsc/Downloads/TEMP_TEST"

colorspace = {
    "colorScience": "aces_1.0.3",
    "colorSpaceViewer": "ACES",
    "colorLutViewer": "sRGB",
    "colorSpaceScene": "acescg",
    "colorSpaceLutInput": "ACES - ACES2065-1",
    "colorSpaceLutOutput": "Utility - Curve - sRGB"
    }


class Image_Convertor:
    ocio_confs_dir = "C:/Program Files/Nuke11.2v2/plugins/OCIOConfigs/configs"
    output_ext = ".jpg"

    def __init__(self, src, dst_dir, **kwarg):
        print(kwarg)
        assert all([src, dst_dir]), "Missing values in compulsory arguments!"
        self.src = src
        self.dst_dir = dst_dir

        # get optionals
        self.colorscience = kwarg.get("colorScience", "aces_1.0.3")
        self.colorspace_viewer = kwarg.get("colorSpaceViewer", "ACES")
        self.color_lut_viewer = kwarg.get("colorLutViewer", "sRGB")
        self.colorspace_scene = kwarg.get("colorSpaceScene", "acescg")
        self.colorspace_lut_input = kwarg.get(
            "colorSpaceLutInput", None)
        self.colorspace_lut_output = kwarg.get(
            "colorSpaceLutOutput", None)

        self.process()

    def process(self):
        log.debug("_ color settings: {}".format(
            (self.colorscience,
             self.colorspace_viewer,
             self.color_lut_viewer,
             self.colorspace_scene,
             self.colorspace_lut_input,
             self.colorspace_lut_output
             )
        ))
        # secure the dest dir exists
        if not os.path.isdir(dst_dir):
            os.mkdir(dst_dir, mode=777)

        if os.path.isdir(self.src):
            self.process_sequence()
        elif os.path.isfile(self.src):
            self.process_image()
        else:
            log.warning("Not correct input data to `src`. "
                        "Path to dir or file is allowed only, "
                        "got: `{}`".format(self.src))

    def process_sequence(self):
        for collection in pyapi.find_collections(self.src):
            for c in collection:
                src_path = os.path.join(self.src, c).replace("\\", "/")
                src = oiio.ImageBuf(src_path)
                spec = src.spec()
                print_imagespec(spec)
                if self.colorspace_lut_input and self.colorspace_lut_output:
                    dst = oiio.ImageBufAlgo.colorconvert(
                        src,
                        self.colorspace_lut_input,
                        self.colorspace_lut_output,
                        roi=src.roi_full,  # crop area
                        colorconfig=self.get_ocio_conf()
                        )
                else:
                    dst = oiio.ImageBufAlgo.ociodisplay(
                        src,
                        self.colorspace_viewer,
                        self.color_lut_viewer,
                        self.colorspace_scene,
                        roi=src.roi_full,  # crop area
                        colorconfig=self.get_ocio_conf()
                        )

                src.clear()

                print("DST Resolution: {0}x{1}".format(
                    dst.spec().width, dst.spec().height))

                ext = os.path.splitext(c)[-1]
                dst_path = os.path.normpath(
                    os.path.join(self.dst_dir, c).replace(ext, self.output_ext))

                dst.write(dst_path)
                print(dst_path)

    def process_image(self):
        src = oiio.ImageBuf(self.src)
        print_imagespec(src.spec())
        dst = oiio.ImageBufAlgo.ociodisplay(
            src,
            self.colorspace_viewer,
            self.color_lut_viewer,
            self.colorspace_scene,
            roi=src.roi_full,  # crop area
            colorconfig=self.get_ocio_conf()
            )

        src.clear()

        print("DST Resolution: {0}x{1}".format(
            dst.spec().width, dst.spec().height))

        ext = os.path.splitext(self.src)[-1]
        dst_path = self.src.replace(ext, self.output_ext)

        dst.write(dst_path)
        print(dst_path)

    def get_ocio_conf(self):
        return os.path.normpath(
            os.path.join(
                self.ocio_confs_dir,
                self.colorscience,
                "config.ocio"
                )
            ).replace("\\", "/")

# # GET RESOLUTION
# print("buf.roi, buf.roi_full: `{}`, `{}`".format(buf.roi, buf.roi_full))
# print("Cropped Resolution: {0}x{1}".format(buf.spec().width, buf.spec().height))
#
#
# buf = oiio.ImageBufAlgo.fit(buf, roi=oiio.ROI(0, 1280, 0, 720))
# buf.write(dst_path.replace(".jpg", "_resized.exr"))
# print("buf.roi, buf.roi_full: `{}`, `{}`".format(buf.roi, buf.roi_full))
# print("Cropped Resolution: {0}x{1}".format(buf.spec().width, buf.spec().height))
#
# # buf = oiio.ImageBufAlgo.fit(buf, roi=oiio.ROI(0, 1920, 0, 1080))


# Print the contents of an ImageSpec
def print_imagespec(spec, subimage=0, mip=0):
    import inspect
    print(inspect.getmembers(spec, lambda a: not(inspect.isroutine(a))))
    if spec.depth <= 1:
        print("resolution {}x{} x:{} y:{}".format(spec.width,
              spec.height, spec.x, spec.y))
        print("resolution {}x{}".format(spec,
              spec.get_float_attribute("YResolution")))
    else:
        print("resolution %dx%d%x%d+d%+d%+d" % (spec.width,
              spec.height, spec.depth, spec.x, spec.y, spec.z))
    if (spec.width != spec.full_width or spec.height != spec.full_height
            or spec.depth != spec.full_depth):
        if spec.full_depth <= 1:
            print("full res   %dx%d%+d%+d" % (spec.full_width,
                  spec.full_height, spec.full_x, spec.full_y))
        else:
            print("full res   %dx%d%x%d+d%+d%+d" % (spec.full_width,
                  spec.full_height, spec.full_depth,
                  spec.full_x, spec.full_y, spec.full_z))
    if spec.tile_width:
        print("tile size  %dx%dx%d" % (spec.tile_width,
              spec.tile_height, spec.tile_depth))
    else:
        print("untiled")
    if mip >= 1:
        return
    print("" + str(spec.nchannels) + "channels:" + str(spec.channelnames))
    print("format = " + str(spec.format))
    if len(spec.channelformats) > 0:
        print("channelformats = " + spec.channelformats)
    print("alpha channel = " + str(spec.alpha_channel))
    print("z channel = " + str(spec.z_channel))
    print("deep = " + str(spec.deep))
    print("PixelAspectRatio: `{}`".format(next((i for i in spec.extra_attribs if "PixelAspectRatio" in i.name), None)))
    for i in spec.extra_attribs:
        if type(i.value) == str:
            print(" " + i.name + "= \"" + i.value + "\"")
        else:
            print(" " + i.name + "=" + str(i.value))


def test():
    ic = Image_Convertor(src_dir, dst_dir, **colorspace)
