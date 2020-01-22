# MIT License
#
# Copyright (c) 2018 Daniel Flehner Heen (Storm Studios)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


import os
import re
import hiero.core
from hiero.core import util

import opentimelineio as otio


marker_color_map = {
    "magenta": otio.schema.MarkerColor.MAGENTA,
    "red": otio.schema.MarkerColor.RED,
    "yellow": otio.schema.MarkerColor.YELLOW,
    "green": otio.schema.MarkerColor.GREEN,
    "cyan": otio.schema.MarkerColor.CYAN,
    "blue": otio.schema.MarkerColor.BLUE,
}


class Get_OTIO:

    def __init__(self, selected_items=None):
        """
        Arguments:
            selected_items (list): list of hiero
        """
        self._sequence = hiero.ui.activeSequence()
        self._selected = selected_items or []
        for i, trackItem in enumerate(self._selected):
            print("__ trackitem: `{}`".format(trackItem))
            print("__ trackitem.index: `{}`".format(i))
        print(self._selected)
        self._processed = list()
        self.create_OTIO()

    def get_rate(self, item):
        num, den = item.framerate().toRational()
        rate = float(num) / float(den)

        if rate.is_integer():
            return rate

        return round(rate, 2)

    def get_clip_ranges(self, trackitem):
        # Is clip an audio file? Use sequence frame rate
        if not trackitem.source().mediaSource().hasVideo():
            rate_item = trackitem.sequence()

        else:
            rate_item = trackitem.source()

        source_rate = self.get_rate(rate_item)

        # Reversed video/audio
        if trackitem.playbackSpeed() < 0:
            start = trackitem.sourceOut()

        else:
            start = trackitem.sourceIn()

        source_start_time = otio.opentime.RationalTime(
            start,
            source_rate
        )
        source_duration = otio.opentime.RationalTime(
            trackitem.duration(),
            source_rate
        )

        source_range = otio.opentime.TimeRange(
            start_time=source_start_time,
            duration=source_duration
        )

        available_range = None
        hiero_clip = trackitem.source()
        if not hiero_clip.mediaSource().isOffline():
            start_time = otio.opentime.RationalTime(
                hiero_clip.mediaSource().startTime(),
                source_rate
            )
            duration = otio.opentime.RationalTime(
                hiero_clip.mediaSource().duration(),
                source_rate
            )
            available_range = otio.opentime.TimeRange(
                start_time=start_time,
                duration=duration
            )

        return source_range, available_range

    def add_gap(self, trackitem, otio_track, prev_out):
        gap_length = trackitem.timelineIn() - prev_out
        if prev_out != 0:
            gap_length -= 1

        rate = self.get_rate(trackitem.sequence())
        gap = otio.opentime.TimeRange(
            duration=otio.opentime.RationalTime(
                gap_length,
                rate
            )
        )
        otio_gap = otio.schema.Gap(source_range=gap)
        # append then to self._processed
        if otio_gap not in self._processed:
            otio_track.append(otio_gap)
            self._processed.append(otio_gap)

    def get_marker_color(self, tag):
        icon = tag.icon()
        pat = 'icons:Tag(?P<color>\w+)\.\w+'

        res = re.search(pat, icon)
        if res:
            color = res.groupdict().get('color')
            if color.lower() in marker_color_map:
                return marker_color_map[color.lower()]

        return otio.schema.MarkerColor.RED

    def add_markers(self, tags, hiero_item, otio_item):
        for tag in tags:
            if not tag.visible():
                continue

            if tag.name() == 'Copy':
                # Hiero adds this tag to a lot of clips
                continue

            frame_rate = self.get_rate(hiero_item)

            marked_range = otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(
                    tag.inTime(),
                    frame_rate
                ),
                duration=otio.opentime.RationalTime(
                    int(tag.metadata().dict().get('tag.length', '0')),
                    frame_rate
                )
            )

            marker = otio.schema.Marker(
                name=tag.name(),
                color=self.get_marker_color(tag),
                marked_range=marked_range,
                metadata={
                    'Hiero': tag.metadata().dict()
                }
            )

            # append then to self._processed
            if marker not in self._processed:
                otio_item.markers.append(marker)
                self._processed.append(marker)

    def add_clip(self, trackitem, otio_track, itemindex):
        itemindex = int(itemindex)
        hiero_clip = trackitem.source()

        # Add Gap if needed
        print("__ trackitem.name: `{}`".format(trackitem.name()))
        print("__ itemindex({}): `{}`".format(type(itemindex), itemindex))
        # for i, itemsss in enumerate(trackitem.parent().items()):
        #     print("__ trackitem.parent.item: `{}`".format(itemsss))
        #     print("__ trackitem.parent.index: `{}`".format(i))
        try:
            prev_item = (
                itemindex and trackitem.parent().items()[itemindex - 1] or
                trackitem
            )
        except:
            prev_item = (trackitem)

        if prev_item == trackitem and trackitem.timelineIn() > 0:
            self.add_gap(trackitem, otio_track, 0)

        elif (
            prev_item != trackitem and
            prev_item.timelineOut() != trackitem.timelineIn()
        ):
            self.add_gap(trackitem, otio_track, prev_item.timelineOut())

        # Create Clip
        source_range, available_range = self.get_clip_ranges(trackitem)

        otio_clip = otio.schema.Clip()
        otio_clip.name = trackitem.name()
        otio_clip.source_range = source_range

        # Add media reference
        media_reference = otio.schema.MissingReference()
        if not hiero_clip.mediaSource().isOffline():
            source = hiero_clip.mediaSource()
            media_reference = otio.schema.ExternalReference()
            media_reference.available_range = available_range

            path, name = os.path.split(source.fileinfos()[0].filename())
            target_url = os.path.normpath(os.path.join(path, name))

            # fix path separators
            if os.sep == '\\':
                target_url = target_url.replace(os.sep, os.altsep)

            media_reference.target_url = target_url
            media_reference.name = name

        otio_clip.media_reference = media_reference

        # Add Time Effects
        playbackspeed = trackitem.playbackSpeed()
        print(playbackspeed)
        if playbackspeed != 1:
            if playbackspeed == 0:
                time_effect = otio.schema.FreezeFrame()

            else:
                time_effect = otio.schema.LinearTimeWarp(
                    name="Retime",
                    time_scalar=playbackspeed
                )
            otio_clip.effects.append(time_effect)

        if trackitem.linkedItems():
            print(trackitem.linkedItems())

        # Add tags as markers
        self.add_markers(trackitem.tags(), trackitem.source(), otio_clip)

        # append then to self._processed
        if otio_clip not in self._processed:
            otio_track.append(otio_clip)
            self._processed.append(otio_clip)

        # Add Transition if needed
        if trackitem.inTransition() or trackitem.outTransition():
            self.add_transition(trackitem, otio_track)

    def add_transition(self, trackitem, otio_track):
        transitions = []

        if trackitem.inTransition():
            if trackitem.inTransition().alignment().name == 'kFadeIn':
                transitions.append(trackitem.inTransition())

        if trackitem.outTransition():
            transitions.append(trackitem.outTransition())

        for transition in transitions:
            alignment = transition.alignment().name

            if alignment == 'kFadeIn':
                in_offset_frames = 0
                out_offset_frames = (
                    transition.timelineOut() - transition.timelineIn()
                ) + 1

            elif alignment == 'kFadeOut':
                in_offset_frames = (
                    trackitem.timelineOut() - transition.timelineIn()
                ) + 1
                out_offset_frames = 0

            elif alignment == 'kDissolve':
                in_offset_frames = (
                    transition.inTrackItem().timelineOut() -
                    transition.timelineIn()
                )
                out_offset_frames = (
                    transition.timelineOut() -
                    transition.outTrackItem().timelineIn()
                )

            else:
                # kUnknown transition is ignored
                continue

            rate = trackitem.source().framerate().toFloat()
            in_time = otio.opentime.RationalTime(in_offset_frames, rate)
            out_time = otio.opentime.RationalTime(out_offset_frames, rate)

            otio_transition = otio.schema.Transition(
                name=alignment,    # Consider placing Hiero name in metadata
                transition_type=otio.schema.TransitionTypes.SMPTE_Dissolve,
                in_offset=in_time,
                out_offset=out_time,
                metadata={}
            )

            if alignment == 'kFadeIn':
                otio_track.insert(-2, otio_transition)

            else:
                otio_track.append(otio_transition)

    def add_tracks(self):
        """Splitter of trackItems
        """
        if not self._selected:
            # if not selected we loop Tracks
            for track in self._sequence.items():
                # find trackItems and process them to otio.Clip
                for event, clip in enumerate(track.items()):
                    print("__ event: `{}`".format(event))
                    self.tracks_with_clips(clip, track, event)

        else:
            for clip in self._selected:
                print("__ clip.type: `{}`".format(type(clip)))
                if not isinstance(clip, hiero.core.TrackItem):
                    continue
                event = clip.eventNumber()
                track = clip.parent()
                print("__ track.len: `{}`".format(len(track.items())))
                self.tracks_with_clips(clip, track, event)

        # Add tags as markers
        self.add_markers(self._sequence.tags(), self._sequence, self.otio_timeline.tracks)

    def tracks_with_clips(self, clip, track, event):
        print("__ clip.name: `{}`".format(clip.name()))
        print("__ track.name: `{}`".format(track.name()))
        print("__ event({}): `{}`".format(type(event), event))
        # find tracks and process them to otio.Track
        if isinstance(track, hiero.core.AudioTrack):
            kind = otio.schema.TrackKind.Audio

        else:
            kind = otio.schema.TrackKind.Video
        # assign otio object to specific category
        otio_track = otio.schema.Track(kind=kind)
        otio_track.name = track.name()

        if isinstance(clip, hiero.core.TrackItem) and \
                isinstance(clip.source(), hiero.core.Clip):
            self.add_clip(clip, otio_track, event)

        # append then to self._processed
        if otio_track not in self._processed:
            self.otio_timeline.tracks.append(otio_track)
            self._processed.append(otio_track)

        # Add tags as markers
        self.add_markers(
            self._sequence.tags(),
            self._sequence,
            self.otio_timeline.tracks
            )


    def create_OTIO(self):
        self.otio_timeline = otio.schema.Timeline()
        self.otio_timeline.name = self._sequence.name()

        self.add_tracks()
