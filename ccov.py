#!/usr/bin/python

import array
import fnmatch
import re
import shutil
import subprocess
import tempfile

def format_set_difference(a, b):
    if a == b:
        return None
    return "added %s\nremoved %s" % (str(b - a), str(a - b))

class FileCoverageDetails(object):
    '''This class contains detailed information about the file, line, and branch
    coverage within a single file.'''

    __slots__ = ('_lines', '_funcs', '_branches')

    def __init__(self):
        self._lines = array.array('l', [-1] * 1000)
        self._funcs = dict()
        self._branches = dict()

    def add_line_hit(self, line, hitcount):
        '''Note that the line has executed hitcount times.'''
        if line >= len(self._lines):
            self._lines.extend([-1] *
                max(line + 1 - len(self._lines), len(self._lines)))
        if self._lines[line] == -1:
            self._lines[line] = hitcount
        else:
            self._lines[line] += hitcount

    def lines(self):
        '''Returns an iterator over (line #, hit count) for this file.'''
        for i in xrange(len(self._lines)):
            count = self._lines[i]
            if count != -1:
                yield (i, count)

    def add_function_hit(self, name, hitcount, lineno=None):
        '''Note that the function has been executed hitcount times. Optionally,
        if lineno is not None, note the line number of this function.'''
        if not name in self._funcs:
            self._funcs[name] = [lineno, 0]
        fndata = self._funcs[name]
        if lineno is not None:
            fndata[0] = lineno
        fndata[1] += hitcount

    def functions(self):
        '''Returns an iterator over (function name, line #, hit count) for this
        file.'''
        for func, fndata in self._funcs.iteritems():
            yield (func, fndata[0], fndata[1])

    def add_branch_hit(self, lineno, brno, targetid, count):
        '''Note that the brno'th branch on the line number going to the targetid
        basic block has been executed count times.'''
        brdata = self._branches.setdefault((lineno, brno), {})
        brdata[targetid] = brdata.get(targetid, 0) + count

    def branches(self):
        '''Returns an iterator over (line #, branch #, [ids], [counts]) for this
        file.'''
        for tup in self._branches.iteritems():
            items = tup[1].items()
            items.sort()
            yield (tup[0][0], tup[0][1], [x[0] for x in items], [x[1] for x in items])

    def write_lcov_output(self, fd):
        '''Writes the record for this file to the file descriptor in the LCOV
        info file format.'''
        # Write out func data
        fnf, fnh = 0, 0
        for fname, fline, fcount in self.functions():
            fd.write("FN:%d,%s\n" % (fline, fname))
            fd.write("FNDA:%d,%s\n" % (fcount, fname))
            fnf += 1
            fnh += fcount != 0
        fd.write("FNF:%d\n" % fnf)
        fd.write("FNH:%d\n" % fnh)

        # Write out line data
        lh, lf = 0, 0
        for line, hit in self.lines():
            fd.write("DA:%d,%d\n" % (line, hit))
            lf += 1
            lh += hit != 0
        fd.write("LH:%d\n" % lh)
        fd.write("LF:%d\n" % lf)

        # Write out branch data
        brf, brh = 0, 0
        for line, branch, ids, counts in self.branches():
            total = sum(counts)
            for branchno, count in zip(ids, counts):
                fd.write("BRDA:%d,%d,%d,%s\n" % (line, branch, branchno,
                    (total == 0 and '-' or str(count))))
                brf += 1
                brh += count != 0
        fd.write("BRH:%d\n" % brh)
        fd.write("BRF:%d\n" % brf)
        fd.write("end_of_record\n")
        pass

    def check_equivalency(self, otherdata):
        if self._lines != otherdata._lines:
            return "Line counts differ"
        if set(self.functions()) != set(otherdata.functions()):
            return "Function counts differ"
        ourbrs = set((x[0], x[1], tuple(x[2]), tuple(x[3]))
            for x in self.branches())
        theirbrs = set((x[0], x[1], tuple(x[2]), tuple(x[3]))
            for x in otherdata.branches())
        if ourbrs != theirbrs:
            return "Branch counts differ"
        pass

class CoverageData:
  # data is a map of [testname -> fileData]
  # fileData is a map of [file -> FileCoverageDetails]
  def __init__(self):
        self._data = {'': {}}

  def addFromLcovFile(self, fd):
    ''' Adds the data from the given file (in lcov format) to the current
        data tree. '''
    fileData = self._data['']
    # LCOV info files are line-based
    for line in fd:
      line = line.strip()
      instr, data = line.split(':', 1)
      if instr == 'TN': # TN:<test name>
        fileData = self._data.setdefault(data, dict())
        continue
      elif instr == 'SF': # SF:<absolute path to the source file>
        if os.path.islink(data):
          data = os.path.realpath(data)
        CoverageData._addLcovData(fd,
            fileData.setdefault(data, FileCoverageDetails()))
      else:
        raise Exception("Unknown line: %s" % line)
    fd.close()

  @staticmethod
  def _addLcovData(fd, fileStruct):
        # Lines and function count live in dicts
        for line in fd:
            line = line.strip()
            if line == 'end_of_record':
                return
            instr, data = line.split(':', 1)
            if instr == 'DA': # DA:<line number>,<execution count>[,<checksum>]
                data = data.split(',')
                lno, hits = int(data[0]), int(data[1])
                fileStruct.add_line_hit(lno, hits)
            elif instr == 'FNDA': # FNDA:<execution count>,<function name>
                data = data.split(',')
                fileStruct.add_function_hit(data[1], int(data[0]))
            elif instr == 'FN': # FN:<line number of function>,<function name>
                data = data.split(',')
                fileStruct.add_function_hit(data[1], 0, int(data[0]))
            elif instr == 'BRDA': # <line>,<block>,<branch>,<count or ->
                data = [x == '-' and '-' or int(x) for x in data.split(',')]
                if data[3] == '-':
                  data[3] = 0
                fileStruct.add_branch_hit(data[0], data[1], data[2], data[3])
            elif instr in ['LH', 'LF', 'FNF', 'FNH']:
                # Hit/found -> we count these ourselves
                continue
            #else:
            #    raise Exception("Unknown line: %s" % line)

  def writeLcovOutput(self, fd):
    for test in self._data:
      fileData = self._data[test]
      for fname in fileData:
        perFileData = fileData[fname]
        fd.write('TN:%s\n' % test)
        fd.write("SF:%s\n" % fname)
        perFileData.write_lcov_output(fd)
    fd.close()

  def loadGcdaTree(self, testname, gcdaDir):
        import gcov, io
        if not testname in self._data:
            self._data[testname] = dict()
        for dirpath, dirnames, filenames in os.walk(gcdaDir):
            print 'Processing %s' % dirpath
            gcda_files = filter(lambda f: f.endswith('.gcda'), filenames)
            gcno_files = [f[:-2] + 'no' for f in gcda_files]
            filepairs = [(da, no) for (da, no) in zip(gcda_files, gcno_files)
                if no in filenames]
            for gcda, gcno in filepairs:
                gcnodata = gcov.read_gcno_file(io.open(
                    os.path.join(dirpath, gcno), "rb"))
                gcov.add_gcda_counts(io.open(
                    os.path.join(dirpath, gcda), "rb"), gcnodata)
                gcov.make_coverage_json(gcnodata, self._data[testname], dirpath)

  def loadViaGcov(self, testname, dirwalk, gcovtool):
        dirwalk = os.path.abspath(dirwalk)
        iterpaths = []
        for dirpath, dirnames, filenames in os.walk(dirwalk):
            iterpaths.append((dirpath,
                filter(lambda x: x.endswith('.gcda'), filenames)))
        iterpaths = filter(lambda x: x[-1], iterpaths)
        table = self._data.setdefault(testname, {})
        loader = GcovLoader(dirwalk, gcovtool, table=table)
        for directory, gcdas in iterpaths:
            loader.loadDirectory(directory, gcdas)

  def getFlatData(self):
      return self._getFlatData(self.getTests())

  def getFileData(self, file, test):
      data = FileCoverageDetails()
      testdata = self._data[test]
      return testdata.get(file, data)

  def _getFlatData(self, keys):
        data = {}
        for test in keys:
            testdata = self._data[test]
            for file in testdata:
                fdata = data.setdefault(file, FileCoverageDetails())
                tfdata = testdata[file]
                # Merge line data in
                for line, lh in tfdata.lines():
                    fdata.add_line_hit(line, lh)
                # Merge in function data
                for func, line, fh in tfdata.functions():
                    fdata.add_function_hit(func, fh, line)
                # Branch data
                for line, branch, ids, counts in tfdata.branches():
                    for brid, count in zip(ids, counts):
                        fdata.add_branch_hit(line, branch, brid, count)
        return data

  def getTestData(self, test):
        return self._getFlatData([test])

  def getTests(self):
        return self._data.keys()

  def filterFilesByGlob(self, glob):
    newdata = {}
    for test in self._data:
      testdata = self._data[test]
      newtestdata = {}
      for filename in fnmatch.filter(testdata.keys(), glob):
        newtestdata[filename] = testdata[filename]
      if len(newtestdata) > 0:
        newdata[test] = newtestdata
    self._data = newdata

  def checkEquivalency(self, otherData):
        if set(self.getTests()) != set(otherData.getTests()):
            return "Difference in tests"
        for test in self.getTests():
            ourfiles = set(self._data[test].keys())
            theirfiles = set(otherData._data[test].keys())
            diff = format_set_difference(ourfiles, theirfiles)
            if diff:
                return "Difference in files: " + diff
            for f in ourfiles:
                result = self.getFileData(f, test).check_equivalency(
                    otherData.getFileData(f, test))
                if result:
                    return result + " on test " + test
        return None

class GcovLoader(object):
    def __init__(self, basedir, gcovtool='gcov', table={}):
        self.gcovtool = gcovtool
        self.basedir = basedir
        self.table = table

    def loadDirectory(self, directory, gcda_files):
        print 'Processing %s' % directory
        gcda_files = map(lambda f: os.path.join(directory, f), gcda_files)
        gcovdir = tempfile.mktemp("gcovdir")
        os.mkdir(gcovdir)
        with open('/dev/null', 'w') as hideOutput:
            subprocess.check_call([self.gcovtool, "-b", "-c", "-a", "-f"] +
                gcda_files, cwd=gcovdir, stdout=hideOutput, stderr=hideOutput)
        for gcovfile in os.listdir(gcovdir):
            with open(os.path.join(gcovdir, gcovfile)) as fd:
                self._readGcovFile(fd, directory)
        shutil.rmtree(gcovdir)

    def _readGcovFile(self, fd, relpath):
        lineDataRe = re.compile(r"\s*([^:]+):\s*([0-9]+):(.*)$")
        functionDataRe = re.compile("function (.*) called ([0-9]+)")
        branchNoRe = re.compile(r"\s*[^:]+:\s*[0-9]+-block\s+([0-9]+)$")
        brdRe = re.compile(r"branch\s*([0-9]+) (taken ([0-9]+)|never executed)")
        lineno = 0
        branchno = 0
        for line in fd:
            line = line.strip()
            match = lineDataRe.match(line)
            if match is not None:
                count = match.group(1)
                lineno = int(match.group(2))
                data = match.group(3)
                if lineno == 0 and data.startswith('Source:'):
                    # Build the filename
                    filename = data[data.find(':')+1:]
                    filename = os.path.abspath(os.path.join(relpath, filename))
                    # Set the accumulator tables
                    if not filename in self.table:
                        fulltable = FileCoverageDetails()
                        self.table[filename] = fulltable
                    else:
                        fulltable = self.table[filename]
                elif lineno >= 1 and count != '-':
                    if count == '#####':
                        count = 0
                    else:
                        count = int(count)
                    fulltable.add_line_hit(lineno, count)
                continue
            match = functionDataRe.match(line)
            if match is not None:
                func = match.group(1)
                fncount = int(match.group(2))
                fulltable.add_function_hit(func, fncount, lineno + 1)
                continue
            match = branchNoRe.match(line)
            if match is not None:
                branchno = int(match.group(1))
                continue
            match = brdRe.match(line)
            if match is not None:
                brid = int(match.group(1))
                brcount = match.group(3)
                if brcount is None:
                    brcount = 0
                else:
                    brcount = int(brcount)
                fulltable.add_branch_hit(lineno, branchno, brid, brcount)

import os, sys

def main(argv):
  from optparse import OptionParser
  o = OptionParser()
  o.add_option('-a', '--add', dest="more_files", action="append",
      help="Add contents of coverage data", metavar="FILE")
  o.add_option('--experimental-collect', dest="gcda_dirs", action="append",
      help="Collect data from gcov results", metavar="DIR")
  o.add_option('-c', '--gcov-collect', dest="gcov_dirs", action="append",
      help="Collect data from gcov results", metavar="DIR")
  o.add_option('--gcov-tool', dest="gcov_tool", default="gcov",
      help="Version of gcov to use to extract data")
  o.add_option('-e', '--extract', dest="extract_glob",
      help="Extract only data for files matching PATTERN", metavar="PATTERN")
  o.add_option('-o', '--output', dest="outfile",
      help="File to output data to", metavar="FILE")
  o.add_option('-t', '--test-name', dest="testname",
      help="Use the NAME for the name of the test", metavar="NAME")
  (opts, args) = o.parse_args(argv)

  # Load coverage data
  coverage = CoverageData()
  if opts.more_files == None: opts.more_files = []
  for lcovFile in opts.more_files:
      print >> sys.stderr, "Reading file %s" % lcovFile
      fd = open(lcovFile, 'r')
      coverage.addFromLcovFile(fd)

  if opts.gcda_dirs == None: opts.gcda_dirs = []
  test = opts.testname or ''
  for gcdaDir in opts.gcda_dirs:
      coverage.loadGcdaTree(test, gcdaDir)
  for gcovdir in (opts.gcov_dirs or []):
      coverage.loadViaGcov(test, gcovdir, opts.gcov_tool)

  if opts.extract_glob is not None:
    coverage.filterFilesByGlob(opts.extract_glob)
  # Store it to output
  if opts.outfile != None:
    print >> sys.stderr, "Writing to file %s" % opts.outfile
    outfd = open(opts.outfile, 'w')
  else:
    outfd = sys.stdout
  coverage.writeLcovOutput(outfd)
  outfd.close()

if __name__ == '__main__':
  main(sys.argv[1:])
