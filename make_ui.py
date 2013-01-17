#!/usr/bin/python

import cgi
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

  # Make the output directory
  if not os.path.exists(opts.outdir):
    os.makedirs(opts.outdir)

  builder = UiBuilder(cov, opts.outdir)
  builder.makeStaticOutput()
  builder.makeDynamicOutput()

class UiBuilder(object):
  def __init__(self, covdata, outdir):
    self.data = covdata
    self.flatdata = self.data.getFlatData()
    self.outdir = outdir
    self.uidir = os.path.dirname(__file__)

  def buildJSONData(self):
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
    data = self.flatdata
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
    self.relsrc = ''
    while len(json_data["files"]) == 1:
      json_data = json_data["files"][0]
      if 'name' in json_data:
        self.relsrc += '/' + json_data['name']
    self.relsrc = self.relsrc.replace('//', '/')
    return json_data

  def makeStaticOutput(self):
    staticdir = os.path.join(self.uidir, "webui")
    for static in os.listdir(staticdir):
      shutil.copy2(os.path.join(staticdir, static),
                   os.path.join(self.outdir, static))

  def makeDynamicOutput(self):
    # Dump out JSON files
    json_data = self.buildJSONData()
    json.dump(json_data, open(os.path.join(self.outdir, 'all.json'), 'w'))
    self._makeDirectoryIndex('', json_data)

  def _readTemplate(self, name):
    from string import Template
    templatefile = os.path.join(self.uidir, "uitemplates", name)
    fd = open(templatefile, 'r')
    try:
      template = fd.read()
    finally:
      fd.close()
    return Template(template)

  def _makeDirectoryIndex(self, dirname, jsondata):
    # Utility method for printing out rows of the table
    def summary_string(lhs, jsondata):
      output = '<tr>'
      output += '<td>%s</td>' % lhs
      for piece in ['lines', 'funcs', 'branches']:
        hit = jsondata[piece + '-hit']
        count = jsondata[piece]
        if count == 0:
          output += '<td>0 / 0</td><td>-</td>'
        else:
          ratio = 100.0 * hit / count
          if ratio < 75.0: clazz = "lowcov"
          elif ratio < 90.0: clazz = "mediumcov"
          else: clazz = "highcov"
          output += '<td class="%s">%d / %d</td><td class="%s">%.1f%%</td>' % (
            clazz, hit, count, clazz, ratio)
      return output + '</tr>'
    htmltmp = self._readTemplate('directory.html')

    jsondata['files'].sort(lambda x, y: cmp(x['name'], y['name']))

    # Parameters for output
    parameters = {}
    parameters['directory'] = dirname
    if dirname:
      parameters['depth'] = '/'.join('..' for x in dirname.split('/'))
    else:
      parameters['depth'] = '.'
    parameters['testoptions'] = '<option>all</option>' # XXX Add more test data
    from datetime import date
    parameters['date'] = date.today().isoformat()

    def htmlname(json):
      if len(json['files']) > 0:
        return json['name']
      else:
        return json['name'] + '.html'
    tablestr = '\n'.join(summary_string(
      '<a href="%s">%s</a>' % (htmlname(child), child['name']), child)
                         for child in jsondata['files'])
    parameters['tbody'] = tablestr
    parameters['tfoot'] = summary_string('Total', jsondata)

    outputdir = os.path.join(self.outdir, dirname)
    if not os.path.exists(outputdir):
      os.makedirs(outputdir)
    fd = open(os.path.join(outputdir, 'index.html'), 'w')
    try:
      fd.write(htmltmp.substitute(parameters))
    finally:
      fd.close()

    # Recursively build for all files in the directory
    for child in jsondata['files']:
      if len(child['files']) > 0:
        self._makeDirectoryIndex(os.path.join(dirname, child['name']), child)
      else:
        self._makeFileData(dirname, child['name'], child)

  def _makeFileData(self, dirname, filename, jsondata):
    print 'Writing %s/%s.html' % (dirname, filename)
    htmltmp = self._readTemplate('file.html')

    parameters = {}
    parameters['file'] = os.path.join(dirname, filename)
    parameters['directory'] = dirname
    parameters['depth'] = '/'.join('..' for x in dirname.split('/'))
    parameters['testoptions'] = '<option>all</option>' # XXX Add more test data
    from datetime import date
    parameters['date'] = date.today().isoformat()

    # Read the input file
    srcfile = os.path.join(self.relsrc, dirname, filename)
    if not os.path.exists(srcfile):
      parameters['tbody'] = '<tr><td colspan="5">File could not be found</td></tr>'
    else:
      fd = open(os.path.join(self.relsrc, dirname, filename), 'r')
      try:
        srclines = fd.readlines()
      finally:
        fd.close()

      lineno = 1
      outlines = []
      flatdata = self.flatdata[srcfile]
      for line in srclines:
        covstatus = ''
        linecount = ''
        if lineno in flatdata['lines']:
          linecount = str(flatdata['lines'][lineno])
          iscov = linecount != '0'
          covstatus = ' class="highcov"' if iscov else ' class="lowcov"'
        outlines.append(('  <tr%s><td>%d</td>' +
          '<td></td><td>%s</td><td>%s</td></tr>\n'
          ) % (covstatus, lineno, linecount, cgi.escape(line.rstrip())))
        lineno += 1
      parameters['tbody'] = ''.join(outlines)

    outputdir = os.path.join(self.outdir, dirname)
    if not os.path.exists(outputdir):
      os.makedirs(outputdir)
    fd = open(os.path.join(outputdir, filename + '.html'), 'w')
    try:
      fd.write(htmltmp.substitute(parameters))
    finally:
      fd.close()


if __name__ == '__main__':
  main(sys.argv)
