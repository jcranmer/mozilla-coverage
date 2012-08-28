#!/usr/bin/python

import json
import os
import shutil
import sys
from ccov import CoverageData

def main(argv):
  from optparse import OptionParser
  o = OptionParser()
  o.add_option('-o', '--output', dest="outdir",
      help="Directory to store all HTML files", metavar="DIRECTORY")
  (opts, args) = o.parse_args(argv)
  if opts.outdir is None:
    print "Need to pass in -o!"
    sys.exit(1)

  # Add in all the data
  cov = CoverageData()
  for lcovFile in args[1:]:
    cov.addFromLcovFile(open(lcovFile, 'r'))
  json_data = build_json_data(cov.getFlatData())

  # Make the output directory
  if not os.path.exists(opts.outdir):
    os.makedirs(opts.outdir)

  # Dump out JSON files
  json.dump(json_data, open(os.path.join(opts.outdir, 'all.json'), 'w'))
  copy_static_files(opts.outdir)

def build_json_data(data):
  # The output format is a tree structure, where each node looks like:
  # { lines: <number of lines in the file/directory>,
  #   lines-hit: <number of lines that have a count > 0 in file/directory>,
  #   funcs: <number of functions in the file/directory>,
  #   funcs-hit: <number of functions that have a count > 0 in file/directory>,
  #   branches: <number of branches>,
  #   branches-hit: <number of branches with count > 0>,
  #   files: [ list of children of this node ],
  #   name: "local name of the file, not the full path"
  # }
  default_dict = {"lines": 0, "lines-hit": 0, "funcs": 0, "funcs-hit": 0,
                  "branches": 0, "branches-hit": 0, "files": []}
  json_data = dict(default_dict)
  for filename in data:
    parts = filename.split('/')
    linehit, linecount = 0, 0
    fnhit, fncount = 0, 0
    brhit, brcount = 0, 0
    if "lines" in data[filename]:
      linehit += len([k for k in data[filename]["lines"] if data[filename]["lines"][k] != 0])
      linecount += len(data[filename]["lines"])
    if "funcs" in data[filename]:
      fnhit += len([k for k in data[filename]["funcs"] if data[filename]["funcs"][k][1] != 0])
      fncount += len(data[filename]["funcs"])
    if "branches" in data[filename]:
      brdata = data[filename]["branches"]
      for brinfo in brdata.itervalues():
        brcount += len(brinfo)
        brhit += len([k for k in brinfo if brinfo[k] != 0])
    blob = json_data
    for component in parts:
      blob["lines"] += linecount
      blob["lines-hit"] += linehit
      blob["funcs"] += fncount
      blob["funcs-hit"] += fnhit
      blob["branches"] += brcount
      blob["branches-hit"] += brhit
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
    blob["branches"] += brcount
    blob["branches-hit"] += brhit

  # Make the root node be the lowest path where filenames diverge. This
  # generally works, assuming that things like /usr/include/ are removed from
  # the coverage files before hand.
  while len(json_data["files"]) == 1:
    json_data = json_data["files"][0]
  return json_data

def copy_static_files(output):
  staticdir = os.path.join(os.path.dirname(__file__), "webui")
  for static in os.listdir(staticdir):
    shutil.copy2(os.path.join(staticdir, static), os.path.join(output, static))

if __name__ == '__main__':
  main(sys.argv)
