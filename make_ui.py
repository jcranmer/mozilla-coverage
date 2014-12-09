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
    o.add_option('-s', '--source-dir', dest="basedir",
        help="Base directory for source code", metavar="DIRECTORY")
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

    print ('Building UI...')
    builder = UiBuilder(cov, opts.outdir, opts.basedir)
    builder.makeStaticOutput()
    builder.makeDynamicOutput()

class UiBuilder(object):
    def __init__(self, covdata, outdir, basedir):
      self.data = covdata
      self.flatdata = self.data.getFlatData()
      self.outdir = outdir
      self.uidir = os.path.dirname(__file__)
      self.basedir = basedir
      self.relsrc = None
      self.tests = ['all']

    def _loadGlobalData(self):
        json_data = self.buildJSONData(self.flatdata)
        # Make the root node be the lowest path where filenames diverge. This
        # generally works, assuming that things like /usr/include/ are removed
        # from the coverage files before hand.
        self.relsrc = ''
        while len(json_data["files"]) == 1 and len(json_data["files"][0]["files"]):
            json_data = json_data["files"][0]
            if 'name' in json_data:
                self.relsrc += '/' + json_data['name']
        self.relsrc = self.relsrc.replace('//', '/')
        if self.basedir is None:
            self.basedir = self.relsrc
        return json_data

    def buildJSONData(self, data):
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
        #linehit, linecount = reduce(lambda x, y: (x[0] + 1, x[1] + (y[1] != 0)),
        #    data[filename].lines(), (0, 0))
        for lno, lc in data[filename].lines():
            linehit += lc > 0
            linecount += 1
        for fname, _, fc in data[filename].functions():
            fnhit += fc > 0
            fncount += 1
        for _, _, _, brinfo in data[filename].branches():
          brcount += len(brinfo)
          brhit += sum(k != 0 for k in brinfo)
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

      if self.relsrc is not None:
        for part in self.relsrc.split('/'):
          json_data = json_data['files'][0]
      return json_data

    def makeStaticOutput(self):
      staticdir = os.path.join(self.uidir, "webui")
      for static in os.listdir(staticdir):
        shutil.copy2(os.path.join(staticdir, static),
                     os.path.join(self.outdir, static))

    def makeDynamicOutput(self):
        # Dump out JSON files
        json_data = self._loadGlobalData()
        json.dump(json_data, open(os.path.join(self.outdir, 'all.json'), 'w'))
        for test in self.data.getTests():
            small_data = self.data.getTestData(test)
            if len(small_data) == 0:
                continue
            self.tests.append(test)
            test_data = self.buildJSONData(small_data)
            json.dump(test_data,
                open(os.path.join(self.outdir, test + '.json'), 'w'))
        self.tests.sort()
        covtemp = self._readTemplate("coverage.html")
        with open(os.path.join(self.outdir, "coverage.html"), 'w') as fd:
            fd.write(covtemp.substitute({'tests':
                '\n'.join(('<option>%s</option>' % t) for t in self.tests)}))
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
      parameters['testoptions'] = '\n'.join(
        ('<option>%s</option>' % test) for test in self.tests)
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
        parameters['testoptions'] = '\n'.join(
           '<option>%s</option>' % s for s in self.tests)
        from datetime import date
        parameters['date'] = date.today().isoformat()

        # Read the input file
        srcfile = os.path.join(self.basedir, dirname, filename)
        filekey = os.path.join(self.relsrc, dirname, filename)
        if not os.path.exists(srcfile):
            parameters['tbody'] = (
                '<tr><td colspan="5">File could not be found</td></tr>')
            parameters['data'] = ''
        else:
            with open(srcfile, 'r') as fd:
                srclines = fd.readlines()

            flatdata = self.flatdata[filekey]
            del self.flatdata[filekey] # Scavenge memory we don't need anymore.
            alldata = self._buildFileJson(flatdata)
            outdata = {'all': alldata}
            for test in self.tests[1:]:
                outdata[test] = self._buildFileJson(
                    self.data.getFileData(filekey, test))
            parameters['data'] = '''var data=%s;''' % json.dumps(outdata)
            # Precompute branch data for each line.
            brlinedata = {}
            for line in range(len(alldata['lines'])):
                data = alldata['bcounts'][line]
                entries = []
                for branch, tdata in data.items():
                    tentries = ['<span class="%s" title="%d"> %s </span>' % (
                        "highcov" if count > 0 else "lowcov", count,
                        "+" if count > 0 else "-") for count in tdata]
                    tentries[0] = ('<span data-branchid="%d">[' % branch +
                        tentries[0])
                    tentries[-1] += ']</span>'
                    entries.extend(tentries)
                # Insert breaks every 8 values to make particularly long strings
                # not overflow the browser viewport
                for i in range(7, len(entries) - 1, 8):
                    entries[i] += '<br>'
                brlinedata[alldata['lines'][line]] = ''.join(entries)

            lineno = 1
            outlines = []
            linehitdata = dict(flatdata.lines())
            for line in srclines:
                covstatus = ''
                linecount = ''
                if lineno in linehitdata:
                    linecount = str(linehitdata[lineno])
                    iscov = linecount != '0'
                    covstatus = ' class="highcov"' if iscov else ' class="lowcov"'
                brcount = brlinedata.get(lineno, '')
                outlines.append(('  <tr%s><td>%d</td>' +
                    '<td>%s</td><td>%s</td><td>%s</td></tr>\n'
                    ) % (covstatus, lineno, brcount, linecount,
                        cgi.escape(line.rstrip())))
                lineno += 1
            parameters['tbody'] = ''.join(outlines)

        outputdir = os.path.join(self.outdir, dirname)
        if not os.path.exists(outputdir):
            os.makedirs(outputdir)
        with open(os.path.join(outputdir, filename + '.html'), 'w') as fd:
            fd.write(htmltmp.substitute(parameters))

    def _buildFileJson(self, data):
        lines, counts = zip(*data.lines())
        brdata = list(data.branches())
        brdata.sort()
        brlinedata = {}
        for line, branchid, ids, counts in brdata:
            brlinedata.setdefault(line, {})[branchid] = counts
        flat = [brlinedata.get(l, {}) for l in lines]
        return {'lines': lines, 'lcounts': counts, 'bcounts': flat}

if __name__ == '__main__':
  main(sys.argv)
