/* global app, qe, $, ProjectItemType */
/*
              .____ _ ___ .____.______
--- - - --   /  .  \//  //  .  \  ___/ --- ---- - -
 - --- ---  /  ____/ __//  ____/ /_/  --- - -- ---
           /__/ /___/  /__/ /______/
          ._- -=[ PyPe 4 3veR ]=- -_.
*/


pype = {
  setEnvs: function (env) {
    for (key in env) {
      $.setenv(key, env[key])
    };
  },

  importClips: function (obj) {
    app.project.importFiles(obj.paths);
    return JSON.stringify(obj);
  },

  convertPathString: function (path) {
    return path.replace(
      new RegExp('\\\\', 'g'), '/').replace(new RegExp('//\\?/', 'g'), '');
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

    function objectIsSequence() {
      var isSequence = false;

      for (var s = 0; s < app.project.sequences.numSequences; s++) {
        if (item.name === app.project.sequences[s].name) {
          isSequence = true;
        }
      }

      return isSequence;
    }

    // walk through bins recursively
    function walkBins(item, source, rootBinCounter) {
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
    function getClipNames(seq, sequences) {
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
    function walkBins(bin) { // eslint-disable-line no-unused-vars
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
  getInOutOfAll: function () {
    var seq = app.project.activeSequence;
    var points = [];
    var output = [];

    // VIDEO CLIPS IN SEQUENCES
    for (var l = 0; l < seq.videoTracks.numTracks; l++) {
      var numOfClips = seq.videoTracks[l].clips.numTracks;
      // $.writeln('\n' + seq.name + ' ' + seq.videoTracks[l].name + ' has  ' + numOfClips + ' clips');
      for (var m = 0; m < numOfClips; m++) {
        var clip = seq.videoTracks[l].clips[m];
        points.push(Math.ceil(clip.start.seconds * 1000) / 1000);
        points.push(Math.ceil(clip.end.seconds * 1000) / 1000);
      }
    };

    points.sort(function (a, b) {
      return a - b
    });

    output.push(points[0]);
    output.push(points[points.length - 1]);

    return output;
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
          selected.push({
            'clip': clip,
            'sequence': seq,
            'videoTrack': seq.videoTracks[l]
          });
        }
      }
    }
    return selected;
  },

  dumpSequenceMetadata: function (sequence, data) {
    var kPProPrivateProjectMetadataURI = "http://ns.adobe.com/premierePrivateProjectMetaData/1.0/";
    var metadata = sequence.projectItem.getProjectMetadata();
    var pypeData = "pypeData"
    var xmp = new XMPMeta(metadata);
    app.project.addPropertyToProjectMetadataSchema(pypeData, "Pype Data", 2);

    for (key in data) {
      xmp.setProperty(kPProPrivateProjectMetadataURI, pypeData, JSON.stringify(data));
    };

    var str = xmp.serialize();
    sequence.projectItem.setProjectMetadata(str, [pypeData]);

  },

  loadSequenceMetadata: function (sequence) {
    var kPProPrivateProjectMetadataURI = "http://ns.adobe.com/premierePrivateProjectMetaData/1.0/";
    var metadata = sequence.projectItem.getProjectMetadata();
    var pypeData = "pypeData"
    var xmp = new XMPMeta(metadata);
    var pypeDataValue = xmp.getProperty(kPProPrivateProjectMetadataURI, pypeData);

    return JSON.parse(pypeDataValue);
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
      {
        task: 'compositing'
      },
      {
        task: 'roto'
      },
      {
        task: '3d'
      }
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
    var settings = sequence.getSettings()
    metadata['source.fps'] = (1 / interpretation.frameRate);
    metadata['timeline.fps'] = (1 / settings.videoFrameRate.seconds);
    var sequenceSize = pype.getImageSize();
    metadata['format.width'] = sequenceSize.h;
    metadata['format.height'] = sequenceSize.v;
    metadata['format.pixelaspect'] = interpretation.pixelAspectRatio;
    // TODO: change seconds to timecode
    metadata['source.start'] = clip.inPoint.seconds;
    metadata['source.end'] = clip.outPoint.seconds;
    metadata['source.duration'] = clip.duration.seconds;
    metadata['clip.start'] = clip.start.seconds;
    metadata['clip.end'] = clip.end.seconds;

    // set output path temorarily
    var outputPath = "C:\\Users\\hubert\\_PYPE_testing\\projects\\jakub_projectx\\editorial\\e01\\work\\edit\\transcode"

    // send render jobs to encoder
    $.writeln(clip.name)
    pype.render(outputPath, instance['name'], metadata['clip.start'], metadata['clip.end']);

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
            metadata['clip.audio'] = {
              'audioChanels': 2,
              'audioRate': 48000
            };
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
    var sequence = app.project.activeSequence
    // get original timeline in out points
    var defaultTimelinePointValue = -400000
    var origInPoint = Math.ceil(sequence.getInPoint() * 100) / 100;
    var origOutPoint = Math.ceil(sequence.getOutPoint() * 100) / 100;
    if (origInPoint == defaultTimelinePointValue) {
      var allInOut = pype.getInOutOfAll();
      origInPoint = allInOut[0];
      origOutPoint = allInOut[1];
    };

    // instances
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
    // set back original in/out point on timeline
    $.writeln(origInPoint, origOutPoint)
    app.project.activeSequence.setInPoint(origInPoint);
    app.project.activeSequence.setOutPoint(origOutPoint);
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
  },
  // $.getenv('PYTHONPATH')
  alert_message: function (message) {
    alert(message, "WARNING", true);
    app.setSDKEventMessage(message, 'error');
  },
  versionUpWorkFile: function () {
    var outputPath = pype.convertPathString(app.project.path);
    var outputName = String(app.project.name);
    var dirPath = outputPath.replace(outputName, '');
    var pattern = /_v([0-9]*)/g;
    var search = pattern.exec(outputName);
    var version = 1;
    var newFileName, absPath;

    if (search) {
      var match = parseInt(search[1], 10);
      version += match;
      var replVers = search[0].replace(search[1], (version).pad(search[1].length));
      newFileName = outputName.replace(search[0], replVers);
      absPath = dirPath + newFileName;
      app.project.saveAs(absPath);
      return newFileName;
    } else {
      var create = confirm('The project file name is missing version `_v###` \n example: `NameOfFile_v001.prproj`\n\n Would you like to create version?", true, "ERROR in name syntax');
      if (create) {
        var splitName = outputName.split('.');
        newFileName = splitName[0] + '_v001.' + splitName[1];
        absPath = dirPath + newFileName;
        app.project.saveAs(absPath);
        return newFileName;
      }
    }
  },
  transcodeExternal: function (fileToTranscode, fileOutputPath) {
    fileToTranscode = typeof fileToTranscode !== 'undefined' ? fileToTranscode : 'C:\\Users\\hubert\\_PYPE_testing\\projects\\jakub_projectx\\resources\\footage\\raw\\day01\\bbt_test_001_raw.mov';
    fileOutputPath = typeof fileOutputPath !== 'undefined' ? fileOutputPath : 'C:\\Users\\hubert\\_PYPE_testing\\projects\\jakub_projectx\\editorial\\e01\\work\\edit\\transcode';

    app.encoder.launchEncoder();
    var outputPresetPath = $.getenv('EXTENSION_PATH').split('/').concat(['encoding', 'prores422.epr']).join($._PPP_.getSep());
    var srcInPoint = 1.0; // encode start time at 1s (optional--if omitted, encode entire file)
    var srcOutPoint = 3.0; // encode stop time at 3s (optional--if omitted, encode entire file)
    var removeFromQueue = false;

    app.encoder.encodeFile(
      fileToTranscode,
      fileOutputPath,
      outputPresetPath,
      removeFromQueue,
      srcInPoint,
      srcOutPoint);

  },

  render: function (outputPath, clipName, inPoint, outPoint) {
    var outputPresetPath = $.getenv('EXTENSION_PATH').split('/').concat(['encoding', 'prores422.epr']).join($._PPP_.getSep());
    app.enableQE();
    var activeSequence = qe.project.getActiveSequence(); // we use a QE DOM function, to determine the output extension.
    if (activeSequence) {
      app.encoder.launchEncoder(); // This can take a while; let's get the ball rolling.

      var projPath = new File(app.project.path);

      if ((outputPath) && projPath.exists) {
        var outPreset = new File(outputPresetPath);
        if (outPreset.exists === true) {
          var outputFormatExtension = activeSequence.getExportFileExtension(outPreset.fsName);
          if (outputFormatExtension) {
            app.project.activeSequence.setInPoint(inPoint);
            app.project.activeSequence.setOutPoint(outPoint);
            var fullPathToFile = outputPath +
              $._PPP_.getSep() +
              clipName +
              "." +
              outputFormatExtension;

            pype.log(fullPathToFile);
            var outFileTest = new File(fullPathToFile);

            if (outFileTest.exists) {
              var destroyExisting = confirm("A file with that name already exists; overwrite?", false, "Are you sure...?");
              if (destroyExisting) {
                outFileTest.remove();
                outFileTest.close();
              }
            }

            app.encoder.bind('onEncoderJobComplete', $._PPP_.onEncoderJobComplete);
            app.encoder.bind('onEncoderJobError', $._PPP_.onEncoderJobError);
            app.encoder.bind('onEncoderJobProgress', $._PPP_.onEncoderJobProgress);
            app.encoder.bind('onEncoderJobQueued', $._PPP_.onEncoderJobQueued);
            app.encoder.bind('onEncoderJobCanceled', $._PPP_.onEncoderJobCanceled);


            // use these 0 or 1 settings to disable some/all metadata creation.
            app.encoder.setSidecarXMPEnabled(0);
            app.encoder.setEmbeddedXMPEnabled(0);


            var jobID = app.encoder.encodeSequence(app.project.activeSequence,
              fullPathToFile,
              outPreset.fsName,
              app.encoder.ENCODE_IN_TO_OUT,
              1); // Remove from queue upon successful completion?
            $._PPP_.updateEventPanel('jobID = ' + jobID);
            outPreset.close();
          }
        } else {
          $._PPP_.updateEventPanel("Could not find output preset.");
        }
      } else {
        $._PPP_.updateEventPanel("Could not find/create output path.");
      }
      projPath.close();
    } else {
      $._PPP_.updateEventPanel("No active sequence.");
    }
  }


};

Number.prototype.pad = function (size) {
  var s = String(this);
  while (s.length < (size || 2)) {
    s = "0" + s;
  }
  return s;
};

pype.getPyblishRequest();
