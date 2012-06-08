/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */


////////////////////////////////////////////////////////////////////////////////// List of things that want/need to be done:
// 1. Handle preprocessed-scripts
// 2. Handle non-flat-format builds
// 3. Support embedded scripts
// 4. Make this faster if possible
// 5. Branch coverage data
// 6. Fix function hit counts.
////////////////////////////////////////////////////////////////////////////////


let Cc = Components.classes, Ci = Components.interfaces;

Components.utils.import("resource:///modules/FileUtils.jsm");
Components.utils.import("resource:///modules/NetUtil.jsm");
Components.utils.import("resource:///modules/ctypes.jsm");

if (arguments.length < 2) {
  throw ("Need two arguments: <output json data> <output lcov> " +
      "[<directories to scan for more scripts>]\n");
}

// Snarf a file to a string
function loadFileToString(file) {
  let frawin = Cc["@mozilla.org/network/file-input-stream;1"]
                 .createInstance(Ci.nsIFileInputStream);
  frawin.init(file, -1, 0, 0);
  let fin = Cc["@mozilla.org/scriptableinputstream;1"]
              .createInstance(Ci.nsIScriptableInputStream);
  fin.init(frawin);
  let data = "";
  let str = fin.read(4096);
  while (str.length > 0) {
    data += str;
    str = fin.read(4096);
  }
  fin.close();

  return data;
}

// A generator that returns the lines of the file. Useful for not blowing up
// memory usage.
function yieldFileLines(file) {
  let frawin = Cc["@mozilla.org/network/file-input-stream;1"]
                 .createInstance(Ci.nsIFileInputStream);
  frawin.init(file, -1, 0, 0);
  frawin.QueryInterface(Ci.nsILineInputStream);
  let line = {};
  while (frawin.readLine(line)) {
    yield line.value;
  }
  yield line.value;
}

// Map a script "filename" to a real one
function find_file(file, base) {
  // I don't know why this comes up, but I sometimes see things like
  // resource:///foo -> resource:///bar (the correct file is the latter)
  let parts = file.split(" -> ");
  file = parts[parts.length - 1];
  if (file.indexOf(":") >= 0) {
    // resource URIs make channels whose specs are the file URIs. This is a
    // shortcut to get the filename [leaks the channel, though]
    try {
      var channel = NetUtil.newChannel(file);
      file = channel.URI.spec;
    } catch (e) {
      print("Unable to view URL " + file);
      return file;
    }
  }
  // Delete the beginning of file URIs
  if (file.substring(0, "file://".length) == "file://")
    file = file.substring("file://".length);
  else if (file.indexOf(":") >= 0) {
    // Any other URI is impossible to handle
    print("Unknown URL: " + file);
    return file;
  }

  // We want to follow symlinks (hope people do flat chrome files!)
  let fd = FileUtils.File(file[0] == "/" ? file : base + "/" + file);
  if (fd.exists()) {
    fd.normalize();
    return fd.isSymlink() ? fd.target : fd.path;
  }

  return '';
}

// Handle a result line for a single execution.
function process_test(test, totals) {
  // We want to get all the counts, and we don't care about how it gets executed
  // so sum it all up
  function exec_count(data) {
    let sum = 0;
    for (let type in data)
      sum += data[type];
    return sum;
  }
  // Helper for default stuff
  function get_default(obj, prop, def) {
    return prop in obj ? obj[prop] : def;
  }
  // Each line is [base, summary, contents]
  let base_file = test.shift();
  for (let line of test) {
    // Ignore files that don't map to source code (e.g., eval inner scripts).
    let file = find_file(line[0].file, base_file);
    if (file == "") continue;
    if (!(file in totals))
      totals[file] = {funcs: {}, lines: {}};

    // If the contents isn't null
    // XXX? Still needed?
    if (line[1] !== null) {
      // pcccount data looks like:
      // {text: ''; opcodes: []}
      // Each opcode looks like:
      // {line: 123; counts: {typea: 13, typeb:12}, textOffset: 534, text: '',
      //  name: ''} [textOffset/text isn't always present]
      let line_data = {};
      for (let opcodeData of line[1].opcodes) {
        //if (!('textOffset' in opcodeData) && !('text' in opcodeData)) {
        //  continue;
        //}
        let counts = exec_count(opcodeData.counts);
        // There can be multiple opcodes per line. Instead of adding everything
        // up, just take the maximum of any operand in the line. Then add all
        // the data in one go to the output array
        line_data[opcodeData.line] = Math.max(counts,
          get_default(line_data, opcodeData.line, 0));
      }
      let lines = totals[file].lines;
      for (let line in line_data) {
        lines[line] = get_default(lines, line, 0) + line_data[line];
      }
    }

    // Process function coverage using the summary. This produces insane counts,
    // since it uses the sum of all codes, but it's simplest for now.
    let funcname = line[0].name;
    if (funcname) {
      let data = get_default(totals[file].funcs, funcname,
        {line: line[0].line, count: 0});
      data.count += exec_count(line[0].totals);
      totals[file].funcs[funcname] = data;
    }
  }
}

// Process the input to produce the coverage data
let totals = {};
for (let line of yieldFileLines(FileUtils.File(arguments[0]))) {
  if (line.length == 0)
    continue;
  let test = JSON.parse(line);
  process_test(test, totals);
}

function insert_not_exec(file, file_data) {
  // So, the JS shell only outputs this to stdout. We use a system+ctypes thunk
  // to shove this where it needs to go.
  let outFile = FileUtils.File("/tmp/disrendezvous");
  outFile.createUnique(Ci.nsIFile.NORMAL_FILE_TYPE, 6 * 8 * 8);
  let libc = ctypes.open("libc.so.6");
  let system = libc.declare("system", ctypes.default_abi, ctypes.int, ctypes.char.ptr);
  system("/src/build/trunk/mail/mozilla/dist/bin/js -e 'disfile(" +
      '"-l", "-r", "' + file + '")\' > ' + outFile.path);
  let dbg = Components.utils.getJSTestingFunctions();
  let lines = loadFileToString(outFile).split('\n');
  outFile.remove(false);
  libc.close();

  // Process the data. We're mostly interested in the line numbers of each
  // opcode
  let ignoreData = true;
  for (let line of lines) {
    if (ignoreData) {
      // Opcode 0
      if (line.substring(0,6) == '00000:')
        ignoreData = false;
      else
        continue;
    }
    // Ignore source notes
    if (line.substring(0, 6) == "Source") {
      ignoreData = true;
      continue;
    }
    let data = /^0*([0-9]+): *([0-9]+)/.exec(line);
    // No line data
    if (data === null)
      continue;

    // line number is column 2
    var lno = parseInt(data[2]);
    if (!(lno in file_data.lines))
      file_data.lines[lno] = 0;

    // Look for an explicit mention of a function
    let match = /function ([a-zA-Z_$0-9]+)\(/.exec(line);
    if (match !== null) {
      let fname = match[1];
      if (!(fname in file_data.funcs)) {
        file_data.funcs[fname] = {line: lno, count: 0};
      }
    }
  }
}

// pccounts necessarily don't show counts for scripts that aren't run. Load in
// all the files and find functions that weren't run.
for (let file in totals) {
  insert_not_exec(file, totals[file]);
}

// Walk the directory tree to find other files not even loaded (!)
function process_directory(dir, totals) {
  let files = dir.directoryEntries;
  while (files.hasMoreElements()) {
    let file = files.getNext().QueryInterface(Ci.nsIFile);
    if (file.isDirectory())
      process_directory(file, totals);
    else {
      let path = file.isSymlink() ? file.target : file.path;
      // Don't process any file we've already talked
      if (path in totals)
        continue;
      let ext = path.split('.');
      ext = ext[ext.length - 1];
      if (ext != 'js' && ext != 'jsm')
        continue;
      totals[path] = {funcs: {}, lines: {}};
      insert_not_exec(path, totals[path]);
    }
  }
}
for (let i = 2; i < arguments.length; i++) {
  process_directory(FileUtils.File(arguments[i]), totals);
}

// Output in lcov's format
let fout = FileUtils.openFileOutputStream(FileUtils.File(arguments[1]));
function write(str) { fout.write(str, str.length); }
write("TN:\n");
for (let file in totals) {
  write("SF:" + file + "\n");
  for (let func in totals[file].funcs) {
    let data = totals[file].funcs[func];
    write("FN:" + data.line + "," + func + "\n");
    write("FNDA:" + data.count + "," + func + "\n");
  }
  for (let line in totals[file].lines) {
    write("DA:" + line + "," + totals[file].lines[line] + "\n");
  }
  write("end_of_record\n");
}
