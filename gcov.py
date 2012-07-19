#!/usr/bin/python

import io
import struct
import sys

def read_struct(fmt, f):
  return struct.unpack(fmt, f.read(struct.calcsize(fmt)))

def read_string(f):
  fmt = '=%ds' % (read_struct('=I', f)[0] * 4)
  return read_struct(fmt, f)[0].strip('\x00')

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

def read_gcno_tag(f, data, curfn):
  if curfn:
    fndata = data['funcs'][curfn]
  tag, length = read_struct('=II', f)
  if tag == 0x01000000: # GCOV_FUNCTION
    ident, checksum = read_struct('=II', f)
    # GCC 4.7 added a second checksum
    if data['version'] > '407 ':
      read_struct('=I', f)
    name = read_string(f)
    source = read_string(f)
    line = read_struct('=I', f)[0]
    data['funcs'][ident] = { "file": source, "line": line, "bbs": [],
      "name": name}
    return ident
  elif tag == 0x01410000: # GCOV_BLOCKS
    flags = read_struct('=%dI' % length, f)
    fndata['bbs'] = [{'flags': flag, 'next': [], 'lines': []} for flag in flags]
  elif tag == 0x01430000: # GCOV_ARCS
    bno = read_struct('=I', f)[0]
    narcs = (length - 1) / 2
    # Data is (destination, flags, counts)
    arcs = [read_struct('=II', f) for i in range(narcs)]
    # Add on counts
    fndata['bbs'][bno]['next'] = [[arc[0], arc[1], 0] for arc in arcs]
  elif tag == 0x01450000: # GCOV_LINES
    ldata = fndata['bbs'][read_struct('=I', f)[0]]['lines']
    curfile = ''
    while True:
      lineno = read_struct('=I', f)[0]
      if lineno == 0:
        curfile = read_string(f)
      else:
        ldata.append((curfile, lineno))
      if curfile == '':
        break
  elif length != 0:
    raise Exception("Unknown tag %x" % tag)
  return curfn

def read_gcno_file(f):
  # Initial prolog stamp
  magic, version, stamp = read_struct('=III', f)
  if magic != 0x67636e6f: # gcno, as a hex integer
    raise Exception("Unknown magic: %x" % magic)
  version = ''.join(chr((version >> shift) & 0xff) for shift in [24, 16, 8, 0])
  stamp = ''.join(chr((stamp >> shift) & 0xff) for shift in [24, 16, 8, 0])
  # What's the stamp about? I don't know...
  tldata = {'funcs': {}, 'version': version, 'stamp': stamp}
  curfn = ''

  # There has got to be an easier way to tell if we're at eof...
  pos = f.tell()
  f.seek(0, 2)
  eof = f.tell()
  f.seek(pos)
  while f.tell() != eof:
    curfn = read_gcno_tag(f, tldata, curfn)
  f.close()
  return tldata

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
        # Flag 1 << 0 is "on_tree"; not having this means the counter doesn't
        # count
        if arc[1] & 1 == 1:
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
      data[f] = {'lines': {}, 'funcs': {}, 'branches': {}}
    return data[f]
  for fn in gcnodata['funcs']:
    fndata = gcnodata['funcs'][fn]
    fnhc = [fndata['line'], 0]
    get_file_data(data, fndata['file'])['funcs'][fndata['name']] = fnhc

    # Count up in/out for each block
    blkin = [0] * len(fndata['bbs'])
    blkout = [0] * len(fndata['bbs'])
    for blkno in range(len(fndata['bbs'])):
      bb = fndata['bbs'][blkno]
      for arc in bb['next']:
        blkout[blkno] += arc[2]
        blkin[arc[0]] += arc[2]
      # Branch data: for every bb that has two or more branch points, compute
      # each arc as a separate branch-data node
      if len(bb['next']) > 1 and len(bb['lines']) > 0:
        brfile, brline = bb['lines'][-1]
        branchdata = get_file_data(data, brfile)['branches']
        brdata = branchdata.setdefault((brline, blkno), {})
        for x in range(len(bb['next'])):
          brdata[x] = brdata.get(x, 0) + bb['next'][x][2]
    # Function hit count == blkout for block 0
    fnhc[1] = blkout[0]

    # Convert block counts to line counts
    # XXX: This is an overestimate. Consider a line like if (a || b); this
    # produces two distinct basic blocks on the same line, and we'd double-count
    # the execution of b.
    for blkno in range(len(fndata['bbs'])):
      bb = fndata['bbs'][blkno]
      blockhit = blkout[blkno]
      for line in bb['lines']:
        linedata = get_file_data(data, line[0])['lines']
        linedata[line[1]] = linedata.get(line[1], 0) + blockhit
  return data

if __name__ == '__main__':
  gcno = io.open(sys.argv[1], 'rb')
  gcnodata = read_gcno_file(gcno)
  add_gcda_counts(io.open(sys.argv[1][:-2] + "da", "rb"), gcnodata)
  data = make_coverage_json(gcnodata)
  print data
