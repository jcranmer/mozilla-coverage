function displayDirectoryResults(json) {
  var root = json;
  for (var i = 0; i < path.length; i++) {
    var sub = root.files.filter(function (d) { return d.name == path[i] });
    if (sub.length != 1)
      throw new Error("Can't find " + path[i] + " in data!");
    root = sub[0];
  }

  var rows = root.files;
  rows.sort(function (a, b) { return d3.ascending(a.name, b.name); });

  var display = d3.select("#coveredtable > tbody");
  var nodes = display.selectAll("tr").data(rows);

  var cells = nodes.selectAll("td")
    .data(rowConv).filter(function (d, i) { return i > 0; })
    .text(function (d) { return d._text; })
    .attr("class", function (d) { return d._style; });

  var total = d3.selectAll("#coveredtable > tfoot > tr > td")
    .data(rowConv(root)).filter(function (d, i) { return i > 0; })
    .text(function (d) { return d._text; })
    .attr("class", function (d) { return d._style; });
}

function rowConv(d) {
  function array(hit, total) {
    if (total == 0)
      return [{_style: "", _text: "0 / 0"}, {_style: "", _text: "-"}];
    var style = hit / total < 0.75 ? "lowcov" :
                hit / total < 0.90 ? "mediumcov" : "highcov";
    return [{_style: style, _text: hit + " / " + total},
      {_style: style, _text: d3.format(".3p")(hit / total)}];
  }
  return [d].concat(
    array(d["lines-hit"], d["lines"]).concat(
    array(d["funcs-hit"], d["funcs"]).concat(
    array(d["branches-hit"], d["branches"]))));
}

function onDirectoryLoad() {
  d3.select("#testsuite").on("change", function () {
    d3.json(depth + "/" + this.value + ".json", displayDirectoryResults);
  });
}

function convertFileTable(data) {
  var zip = data.lines.map(function (d, i) {
    return [formatBranchData(data.bcounts[i]), data.lcounts[i]];
  });
  var rows = d3.selectAll("#filetable > tbody > tr")
    .filter(".highcov, .lowcov")
    .data(zip);
  rows.attr("class", function (d, i) { return data.lcounts[i] == 0 ? "lowcov"
    : "highcov"; });
  var cells = rows.selectAll("td:nth-child(2), td:nth-child(3)")
    .data(function (d) { return d; });

  cells.html(function (d) { return d; });
}

function formatBranchData(bdata) {
  // Branch data is an array of arrays, each outer array corresponding to a
  // potential branch, and each array containing the counts of the targets
  // within that branch (switches get more than 2 targets).
  var entries = [];
  for (var branch in bdata) {
    var str = "[";
    var tdata = bdata[branch];
    for (var t = 0; t < tdata.length; t++) {
      str += '<span class="';
      str += tdata[t] == 0 ? "lowcov" : "highcov";
      str += '" title="' + tdata[t] + '"> ';
      str += tdata[t] == 0 ? "-" : "+";
      str += " </span>";
      if (t + 1 == tdata.length)
        str += "]";
      entries.push(str);
      str = "";
    }
  }
  // Insert breaks every 8 entries.
  for (var i = 7; i < entries.length - 1; i += 8)
    entries[i] += "<br>";
  return entries.join("");
}

function onFileLoad() {
  d3.select("#testsuite").on("change", function () {
    convertFileTable(data[this.value]);
  });
}
