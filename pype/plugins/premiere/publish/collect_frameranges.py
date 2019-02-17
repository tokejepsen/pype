import pyblish.api


class CollectFrameranges(pyblish.api.InstancePlugin):
    """
    Collecting frameranges needed for ftrack integration

    Args:
        context (obj): pyblish context session

    """

    label = "Collect Clip Frameranges"
    order = pyblish.api.CollectorOrder
    families = ['clip']

    def process(self, instance):
        # getting metadata from jsonData key
        metadata = instance.data.get('jsonData').get('metadata')

        # getting important metadata time calculation
        fps = metadata['ppro.timeline.fps']
        sec_start = metadata['ppro.clip.start']
        sec_end = metadata['ppro.clip.end']
        fstart = instance.data.get('fstart')
        fend = fstart + int((sec_end - sec_start) * fps)

        self.log.debug("fps: {}\nsec_start: {}\nsec_end: {}\nfstart: {}\nfend: {}\n".format(
            fps, sec_start, sec_end, fstart, fend))

        instance.data['startFrame'] = fstart
        instance.data['endFrame'] = fend
        instance.data['fps'] = metadata['ppro.timeline.fps']
