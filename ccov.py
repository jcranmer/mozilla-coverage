#!/usr/bin/python

class CoverageData:
  # data is a map of [testname -> fileData]
  # fileData is a map of [file -> perFileData]
  # perFileData:
  #  lines: [line# -> line hit count]
  #  funcs: [func name -> [line number, func hit count]]
  _data = {'': {}}
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
        CoverageData._addLcovData(fd, fileData.setdefault(data, {}))
      else:
        raise Exception("Unknown line: %s" % line)
    fd.close()

  @staticmethod
  def _addLcovData(fd, fileStruct):
    # Lines and function count live in dicts
    lines = fileStruct.setdefault('lines', {})
    funcs = fileStruct.setdefault('funcs', {})
    for line in fd:
      line = line.strip()
      if line == 'end_of_record':
        return
      instr, data = line.split(':', 1)
      if instr == 'DA': # DA:<line number>,<execution count>[,<checksum>]
        data = data.split(',')
        lno, hits = int(data[0]), int(data[1])
        lines[lno] = lines.get(lno, 0) + hits
      elif instr == 'FNDA': # FNDA:<execution count>,<function name>
        data = data.split(',')
        funcs.setdefault(data[1], [0, 0])[1] += int(data[0])
      elif instr == 'FN': # FN:<line number of function start>,<function name>
        data = data.split(',')
        funcs.setdefault(data[1], [0, 0])[0] = int(data[0])
      elif instr in ['LH', 'LF', 'FNF', 'FNH']:
        # Hit/found -> we count these ourselves
        continue
      #else:
      #  raise Exception("Unknown line: %s" % line)

  def writeLcovOutput(self, fd):
    for test in self._data:
      fileData = self._data[test]
      for fname in fileData:
        perFileData = fileData[fname]
        fd.write('TN:%s\n' % test)
        fd.write("SF:%s\n" % fname)
        self._writeRecord(fd, perFileData)
    fd.close()

  def _writeRecord(self, fd, perFileData):
    # Write out func data
    fnf, fnh = 0, 0
    for func in perFileData['funcs']:
      fndata = perFileData['funcs'][func]
      fd.write("FN:%d,%s\n" % (fndata[0], func))
      fd.write("FNDA:%d,%s\n" % (fndata[1], func))
      fnf += 1
      fnh += fndata[1] != 0
    fd.write("FNF:%d\n" % fnf)
    fd.write("FNH:%d\n" % fnh)

    # Write out line data
    lh, lf = 0, 0
    for line in perFileData['lines']:
      fd.write("DA:%d,%d\n" % (line, perFileData['lines'][line]))
      lf += 1
      lh += perFileData['lines'][line] != 0
    fd.write("LH:%d\n" % lh)
    fd.write("LF:%d\n" % lf)
    fd.write("end_of_record\n")

  def loadGcdaAndGcno(self, testname, gcdapath, gcnopath):
    import gcov, io
    if not testname in self._data:
      self._data[testname] = dict()
    gcnodata = gcov.read_gcno_file(io.open(gcnopath, "rb"))
    gcov.add_gcda_counts(io.open(gcdapath, "rb"), gcnodata)
    gcov.make_coverage_json(gcnodata, self._data[testname])

import os, sys

def main(argv):
  from optparse import OptionParser
  o = OptionParser()
  o.add_option('-a', '--add', dest="more_files", action="append",
      help="Add contents of coverage data", metavar="FILE")
  o.add_option('-o', '--output', dest="outfile",
      help="File to output data to", metavar="FILE")
  o.add_option('-c', '--collect', dest="gcda_dirs", action="append",
      help="Collect data from gcov results", metavar="DIR")
  o.add_option('-t', '--test-name', dest="testname",
      help="Use the NAME for the name of the test", metavar="NAME")
  (opts, args) = o.parse_args(argv)

  # Load coverage data
  coverage = CoverageData()
  if opts.more_files == None: opts.more_files = []
  for lcovFile in opts.more_files:
    print >> sys.stderr, "Reading file %s" % lcovFile
    try:
      fd = open(lcovFile, 'r')
      coverage.addFromLcovFile(fd)
    except IOError, e:
      print >> sys.stderr, e
    except Exception, e:
      print >> sys.stderr, e

  if opts.gcda_dirs == None: opts.gcda_dirs = []
  test = opts.testname or ''
  for gcdaDir in opts.gcda_dirs:
    for dirpath, dirnames, filenames in os.walk(gcdaDir):
      for f in filenames:
        gcnoname = f[:-2] + 'no'
        path = os.path.join(dirpath, f)
        if f[-5:] == '.gcda' and gcnoname in filenames:
          print >>sys.stderr, "Processing file %s" % path
          coverage.loadGcdaAndGcno(test, path, os.path.join(dirpath, gcnoname))

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
