/* global CSInterface, $, querySelector, api, displayResult */
var csi = new CSInterface();
var output = document.getElementById('output');

var rootFolderPath = csi.getSystemPath(SystemPath.EXTENSION);
var timecodes = cep_node.require('node-timecodes');
var process = cep_node.require('process');


function getEnv() {
  csi.evalScript('pype.getWorkfile();', function (result) {
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
  csi.evalScript('$._PPP_.logConsoleOutput()');
  csi.evalScript('$._PPP_.updateEventPanel( "' + "all plugins are loaded" + '" )');
  csi.evalScript('$._PPP_.updateEventPanel( "' + "testing function done" + '" )');
  getEnv();
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

function publish() {
  var $ = querySelector('#publish');
  var path = $('input[name=path]').value;
  var gui = $('input[name=gui]').checked;
  api.publish(path, gui).then(displayResult);
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
