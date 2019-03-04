/* global CSInterface, $, querySelector, api, displayResult */
var csi = new CSInterface();
var output = document.getElementById('output');

var rootFolderPath = csi.getSystemPath(SystemPath.EXTENSION);
var timecodes = cep_node.require('node-timecodes');
var process = cep_node.require('process');


function getEnv() {
  csi.evalScript('pype.getProjectFileData();', function (result) {
    process.env.EXTENSION_PATH = rootFolderPath
    window.ENV = process.env;
    var resultData = JSON.parse(result);
    for (key in resultData) {
      window.ENV[key] = resultData[key];
    };
    csi.evalScript('pype.setEnvs(' + JSON.stringify(window.ENV) + ')');
  });
}

function renderClips() {
  csi.evalScript('pype.transcodeExternal(' + rootFolderPath + ');', function (result) {
    displayResult(result);
  });
}

function displayResult(r) {
  console.log(r);
  csi.evalScript('$.writeln( ' + JSON.stringify(r) + ' )');
  output.classList.remove("error");
  output.innerText = r;
}

function displayError(e) {
  output.classList.add("error");
  output.innerText = e.message;
}

function loadJSX() {
  // get the appName of the currently used app. For Premiere Pro it's "PPRO"
  var appName = csi.hostEnvironment.appName;
  var extensionPath = csi.getSystemPath(SystemPath.EXTENSION);

  // load general JSX script independent of appName
  var extensionRootGeneral = extensionPath + '/jsx/';
  csi.evalScript('$._ext.evalFiles("' + extensionRootGeneral + '")');

  // load JSX scripts based on appName
  var extensionRootApp = extensionPath + '/jsx/' + appName + '/';
  csi.evalScript('$._ext.evalFiles("' + extensionRootApp + '")');
  // csi.evalScript('$._PPP_.logConsoleOutput()');
  getEnv();

  csi.evalScript('$._PPP_.updateEventPanel( "' + "all plugins are loaded" + '" )');
  csi.evalScript('$._PPP_.updateEventPanel( "' + "testing function done" + '" )');

}

// run all at loading
loadJSX()

function evalScript(script) {
  var callback = function (result) {
    displayResult(result);
  };
  csi.evalScript(script, callback);
}

function deregister() {
  api.deregister_plugin_path().then(displayResult);
}

function register() {
  var $ = querySelector('#register');
  var path = $('input[name=path]').value;
  api.register_plugin_path(path).then(displayResult);
}

function getStagingDir() {
  // create stagingDir
  const fs = require('fs-extra');
  const os = require('os');
  const path = require('path');
  const UUID = require('pure-uuid');
  const id = new UUID(4).format();
  const stagingDir = path.join(os.tmpdir(), id);

  fs.mkdirs(stagingDir);
  return stagingDir;

}

function convertPathString(path) {
  return path.replace(
    new RegExp('\\\\', 'g'), '/').replace(new RegExp('//\\?/', 'g'), '');
}

function publish() {
  var $ = querySelector('#publish');
  // var gui = $('input[name=gui]').checked;
  var gui = true;
  var versionUp = $('input[name=version-up]').checked;
  var jsonSendPath = $('input[name=send-path]').value;
  var jsonGetPath = $('input[name=get-path]').value;
  var publish_path = window.ENV['PUBLISH_PATH'];

  if (jsonSendPath == '') {
    // create temp staging directory on local
    var stagingDir = convertPathString(getStagingDir());

    // copy project file to stagingDir
    const fs = require('fs-extra');
    const path = require('path');

    csi.evalScript('pype.getProjectFileData();', function (result) {
      displayResult(result);
      var data = JSON.parse(result);
      displayResult(stagingDir);
      displayResult(data.projectfile);
      var destination = convertPathString(path.join(stagingDir, data.projectfile));
      displayResult('copy project file');
      displayResult(data.projectfile);
      displayResult(destination);
      fs.copyFile(data.projectpath, destination);
      displayResult('project file coppied!');
    });

    // publishing file
    csi.evalScript('pype.getPyblishRequest("' + stagingDir + '");', function (r) {
      var request = JSON.parse(r);
      displayResult(r);
      csi.evalScript('pype.encodeRepresentation(' + JSON.stringify(request) + ');', function (result) {
        // create json for pyblish
        var jsonfile = require('jsonfile');
        var jsonSendFile = stagingDir + '_send.json'
        var jsonGetFile = stagingDir + '_get.json'
        $('input[name=send-path]').value = jsonSendFile;
        $('input[name=get-path]').value = jsonGetFile;
        var jsonContent = JSON.parse(result);
        jsonfile.writeFile(jsonSendFile, jsonContent);
        var checkingFile = function (path) {
          var timeout = 1000;
          setTimeout(function () {
              if (fs.existsSync(path)) {
                // register publish path
                api.register_plugin_path(publish_path).then(displayResult);
                // send json to pyblish
                api.publish(jsonSendFile, jsonGetFile, gui).then(function (result) {
                  // check if resulted path exists as file
                  if (fs.existsSync(result.get_json_path)) {
                    // read json data from resulted path
                    displayResult('Updating metadata of clips after publishing');

                    jsonfile.readFile(result.get_json_path, function (err, json) {
                      csi.evalScript('pype.dumpPublishedInstancesToMetadata(' + JSON.stringify(json) + ');');
                    })

                    // version up project
                    if (versionUp) {
                      displayResult('Saving new version of the project file');
                      csi.evalScript('pype.versionUpWorkFile();');
                    };
                  } else {
                    // if resulted path file not existing
                    displayResult('Publish has not been finished correctly. Hit Publish again to publish from already rendered data, or Reset to render all again.');
                  };

                });

              } else {
                displayResult('waiting');
                checkingFile(path);
              };
            },
            timeout)
        };

        checkingFile(jsonContent.waitingFor)
      });
    });
  } else {
    // register publish path
    api.register_plugin_path(publish_path).then(displayResult);
    // send json to pyblish
    api.publish(jsonSendPath, gui).then(displayResult);
  };
  $('input[name=send-path]').value = '';
  $('input[name=get-path]').value = '';
}

function context() {
  var $ = querySelector('#context');
  var project = $('input[name=project]').value;
  var asset = $('input[name=asset]').value;
  var task = $('input[name=task]').value;
  var app = $('input[name=app]').value;
  api.context(project, asset, task, app).then(displayResult);
}

function tc(timecode) {
  var seconds = timecodes.toSeconds(timecode);
  var timec = timecodes.fromSeconds(seconds);
  displayResult(seconds);
  displayResult(timec);
}

// bind buttons

$('#btn-set-context').click(function () {
  context();
});

$('#btn-register').click(function () {
  register();
});

$('#btn-deregister').click(function () {
  deregister();
});

$('#btn-publish').click(function () {
  publish();
});

$('#btn-send-reset').click(function () {
  var $ = querySelector('#publish');
  $('input[name=send-path]').value = '';
});
$('#btn-get-reset').click(function () {
  var $ = querySelector('#publish');
  $('input[name=get-path]').value = '';
});
$('#btn-get-active-sequence').click(function () {
  evalScript('pype.getActiveSequence();');
});

$('#btn-get-selected').click(function () {
  $('#output').html('getting selected clips info ...');
  evalScript('pype.getSelectedItems();');
});

$('#btn-get-env').click(function () {
  displayResult(window.ENV);
});

$('#btn-get-projectitems').click(function () {
  evalScript('pype.getProjectItems();');
});

$('#btn-metadata').click(function () {
  var path = 'C:/Users/pype/AppData/Local/Temp/pype_aport_llkpwbe2/return_data.json'
  var jsonfile = require('jsonfile')
  jsonfile.readFile(path, function (err, json) {
    csi.evalScript('pype.dumpPublishedInstancesToMetadata(' + JSON.stringify(json) + ');');
  })


});
$('#btn-get-frame').click(function () {
  evalScript('$._PPP_.exportCurrentFrameAsPNG();');
});

$('#btn-tc').click(function () {
  tc('00:23:47:10');
});

$('#btn-generateRequest').click(function () {
  evalScript('pype.getPyblishRequest();');
});

$('#btn-newWorkfileVersion').click(function () {
  evalScript('pype.versionUpWorkFile();');
});
