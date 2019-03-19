function include(arr, obj) {
  for (var i = 0; i < arr.length; i++) {
    if (arr[i] === obj) {
      return true
    }
  }
  return false
}

function addNewTrack() {
  app.enableQE();
  var activeSequence = qe.project.getActiveSequence();
  var newTrack = activeSequence.addTracks((1), 1)

  var sequence = app.project.activeSequence;

  for (var t = 0; t < sequence.videoTracks.numTracks; t++) {
    var videoTrack = sequence.videoTracks[t];
    var trackName = videoTrack.name
    var trackTarget = videoTrack.isTargeted();
    $.writeln(trackTarget);
    sequence.videoTracks[t].setTargeted(false, true);
    trackTarget = videoTrack.isTargeted();
    $.writeln(trackTarget);
    $.writeln(videoTrack);
  }
}

// addNewTrack();

function insertOrAppend() {
  var seq = app.project.activeSequence;
  if (seq) {
    var first = app.project.rootItem.children[0];
    if (first) {
      var numVTracks = seq.videoTracks.numTracks;
      var targetVTrack = seq.videoTracks[(numVTracks - 1)];
      if (targetVTrack) {
        // If there are already clips in this track,
        // append this one to the end. Otherwise,
        // insert at start time.

        if (targetVTrack.clips.numItems > 0) {
          var lastClip = targetVTrack.clips[(targetVTrack.clips.numItems - 1)];
          if (lastClip) {
            targetVTrack.insertClip(first, lastClip.end.seconds);
          }
        } else {
          targetVTrack.insertClip(first, '00;00;00;00');
        }
      } else {
        $._PPP_.updateEventPanel("Could not find first video track.");
      }
    } else {
      $._PPP_.updateEventPanel("Couldn't locate first projectItem.");
    }
  } else {
    $._PPP_.updateEventPanel("no active sequence.");
  }
}

var data = {};
data.binHierarchy = 'renderReference/mp4'
data.clips = {
  "lbb201sc010sh010_renderReference": {
    "_id": "5c8ea6df2af6172d1895a800",
    "schema": "pype:representation-2.0",
    "type": "representation",
    "parent": "5c8ea6df2af6172d1895a7ff",
    "name": "mp4",
    "data": {
      "path": "C:\\Users\\hubert\\_PYPE_testing\\projects\\jakub_projectx\\lbb201_thisone\\lbb201sc010\\lbb201sc010sh010\\publish\\render\\renderReference\\v001\\jkprx_lbb201sc010sh010_renderReference_v001.mp4",
      "template": "{publish.root}/{publish.folder}/v{version:0>3}/{publish.file}"
    },
    "dependencies": [],
    "context": {
      "root": "C:\\Users\\hubert\\_PYPE_testing\\projects",
      "project": {
        "name": "jakub_projectx",
        "code": "jkprx"
      },
      "task": "conform",
      "silo": "lbb201_thisone",
      "asset": "lbb201sc010sh010",
      "family": "render",
      "subset": "renderReference",
      "version": 1,
      "hierarchy": "lbb201_thisone\\lbb201sc010",
      "representation": "mp4"
    },
    "version": {
      "_id": "5c8ea6df2af6172d1895a7ff",
      "schema": "avalon-core:version-2.0",
      "type": "version",
      "parent": "5c8ea6df2af6172d1895a7fe",
      "name": 1,
      "locations": ["http://127.0.0.1"],
      "data": {
        "families": ["render", "reference", "clip", "ftrack"],
        "time": "20190317T205715Z",
        "author": "hubert",
        "source": "{root}/jakub_projectx/lbb201_thisone/work/conform/lbb201_thisone_conform_v001.prproj",
        "comment": "",
        "machine": "JAKUB_HP",
        "fps": null,
        "startFrame": 1,
        "endFrame": 1294,
        "handles": 10
      }
    }
  },
  "lbb201sc010sh020_renderReference": {
    "_id": "5c8ea6e02af6172d1895a808",
    "schema": "pype:representation-2.0",
    "type": "representation",
    "parent": "5c8ea6e02af6172d1895a807",
    "name": "mp4",
    "data": {
      "path": "C:\\Users\\hubert\\_PYPE_testing\\projects\\jakub_projectx\\lbb201_thisone\\lbb201sc010\\lbb201sc010sh020\\publish\\render\\renderReference\\v001\\jkprx_lbb201sc010sh020_renderReference_v001.mp4",
      "template": "{publish.root}/{publish.folder}/v{version:0>3}/{publish.file}"
    },
    "dependencies": [],
    "context": {
      "root": "C:\\Users\\hubert\\_PYPE_testing\\projects",
      "project": {
        "name": "jakub_projectx",
        "code": "jkprx"
      },
      "task": "conform",
      "silo": "lbb201_thisone",
      "asset": "lbb201sc010sh020",
      "family": "render",
      "subset": "renderReference",
      "version": 1,
      "hierarchy": "lbb201_thisone\\lbb201sc010",
      "representation": "mp4"
    },
    "version": {
      "_id": "5c8ea6e02af6172d1895a807",
      "schema": "avalon-core:version-2.0",
      "type": "version",
      "parent": "5c8ea6e02af6172d1895a806",
      "name": 1,
      "locations": ["http://127.0.0.1"],
      "data": {
        "families": ["render", "reference", "clip", "ftrack"],
        "time": "20190317T205715Z",
        "author": "hubert",
        "source": "{root}/jakub_projectx/lbb201_thisone/work/conform/lbb201_thisone_conform_v001.prproj",
        "comment": "",
        "machine": "JAKUB_HP",
        "fps": null,
        "startFrame": 1,
        "endFrame": 1404,
        "handles": 10
      }
    }
  }
};

function searchForBinWithName(nameToFind, folderObject) {

  // deep-search a folder by name in project
  var deepSearchBin = function (inFolder) {
    if (inFolder && inFolder.name === nameToFind && inFolder.type === 2) {
      return inFolder;
    } else {
      for (var i = 0; i < inFolder.children.numItems; i++) {
        if (inFolder.children[i] && inFolder.children[i].type === 2) {
          var foundBin = deepSearchBin(inFolder.children[i]);
          if (foundBin) return foundBin;
        }
      }
    }
    return undefined;
  };
  if (folderObject === undefined) {
    return deepSearchBin(app.project.rootItem);
  } else {
    return deepSearchBin(folderObject);
  }

}

function createDeepBinStructure(hierarchyString) {
  var parents = hierarchyString.split('/');

  // search for the created folder
  var currentBin = searchForBinWithName(parents[0]);
  // create bin if doesn't exists
  if (currentBin === undefined) {
    currentBin = app.project.rootItem.createBin(parents[0])
  };
  for (var b = 1; b < parents.length; b++) {
    var testBin = searchForBinWithName(parents[b], currentBin);
    if (testBin === undefined) {
      currentBin = currentBin.createBin(parents[b]);
    } else {
      currentBin = testBin;
    }
  }
  return currentBin
}

/**
 * Return instance representation of clip imported into bin
 * @param data {object} - has to have at least two attributes `clips` and `binHierarchy`
 * @return {Object}
 */
function importFiles(data) {
  if (app.project) {
    if (data !== undefined) {
      var pathsToImport = [];
      var namesToGetFromBin = [];
      var namesToSetToClips = [];
      var key = '';
      // get all paths and names list
      for (key in data.clips) {
        var path = data.clips[key]['data']['path'];
        var fileName = path.split('/');
        if (fileName.length <= 1) {
          fileName = path.split('\\');
        };
        fileName = fileName[fileName.length - 1]
        pathsToImport.push(path);
        namesToGetFromBin.push(fileName);
        namesToSetToClips.push(key)
      };

      // create parent bin object
      var parent = createDeepBinStructure(data.binHierarchy);

      if (parent.children.numItems > 0) {
        var refinedListForImport = [];
        // loop pathsToImport
        var binItemNames = [];
        for (var c = 0; c < parent.children.numItems; c++) {
          binItemNames.push(parent.children[c].name)
        }
        for (var p = 0; p < namesToSetToClips.length; p++) {
          // loop children in parent bin
          for (var i = 0; i < parent.children.numItems; i++) {

            if (namesToSetToClips[p] === parent.children[i].name) {
              parent.children[i].changeMediaPath(pathsToImport[p]);
              // clip exists and we can update path
              $.writeln("____clip exists and updating path");
              return
            } else {

              if (!include(binItemNames, namesToSetToClips[p])) {
                app.project.importFiles([pathsToImport[p]],
                  1, // suppress warnings
                  parent,
                  0); // import as numbered stills

                for (var pi = 0; pi < parent.children.numItems; pi++) {

                  if (namesToGetFromBin[p] === parent.children[pi].name) {
                    parent.children[pi].name = namesToSetToClips[p];
                  }
                }
              }
            }
          }
        }

      } else {
        app.project.importFiles(pathsToImport,
          1, // suppress warnings
          parent,
          0); // import as numbered stills
        for (var i = 0; i < parent.children.numItems; i++) {
          parent.children[i].name = namesToSetToClips[i];
        }
        return
      };


    }
  }
}


clips = importFiles(data)
