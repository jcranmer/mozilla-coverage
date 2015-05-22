#!/usr/bin/python

import ccov
import io
import struct
import sys

GCOV_TAGS = dict()
def tag_number(index):
    def ret_func(fn):
        GCOV_TAGS[index] = fn
        return fn
    return ret_func

def read_struct(fmt, f):
  return struct.unpack(fmt, f.read(struct.calcsize(fmt)))

def read_string(f):
  fmt = '=%ds' % (read_struct('=I', f)[0] * 4)
  return read_struct(fmt, f)[0].strip('\x00')

class BasicBlockData(object):
    def __init__(self):
        self._line_table = dict()
        self._targets = []
        self._counts = []

    def get_line_table(self):
        '''Return a dictionary of filename -> array-of-line-numbers representing
        the lines within this basic block.'''
        return self._line_table

    def get_lines(self):
        '''Return an iterator of (filename, line number) tuples.'''
        for filename, linearray in self._line_table.iteritems():
            for line in linearray:
                yield (filename, line)

    def set_line_table(self, filelinelist):
        '''Set the list of lines within this basic block by passing in a list of
        (filename, line number) tuples.'''
        self._line_table = dict()
        for file, line in filelinelist:
            self._line_table.setdefault(file, []).append(line)
        for value in self._line_table.itervalues():
            value.sort()

    def set_targets(self, targetlist):
        self._targets = targetlist
        self._counts = [0] * len(self._targets)

    def get_targets(self):
        '''Return an iterator that yield (target block #, flags, count) tuples
        for destinations in this basic block.'''
        for target, count in zip(self._targets, self._counts):
            yield target[0], target[1], count

class FunctionData(object):
    def __init__(self, name, filename, lineno):
        self.name = name
        self.location = (filename, lineno)
        self._bbs = []

    def set_num_blocks(self, num):
        self._bbs = [BasicBlockData() for x in range(num)]

    def get_block(self, index):
        return self._bbs[index]

    def get_blocks(self):
        return iter(self._bbs)

    def __str__(self):
        return '%s at %s:%d' % (self.name, self.location[0], self.location[1])

class GcnoData(object):
    def __init__(self):
        self.version = None
        self.stamp = None
        self._functions = dict()

    def read_gcno_file(self, filename):
        with open(filename, 'rb') as fd:
            self._read_tagged_file(fd, 0x67636e6f)
        self.notes = self.notesdata()

    def _read_int(self, data):
        return struct.unpack('=I', data[:4])[0], data[4:]

    def _read_string(self, data):
        length, data = self._read_int(data)
        length *= 4
        return data[:length].strip('\x00'), data[length:]

    def _read_tagged_file(self, fd, expected):
        # The header is a sequence of 3 int32 values
        magic, version, stamp = read_struct('=III', fd)
        if magic != expected:
            raise Exception("Incorrect magic number, found %x, expected %x" %
                (magic, expected))
        # Convert the version and stamp into strings.
        version = ''.join(chr((version >> shift) & 0xff) for shift in
            [24, 16, 8, 0])
        stamp = ''.join(chr((stamp >> shift) & 0xff) for shift in
            [24, 16, 8, 0])
        if self.version is None:
            self.version = version
        elif version != self.version:
            raise Exception("Version numbers differ, found %s, expected %s" %
                (version, self.version))
        if self.stamp is None:
            self.stamp = stamp
        elif stamp != self.stamp:
            raise Exception("Version stamps differ, found %s, expected %s" %
                (stamp, self.stamp))

        # Try to read all the records
        pos = fd.tell()
        fd.seek(0, 2)
        eof = fd.tell()
        fd.seek(pos)
        parent_record = None
        while fd.tell() != eof:
            parent_record = self._read_record(fd, parent_record)
        fd.seek(pos, 0)

    def _read_record(self, fd, parent_record):
        tag, length = read_struct('=II', fd)
        data = fd.read(length * 4)
        # Records are hierarchial. A top-level record only uses the top octet,
        # and its children use the next octet, etc. In practice, only two levels
        # are used, so we design this method to only support the two levels
        usesParent = bool(tag & 0x00ff0000)
        if tag in GCOV_TAGS:
            if usesParent:
                record = GCOV_TAGS[tag](self, data, parent_record)
            else:
                record = GCOV_TAGS[tag](self, data)
        else:
            print >>sys.stderr, "Ignoring tag %x" % tag
            record = None

        if usesParent:
            return parent_record
        else:
            return record

    @tag_number(0x01000000)
    def _read_function(self, data):
        ident, data = self._read_int(data)
        checksum, data = self._read_int(data)
        # GCC 4.7 added a second checksum
        if self.version > '407 ':
            _, data = self._read_int(data)
        name, data = self._read_string(data)
        source, data = self._read_string(data)
        line, data = self._read_int(data)
        fdata = FunctionData(name, source, line)
        self._functions[ident] = fdata
        return fdata

    @tag_number(0x01410000)
    def _read_basic_block(self, data, fndata):
        flags = []
        while len(data) > 0:
            flag, data = self._read_int(data)
            flags.append(flag)
        fndata.set_num_blocks(len(flags))
        # XXX do something with flags

    @tag_number(0x01430000)
    def _read_arc(self, data, fndata):
        source, data = self._read_int(data)
        targets = []
        while len(data) > 0:
            target, data = self._read_int(data)
            flags, data = self._read_int(data)
            targets.append((target, flags))
        fndata.get_block(source).set_targets(targets)

    @tag_number(0x01450000)
    def _read_line(self, data, fndata):
        bb, data = self._read_int(data)
        lines = []
        filename = ''
        while len(data) > 0:
            lineno, data = self._read_int(data)
            if lineno == 0:
                filename, data = self._read_string(data)
                continue
            lines.append((filename, lineno))
        bbdata = fndata.get_block(bb)
        bbdata.set_line_table(lines)

    def notesdata(self):
        tldata = {'version': self.version, 'stamp': '', 'funcs': dict()}
        for fid, fdata in self._functions.iteritems():
            tlfdata = {
                'file': fdata.location[0],
                'line': fdata.location[1],
                'name': fdata.name,
                'bbs': []
            }
            tldata['funcs'][fid] = tlfdata
            for bb in fdata.get_blocks():
                bbdata = {
                    'lines': list(bb.get_lines()),
                    'flags': 0,
                    'next': [list(t) for t in bb.get_targets()]
                }
                tlfdata['bbs'].append(bbdata)
        return tldata

# How to understand our accumulated gcno data:
# { 'version': the version stamp from the .gcno as a 4-char string,
#   'funcs': [ uniqueID -> {
#      'file': source path
#      'line': source line
#      'name': function name
#      'bbs': [list of {
#        'flags': flag data from gcov
#        'next': [ (dest block #idx, flags, count) ],
#        'lines': [ list of line nos in block ]
#      }]
#   }]
# }

# Arc flags
COMPUTED_COUNT = 1 << 0
FAKE_ARC = 1 << 1

def read_gcda_tag(f, data, curfn):
  if curfn:
    fndata = data['funcs'][curfn]
  # If we h
  tag = read_struct('=I', f)[0]
  if tag == 0:
    return
  length = read_struct('=I', f)[0]
  if tag == 0x01000000: # GCOV_FUNCTION
    ident, checksum = read_struct('=II', f)
    if data['stamp'] == 'LLVM':
      # LLVM adds in these extra two fields, but doesn't use them
      read_struct('=I', f)
      read_string(f)
    # GCC 4.7 added a second checksum
    elif data['version'] > '407 ':
      read_struct('=I', f)
    fndata = data['funcs'][ident]
    return ident
  elif tag == 0x01a10000: # GCOV_COUNTER_ARCS
    count_num = 0
    for bb in fndata['bbs']:
      for arc in bb['next']:
        if arc[1] & COMPUTED_COUNT:
          continue
        lo, hi = read_struct('=II', f)
        arc[2] += lo | hi << 32
        count_num += 1
    assert length / 2 == count_num
  elif (tag == 0xa1000000 or # GCOV_OBJECT_SUMMARY
       tag == 0xa3000000): # GCOV_PROGRAM_SUMMARY
    # I don't know what's going on here, so I'm ignoring it
    f.seek(length * 4, 1)
    #data = read_struct('=%dI' % length, f)
  else:
    raise Exception("Unknown tag %x" % tag)
  return curfn

def add_gcda_counts(f, gcnodata):
  # Initial prolog data
  magic, version, stamp = read_struct('=III', f)
  if magic != 0x67636461: # gcda, as an integer
    raise Exception("Unknown magic: %x" % magic)
  # What's the stamp about? I don't know...
  curfn = 0

  # There has got to be an easier way to tell if we're at eof...
  pos = f.tell()
  f.seek(0, 2)
  eof = f.tell()
  f.seek(pos)
  while f.tell() != eof:
    curfn = read_gcda_tag(f, gcnodata, curfn)
  f.close()

import os

def make_coverage_json(gcnodata, data={}, basedir=''):
  def get_file_data(data, f):
    if f[0] == '.':
      f = os.path.normpath(os.path.join(basedir, f))
    f = os.path.realpath(f)
    if f not in data:
      data[f] = ccov.FileCoverageDetails()
    return data[f]
  for fn in gcnodata['funcs']:
    fndata = gcnodata['funcs'][fn]

    # Count up in/out for each block
    bbdata = fndata['bbs']
    solve_computed_counts(bbdata)
    blkin = [0] * len(bbdata)
    blkout = [0] * len(bbdata)
    for blkno in range(len(bbdata)):
      bb = bbdata[blkno]
      for arc in bb['next']:
        blkout[blkno] += arc[2]
        blkin[arc[0]] += arc[2]
      # Branch data: for every bb that has two or more branch points, compute
      # each arc as a separate branch-data node
      succs = [arc for arc in bb['next'] if not(arc[1] & FAKE_ARC)]
      if len(succs) > 1 and len(bb['lines']) > 0:
        brfile, brline = bb['lines'][-1]
        filedata = get_file_data(data, brfile)
        for x in range(len(bb['next'])):
          if bb['next'][x][1] & FAKE_ARC:
            continue
          filedata.add_branch_hit(brline, blkno, x, bb['next'][x][2])
    # Function hit count == blkout for block 0
    get_file_data(data, fndata['file']).add_function_hit(
        fndata['name'], blkout[0], fndata['line'])

    # Convert block counts to line counts
    # XXX: This is an overestimate. Consider a line like if (a || b); this
    # produces two distinct basic blocks on the same line, and we'd double-count
    # the execution of b.
    for blkno in range(len(fndata['bbs'])):
      bb = fndata['bbs'][blkno]
      blockhit = blkout[blkno]
      for line in bb['lines']:
        get_file_data(data, line[0]).add_line_hit(line[1], blockhit)
  return data

def solve_computed_counts(bbdata):
  # Phase 1: Add in previous links to the bbdata graph.
  for bb in bbdata:
    bb['prev'] = []
  unsolved = set()
  lineinfo = None
  for blkno in range(len(bbdata)):
    bb = bbdata[blkno]
    for i in range(len(bb['next'])):
      arc = bb['next'][i]
      bbdata[arc[0]]['prev'].append(arc)
      if arc[1] & COMPUTED_COUNT:
        unsolved.add(blkno)
        unsolved.add(arc[0])
    # Apparently we need to fix up gcov's line information? this blows...
    if len(bb['lines']) > 0:
      lineinfo = bb['lines'][-1]
    elif lineinfo is not None:
      bb['lines'] = [lineinfo]

  # Phase 2: Go through the entire graph and try to solve unsolved nodes
  while len(unsolved) > 0:
    notsolved = set()
    for blkno in unsolved:
      node = bbdata[blkno]
      # We can't use the first or last nodes to solve the graph, since there's
      # only one edge
      if len(node['prev']) == 0 or len(node['next']) == 0:
        continue

      # Find the imbalance and number of edges to solve for
      imbalance = 0
      num_unsolved = 0
      for arc in node['prev']:
        imbalance += arc[2]
        num_unsolved += (arc[1] & COMPUTED_COUNT != 0)
      pre_unsolved = num_unsolved
      for arc in node['next']:
        imbalance -= arc[2]
        num_unsolved += (arc[1] & COMPUTED_COUNT != 0)

      # If we have only one unsolved edge, we can solve the balance at this node
      if num_unsolved == 1:
        if pre_unsolved == num_unsolved:
          for arc in node['prev']:
            if arc[1] & COMPUTED_COUNT:
              arc[2] = -imbalance
              arc[1] &= ~COMPUTED_COUNT
        else:
          for arc in node['next']:
            if arc[1] & COMPUTED_COUNT:
              arc[2] = imbalance
              arc[1] &= ~COMPUTED_COUNT
      else:
        notsolved.add(blkno)

    # Are we done with the loop?
    if len(unsolved) == len(notsolved):
      display_bb_graph(bbdata)
      raise Exception("Infinite loop!")
    unsolved = notsolved

# Helper for displaying what these graphs look like
def display_bb_graph(bbdata):
  dotname = os.tmpnam()
  dotf = open(dotname, 'w')
  dotf.write('digraph G {\n')
  for blkno in range(len(bbdata)):
    dotf.write('  %d [label="%d %s"];\n' % (blkno, blkno,
      ','.join(pos[0] + ':' + str(pos[1]) for pos in bbdata[blkno]['lines'])))
    for arc in bbdata[blkno]['next']:
      dotf.write('  %d -> %d [label="%x/%d"];\n' % (
        blkno, arc[0], arc[1], arc[2]))
  dotf.write('}')
  dotf.close()
  os.system('dot -Tpng -o %s.png %s' % (dotname, dotname))
  os.system('display %s.png' % dotname)
  os.unlink(dotname)
  os.unlink(dotname + '.png')
