Number.prototype.pad = function (size) {
  var s = String(this);
  while (s.length < (size || 2)) {
    s = "0" + s;
  }
  return s;
}

getSelectedVideoTrackItems = function () {
  var seq = app.project.activeSequence;
  var selected = [];
  var videoTracks = seq.videoTracks;
  var numOfVideoTracks = videoTracks.numTracks;

  // VIDEO CLIPS IN SEQUENCES
  for (var l = 0; l < numOfVideoTracks; l++) {
    var videoTrack = seq.videoTracks[l];
    if (videoTrack.isTargeted()) {
      $.writeln(videoTrack.name);
      var numOfClips = videoTrack.clips.numTracks;
      for (var m = 0; m < numOfClips; m++) {
        var clip = videoTrack.clips[m];

        selected.push({
          'name': clip.name,
          'clip': clip,
          'sequence': seq,
          'videoTrack': videoTrack
        });

      }
    }
  };
  var names = [];
  var items = {};
  var sorted = [];
  for (var c = 0; c < selected.length; c++) {
    items[selected[c].name] = selected[c];
    names.push(selected[c].name);
  };
  names.sort()

  for (var c = 0; c < names.length; c++) {
    sorted.push(items[names[c]])
  };

  return sorted;
}

selected = getSelectedVideoTrackItems();

var startCount = 10;
var stepCount = 10;
var padding = 4;
var newItems = {};
var episode = 'lbb201';
var shotPref = 'sh';
var count = 0;
for (var c = 0; c < selected.length; c++) {
  // fill in hierarchy if set
  var parents = [];
  var hierarchy = [];

  count = (c * stepCount) + startCount;
  var name = selected[c].name;
  var sequenceName = name.slice(0, 5)
  var newName = episode + shotPref + (count).pad(padding);

  parents.push({
    'entityType': 'episode',
    'entityName': episode
  });
  hierarchy.push(episode);

  parents.push({
    'entityType': 'sequence',
    'entityName': sequenceName
  });
  hierarchy.push(sequenceName);

  newItems[newName] = {
    'parents': parents,
    'hierarchy': hierarchy.join('/'),
  };
};

pype.dumpSequenceMetadata(app.project.activeSequence, newItems)
$.writeln(JSON.stringify(newItems))
