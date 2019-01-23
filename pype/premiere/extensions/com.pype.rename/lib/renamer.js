/* global $, CSInterface, process */
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

var csi = new CSInterface();

function displayResults (data) {
  var con = $('#output');
  con.html(data);
}

// Bind renamer controls
$('#renamer-modes a').click(function () {
  var mode = $(this).data('mode');
  $('#renamerDropdown').dropdown('toggle');
  $('#renamerDropdown').html($(this).html());
  $('#renamer-ui .pane').css('display', 'none');
  $('#rpane-' + mode).css('display', 'block');
  $('#renamer-modes').data('mode', mode);
  return false;
});

$('#renamer-caseSelect a').click(function () {
  $('#renamer-caseSelect').data('mode', $(this).data('mode'));
  return false;
});

$('#btn-rename').click(function () {
  var mode = $('#renamer-modes').data('mode');
  if (!mode) {
    mode = 'seqRename';
  }
  var data = '';
  switch (mode) {
    case 'seqRename':
      data = {
        'pattern': $('#rpane-' + mode + ' input[name=renamer-pattern]').val(),
        'start': $('#rpane-' + mode + ' input[name=renamer-start]').val(),
        'increment': $('#rpane-' + mode + ' input[name=renamer-inc]').val()
      };
      csi.evalScript('renameSeq(' + JSON.stringify(data) + ');', function (result) {
        displayResults(result);
      });
      break;

    case 'simpleRename':
      data = $('#rpane-' + mode + ' input[name=renamer-newName]').val();
      displayResults(data);
      csi.evalScript('renameSimple("' + data + '");', function (result) {
        displayResults(result);
      });
      break;

    case 'findAndReplace':
      data = {
        'find': $('#rpane-' + mode + ' input[name=renamer-find]').val(),
        'replaceWith': $('#rpane-' + mode + ' input[name=renamer-replace]').val()
      };
      csi.evalScript('renameFindReplace(' + JSON.stringify(data) + ');', function (result) {
        displayResults(result);
      });
      break;

    case 'matchSequence':
      // not implemented
      break;

    case 'clipRename':
      csi.evalScript('renameClipRename();', function (result) {
        displayResults(result);
      });
      break;

    case 'changeCase':
      var stringCase = 0;
      var caseMode = $('#renamer-caseSelect').data('mode');
      if (caseMode === 'uppercase') {
        stringCase = 1;
      }
      $('#renamer-case').val(caseMode);
      csi.evalScript('renameChangeCase("' + stringCase + '");', function (result) {
        displayResults(result);
      });
      break;

    default:
  }
});

// $.get('http://localhost:43')

// displayResults('-' + window.cep.process.AVALON_PROJECT);
