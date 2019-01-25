/* global app, qe, $, ProjectItemType */
/*
              .____ _ ___ .____.______
--- - - --   /  .  \//  //  .  \  ___/ --- ---- - -
 - --- ---  /  ____/ __//  ____/ /_/  --- - -- ---
           /__/ /___/  /__/ /______/
          ._- -=[ PyPe 4 3veR ]=- -_.
*/
var pype = {

  importClips: function (obj) {
    app.project.importFiles(obj.paths);
    return JSON.stringify(obj);
  },

  convertPathString: function (path) {
    return path.replace(
      new RegExp('\\\\', 'g'), '/').replace(new RegExp('//\\?/', 'g'), ''
    );
  },

  getWorkfile: function () {
    app.enableQE();
    var obj = {
      workfile: app.project.name,
      workdir: pype.convertPathString(app.project.path)
    };
    return JSON.stringify(obj);
  },

  getSequences: function () {
    var project = app.project;
    var sequences = [];
    for (var i = 0; i < project.sequences.numSequences; i++) {
      var seq = project.sequences[i];
      seq.clipNames = [];
      sequences[i] = seq;
      pype.log('sequences[i]  id: ' + project.sequences[i].sequenceID);
    }

    var obj = {
      sequences: sequences
    };
    return JSON.stringify(obj);
  },

  getSequenceItems: function (seqs) {
    app.enableQE();
    qe.project.init();
    var sequences = seqs;
    // pype.log('getSequenceItems sequences obj from app: ' + sequences);

    var rootFolder = app.project.rootItem;
    var binCounter = -1;
    var rootSeqCounter = -1; // count sequences in root folder

    // walk through root folder of project to differentiate between bins, sequences and clips
    for (var i = 0; i < rootFolder.children.numItems; i++) {
      // pype.log('\nroot item at ' + i + " is " +  rootFolder.children[i].name + " of type " + rootFolder.children[i].type);
      var item = rootFolder.children[i];
      // pype.log('item has video tracks? ' + item.videoTracks);
      if (item.type === 2) { // bin
        binCounter++;
        walkBins(item, 'root', binCounter);
      } else if (item.type === 1 && !item.getMediaPath()) { // sequence  OR other type of object
        // pype.log('\nObject of type 1 in root: ' +  typeof item + '   ' + item.name);
        if (objectIsSequence(item)) { // objects of type can also be other objects such as titles, so check if it really is a sequence
          // pype.log('\nSequence in root: ' +  item.name );
          rootSeqCounter++;
          var seq = qe.project.getSequenceAt(rootSeqCounter);
          //  pype.log('\nSequence in root, guid: ' +  seq );
          for (var property in seq) {
            if (seq.hasOwnProperty(property)) {
              //  pype.log('\nSequence in root: ' + seq );
              // pype.log('qe sequence prop: ' + property );
            }
          }
          getClipNames(seq, sequences);
        }
      }
    }

    function objectIsSequence () {
      var isSequence = false;

      for (var s = 0; s < app.project.sequences.numSequences; s++) {
        if (item.name === app.project.sequences[s].name) {
          isSequence = true;
        }
      }

      return isSequence;
    }

    // walk through bins recursively
    function walkBins (item, source, rootBinCounter) {
      app.enableQE();
      // pype.log('\nget clips for bin  ' + item.name  );

      var bin;
      if (source === 'root') { // bin in root folder
        bin = qe.project.getBinAt(rootBinCounter);
      } else { // bin in other bin
        bin = item;

        for (var i = 0; i < bin.numBins; i++) { // if bin contains bin(s) walk through them
          walkBins(bin.getBinAt(i));
        }
        // pype.log('Bin ' + bin.name + ' has ' + bin.numSequences + ' sequences ' );
        // var seqCounter = -1;
        for (var j = 0; j < bin.numSequences; j++) {
          // if(objectIsSequence(item)) {//objects of type can also be other objects such as titles, so check if it really is a sequence?
          // not needed because getSequenceAt apparently only looks at sequences already?
          var seq = bin.getSequenceAt(j);
          // pype.log('\nSequence in bin, guid: ' +  seq.guid );
          getClipNames(seq, sequences);
        }
      }
    }

    // walk through sequences and video & audiotracks to find clip names in sequences
    function getClipNames (seq, sequences) {
      for (var k = 0; k < sequences.length; k++) {
        //  pype.log('getClipNames seq.guid ' + seq.guid  );
        // pype.log(' getClipNames sequences[k].id ' +  sequences[k].sequenceID  );
        if (seq.guid === sequences[k].sequenceID) {
          //  pype.log('Sequence ' + seq.name + ' has ' + app.project.sequences[k].videoTracks.numTracks +' video tracks'  );
          //  pype.log('Sequence ' + seq.name + ' has ' + app.project.sequences[k].audioTracks.numTracks +' audio tracks'  );

          // VIDEO CLIPS IN SEQUENCES
          for (var l = 0; l < sequences[k].videoTracks.numTracks; l++) {
            var videoTrack = seq.getVideoTrackAt(l);
            //  pype.log(seq.name + ' has video track '+ videoTrack.name + ' at index ' + l);
            var clipCounter = 0;
            var numOfClips = app.project.sequences[k].videoTracks[l].clips.numTracks;
            //  pype.log('\n' + bin.name + ' ' + seq.name + ' ' + videoTrack.name + ' has  ' + numOfClips + ' clips');
            for (var m = 0; m < numOfClips; m++) {
              // var clip = app.project.sequences[k].videoTracks[l].clips[m];
              // pype.log('clips in video tracks:   ' + m + ' - ' + clip); //TrackItem, doesn't have name property
              // if a clip was deleted and another one added, the index of the new one is one  or more higher
              while (clipCounter < numOfClips) { // undefined because of old clips
                if (videoTrack.getItemAt(m).name) {
                  clipCounter++;
                  // pype.log('getClipNames ' + seq.name + ' ' + videoTrack.name + ' has  ' + videoTrack.getItemAt(m).name); //Object

                  for (var s = 0; s < sequences.length; s++) {
                    if (seq.guid === sequences[s].sequenceID) {
                      sequences[s].clipNames.push(videoTrack.getItemAt(m).name);
                    }
                  }
                }
                m++;
              }
            }
          }
          // pype.log('jsx after video loop clipsInSequences:' + clipsInSequences);

          // AUDIO CLIPS IN SEQUENCES
          for (var l = 0; l < sequences[k].audioTracks.numTracks; l++) {
            var audioTrack = seq.getAudioTrackAt(l);
            // pype.log(bin.name + ' ' + seq.name + ' has audio track '+ audioTrack.name + ' at index ' + l);
            // pype.log('\n' + bin.name + ' ' + seq.name + ' ' + audioTrack.name + ' has  ' + app.project.sequences[k].audioTracks[l].clips.numTracks + ' clips');
            var clipCounter = 0;
            var numOfClips = app.project.sequences[k].audioTracks[l].clips.numTracks;

            for (var m = 0; m < numOfClips; m++) {
              var clip = app.project.sequences[k].audioTracks[l].clips[m];
              // pype.log('clips in audio tracks:   ' + m + ' - ' + clip);
              // if a clip was deleted and another one added, the index of the new one is one  or more higher
              while (clipCounter < numOfClips) { // undefined because of old clips
                if (audioTrack.getItemAt(m).name) {
                  clipCounter++;
                  // pype.log(seq.name + ' ' + audioTrack.name + ' has  ' + audioTrack.getItemAt(m).name);

                  for (var s = 0; s < sequences.length; s++) {
                    if (seq.guid === sequences[s].sequenceID) {
                      sequences[s].clipNames.push(audioTrack.getItemAt(m).name);
                    }
                  }
                }
                m++;
              }
            }
          }
        } // end if
      } // end for
    } // end getClipNames

    pype.log('sequences returned:' + sequences);
    // return result to ReplaceService.js
    var obj = {
      data: sequences
    };
    // pype.log('jsx getClipNames obj:' + obj);
    return JSON.stringify(obj);
  },

  // getSequenceItems();
  getProjectItems: function () {
    var projectItems = [];
    app.enableQE();
    qe.project.init();

    var rootFolder = app.project.rootItem;
    // walk through root folder of project to differentiate between bins, sequences and clips
    for (var i = 0; i < rootFolder.children.numItems; i++) {
      // pype.log('\nroot item at ' + i + " is of type " + rootFolder.children[i].type);
      var item = rootFolder.children[i];

      if (item.type === 2) { // bin
        //  pype.log('\n' );
        pype.getProjectItems.walkBins(item);
      } else if (item.type === 1 && item.getMediaPath()) { // clip in root
        //  pype.log('Root folder has '  + item + ' ' + item.name);
        projectItems.push(item);
      }
    }

    // walk through bins recursively
    function walkBins (bin) { // eslint-disable-line no-unused-vars
      app.enableQE();

      // $.writeln('bin.name + ' has ' + bin.children.numItems);
      for (var i = 0; i < bin.children.numItems; i++) {
        var object = bin.children[i];
        // pype.log(bin.name + ' has ' + object + ' ' + object.name  + ' of type ' +  object.type + ' and has mediapath ' + object.getMediaPath() );
        if (object.type === 2) { // bin
          // pype.log(object.name  + ' has ' +  object.children.numItems  );
          for (var j = 0; j < object.children.numItems; j++) {
            var obj = object.children[j];
            if (obj.type === 1 && obj.getMediaPath()) { // clip  in sub bin
              // pype.log(object.name  + ' has ' + obj + ' ' +  obj.name  );
              projectItems.push(obj);
            } else if (obj.type === 2) { // bin
              walkBins(obj);
            }
          }
        } else if (object.type === 1 && object.getMediaPath()) { // clip in bin in root
          // pype.log(bin.name + ' has ' + object + ' ' + object.name );
          projectItems.push(object);
        }
      }
    }
    pype.log('\nprojectItems:' + projectItems.length + ' ' + projectItems);
    return projectItems;
  },

  replaceClips: function (obj) {
    pype.log('num of projectItems:' + projectItems.length);
    var hiresVOs = obj.hiresOnFS;
    for (var i = 0; i < hiresVOs.length; i++) {
      pype.log('hires vo name: ' + hiresVOs[i].name);
      pype.log('hires vo id:  ' + hiresVOs[i].id);
      pype.log('hires vo path: ' + hiresVOs[i].path);
      pype.log('hires vo replace: ' + hiresVOs[i].replace);

      for (var j = 0; j < projectItems.length; j++) {
        // pype.log('projectItem id: ' + projectItems[j].name.split(' ')[0] + ' ' + hiresVOs[i].id + ' can change path  ' + projectItems[j].canChangeMediaPath() );
        if (projectItems[j].name.split(' ')[0] === hiresVOs[i].id && hiresVOs[i].replace && projectItems[j].canChangeMediaPath()) {
          pype.log('replace: ' + projectItems[j].name + ' with ' + hiresVOs[i].name);
          projectItems[j].name = hiresVOs[i].name;
          projectItems[j].changeMediaPath(hiresVOs[i].path);
        }
      }
    }
  },

  getActiveSequence: function () {
    return app.project.activeSequence;
  },

  getImageSize: function () {
    return {
      h: app.project.activeSequence.frameSizeHorizontal,
      v: app.project.activeSequence.frameSizeVertical
    };
  },

  getSelectedItems: function () {
    var seq = app.project.activeSequence;
    var selected = [];

    // VIDEO CLIPS IN SEQUENCES
    for (var l = 0; l < seq.videoTracks.numTracks; l++) {
      var numOfClips = seq.videoTracks[l].clips.numTracks;
      // $.writeln('\n' + seq.name + ' ' + seq.videoTracks[l].name + ' has  ' + numOfClips + ' clips');
      for (var m = 0; m < numOfClips; m++) {
        var clip = seq.videoTracks[l].clips[m];
        if (clip.isSelected()) {
          selected.push(
            {
              'clip': clip,
              'sequence': seq,
              'videoTrack': seq.videoTracks[l]
            }
          );
        }
      }
    }
    return selected;
  },

  /**
   * Return instance representation of clip
   * @param clip {object} - index of clip on videoTrack
   * @param sequence {object Sequence} - Sequence clip is in
   * @param videoTrack {object VideoTrack} - VideoTrack clip is in
   * @return {Object}
   */
  getClipAsInstance: function (clip, sequence, videoTrack) {
    // var clip = sequence.videoTracks.clips[clipIdx];
    if ((clip.projectItem.type !== ProjectItemType.CLIP) &&
        (clip.mediaType !== 'Video')) {
      return false;
    }

    var interpretation = clip.projectItem.getFootageInterpretation();
    var instance = {};
    instance['publish'] = true;
    instance['family'] = 'clip';
    instance['name'] = clip.name;
    instance['filePath'] = pype.convertPathString(clip.projectItem.getMediaPath());
    // TODO: tags - wtf and how to get them
    instance['tags'] = [
      {task: 'compositing'},
      {task: 'roto'},
      {task: '3d'}
    ];
    instance['layer'] = videoTrack.name;
    instance['sequence'] = sequence.name;
    // TODO: is it original format of clip or format we want to transcode it to?
    instance['representation'] = 'mov';
    // metadata
    var metadata = {};
    // TODO: how to get colorspace clip info
    metadata['colorspace'] = 'bt.709';
    // frameRate in Premiere is fraction of second, to get "normal fps",
    // we need 1/x
    metadata['fps'] = (1 / interpretation.frameRate);
    var sequenceSize = pype.getImageSize();
    metadata['format.width'] = sequenceSize.h;
    metadata['format.height'] = sequenceSize.v;
    metadata['format.pixelaspect'] = interpretation.pixelAspectRatio;
    // TODO: change seconds to timecode
    metadata['source.start'] = clip.start.seconds;
    metadata['source.end'] = clip.end.seconds;
    metadata['source.duration'] = clip.duration.seconds;
    metadata['clip.start'] = clip.inPoint.seconds;
    metadata['clip.end'] = clip.outPoint.seconds;

    // get linked clips
    var linkedItems = clip.getLinkedItems();
    if (linkedItems) {
      for (var li = 0; li < linkedItems.numItems; li++) {
        if (linkedItems[li].mediaType === 'Audio') {
          var audioClip = linkedItems[li];
          // linked clip is audio
          // check in and out are same
          if ((audioClip.inPoint.seconds === clip.inPoint.seconds) &&
             (audioClip.outPoint.seconds === clip.outPoint.seconds)) {
            metadata['hasAudio'] = true;
            // TODO: find out how to get those without dealing with Qe
            metadata['clip.audio'] = {'audioChanels': 2, 'audioRate': 48000};
            var timelineAudio = [];
            var audioMetadata = [];
            audioMetadata['audioChannels'] = 2;
            audioMetadata['audioRate'] = 48000;
            audioMetadata['source.start'] = audioClip.start.seconds;
            audioMetadata['source.end'] = audioClip.end.seconds;
            audioMetadata['source.duration'] = audioClip.duration.seconds;
            audioMetadata['clip.start'] = audioClip.inPoint.seconds;
            audioMetadata['clip.end'] = audioClip.outPoint.seconds;
            timelineAudio.push(audioMetadata);
            metadata['timeline.audio'] = timelineAudio;
          }
        }
      }
    }
    // set metadata to instance
    instance['metadata'] = metadata;
    return instance;
  },

  getSelectedClipsAsInstances: function () {
    var instances = [];
    var selected = pype.getSelectedItems();
    for (var s = 0; s < selected.length; s++) {
      var instance = pype.getClipAsInstance(
        selected[s].clip,
        selected[s].sequence,
        selected[s].videoTrack
      );
      if (instance !== false) {
        instances.push(instance);
      }
    }
    return instances;
  },

  getPyblishRequest: function () {
    var request = {};
    var instances = pype.getSelectedClipsAsInstances();
    request['instances'] = instances;
    return JSON.stringify(request);
  },

  log: function (info) {
    app.setSDKEventMessage(JSON.stringify(info), 'info');
  },

  message: function (msg) {
    $.writeln(msg); // Using '$' object will invoke ExtendScript Toolkit, if installed.
  }

};
// pype.getSelectedItems()
