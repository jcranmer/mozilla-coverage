#!/usr/bin/python

import sys, json
from ccov import CoverageData

def main():
  if len(sys.argv) != 3:
    print "Usage: %s in.info out.json" % sys.argv[0]
    sys.exit(1)
  cov = CoverageData()
  cov.addFromLcovFile(open(sys.argv[1]))
  json_data = build_json_data(cov.getFlatData())

  json.dump(json_data, open(sys.argv[2], 'w'))

def build_json_data(data):
  # The output format is a tree structure, where each node looks like:
  # { lines: <number of lines in the file/directory>,
  #   lines-hit: <number of lines that have a count > 0 in file/directory>,
  #   funcs: <number of functions in the file/directory>,
  #   funcs-hit: <number of functions that have a count > 0 in file/directory>,
  #   files: [ list of children of this node ],
  #   name: "local name of the file, not the full path"
  # }
  default_dict = {"lines": 0, "lines-hit": 0, "funcs": 0, "funcs-hit": 0, "files": []}
  json_data = dict(default_dict)
  for filename in data:
    parts = filename.split('/')
    linehit, linecount = 0, 0
    fnhit, fncount = 0, 0
    if "lines" in data[filename]:
      linehit += len([k for k in data[filename]["lines"] if data[filename]["lines"][k] != 0])
      linecount += len(data[filename]["lines"])
    if "funcs" in data[filename]:
      fnhit += len([k for k in data[filename]["funcs"] if data[filename]["funcs"][k][1] != 0])
      fncount += len(data[filename]["funcs"])
    blob = json_data
    for component in parts:
      blob["lines"] += linecount
      blob["lines-hit"] += linehit
      blob["funcs"] += fncount
      blob["funcs-hit"] += fnhit
      for f in blob["files"]:
        if f["name"] == component:
          blob = f
          break
      else:
        blob["files"].append(default_dict.copy())
        blob = blob["files"][-1]
        blob["name"] = component
        blob["files"] = []
    blob["lines"] += linecount
    blob["lines-hit"] += linehit
    blob["funcs"] += fncount
    blob["funcs-hit"] += fnhit

  # Make the root node be the lowest path where filenames diverge. This
  # generally works, assuming that things like /usr/include/ are removed from
  # the coverage files before hand.
  while len(json_data["files"]) == 1:
    json_data = json_data["files"][0]
  return json_data

if __name__ == '__main__':
  main()
