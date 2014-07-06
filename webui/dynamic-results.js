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
