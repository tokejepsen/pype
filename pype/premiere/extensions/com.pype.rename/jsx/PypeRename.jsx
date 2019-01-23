/* global app */
/* --------------------------------------
   -. ==  [ part 0f PyPE CluB ] == .-
_______________.___._____________________
\______   \__  |   |\______   \_   _____/
 |     ___//   |   | |     ___/|    __)_
 |    |    \____   | |    |    |        \
 |____|    / ______| |____|   /_______  /
           \/                         \/
        .. __/ CliP R3N4M3R \__ ..
*/

/**
 * Sequence rename seleced clips
 * @param {Object} data - {pattern, start, increment}
 */
function renameSeq (data) { // eslint-disable-line no-unused-vars
  var selected = app.project.activeSequence.getSelection();
  if (selected.length < 1) {
    app.setSDKEventMessage('nothing selected', 'error');
    return false;
  }
  app.setSDKEventMessage('pattern ' + data.pattern + '\n' + 'increment ' + data.increment, 'info');
  // get padding
  var padPtr = RegExp('(.*?)(#+)(.*)');
  var res = data.pattern.match(padPtr);
  // res is now null if there is no padding string (###) in Pattern
  // or array - res[1] is whats before padding string
  // res[2] is padding string
  // res[3] is whatever is after
  if (!res) {
    app.setSDKEventMessage('no padding string detected in pattern ' + data.pattern, 'error');
    return false;
  }

  // convert to int
  var index = parseInt(data.start);
  // change padding string to zero: '####' -> '0000'
  var rx = RegExp('#', 'g');
  var zero = res[2].replace(rx, '0');
  // iterate over selection
  for (var c = 0; c < selected.length; c++) {
    // convert index to string
    var indexStr = '' + index;
    // left-zero pad number
    var padding = zero.substring(0, zero.length - indexStr.length) + indexStr;
    // put name together
    selected[c].name = res[1] + padding + res[3];
    // add increment
    index = index + parseInt(data.increment);
  }
  return JSON.stringify({'status': 'renamed ' + selected.length + ' clips'});
}

/**
 * Simple rename clips
 * @param {string} newName - new clip name. `{shot}` designates current clip name
 * @return {string} result - return stringified JSON status
 */
function renameSimple (newName) { // eslint-disable-line no-unused-vars
  app.setSDKEventMessage('Replacing with pattern ' + newName, 'info');
  var selected = app.project.activeSequence.getSelection();
  if (selected.length < 1) {
    app.setSDKEventMessage('nothing selected', 'error');
    return false;
  }
  var rx = RegExp('{shot}', 'i');
  for (var c = 0; c < selected.length; c++) {
    // find {shot} token and replace it with existing clip name
    selected[c].name = newName.replace(rx, selected[c].name);
  }
  return JSON.stringify({'status': 'renamed ' + selected.length + ' clips'});
}

/**
 * Find string in clip name and replace it with another
 * @param {Object} data - {find, replaceWith} object
 * @return {string} result - return stringified JSON status
 */
function renameFindReplace (data) { // eslint-disable-line no-unused-vars
  var selected = app.project.activeSequence.getSelection();
  if (selected.length < 1) {
    app.setSDKEventMessage('nothing selected', 'error');
    return false;
  }

  var rx = RegExp('{shot}', 'i');
  for (var c = 0; c < selected.length; c++) {
    // replace {shot} token with actual clip name
    var find = data.find.replace(rx, selected[c].name);
    var repl = data.replaceWith.replace(rx, selected[c].name);
    // replace find with replaceWith
    selected[c].name = selected[c].name.replace(find, repl);
  }
  return JSON.stringify({'status': 'renamed ' + selected.length + ' clips'});
}

/**
 * Replace current clip name with filename (without extension)
 * @return {string} result - return stringified JSON status
 */
function renameClipRename () { // eslint-disable-line no-unused-vars
  var selected = app.project.activeSequence.getSelection();
  if (selected.length < 1) {
    app.setSDKEventMessage('nothing selected', 'error');
    return false;
  }

  var regexp = new RegExp('.[^/.]+$');
  for (var c = 0; c < selected.length; c++) {
  // suddenly causes syntax error on regexp? So using explicit contructor
  // regexp above.
  // selected[c].name = selected[c].projectItem.name.replace(/\.[^/.]+$/, '');
    selected[c].name = selected[c].projectItem.name.replace(regexp, '');
  }
  return JSON.stringify({'status': 'renamed ' + selected.length + ' clips'});
}

/**
 * Change clip name to lower or upper case
 * @param {int} case - 0 lower, 1 upper
 * @return {string} result - return stringified JSON status
 */
function renameChangeCase (caseMode) { // eslint-disable-line no-unused-vars
  var selected = app.project.activeSequence.getSelection();
  if (selected.length < 1) {
    app.setSDKEventMessage('nothing selected', 'error');
    return false;
  }

  for (var c = 0; c < selected.length; c++) {
    if (caseMode === 0) {
      selected[c].name = selected[c].name.toLowerCase();
    } else {
      selected[c].name = selected[c].name.toUpperCase();
    }
  }
  return JSON.stringify({'status': 'renamed ' + selected.length + ' clips'});
}

function keepExtension () {
  return app.setExtensionPersistent('com.pype.rename', 0);
}

keepExtension();
