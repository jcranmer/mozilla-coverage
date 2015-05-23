#!/usr/bin/python

import os
import struct
import sys

GCOV_TAGS = dict()
def tag_number(index):
    def ret_func(fn):
        GCOV_TAGS[index] = fn
        return fn
    return ret_func

# Arc flags
COMPUTED_COUNT = 1 << 0
FAKE_ARC = 1 << 1
FALLTHROUGH = 1 << 2
# Not-gcov arc flags
UNCONDITIONAL = 1 << 32
CALL_NON_RETURN = 1 << 33

def read_struct(fmt, f):
  return struct.unpack(fmt, f.read(struct.calcsize(fmt)))

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

    def add_count(self, arc, count):
        '''Add the number of executions to a specific destination counter.'''
        self._counts[arc] += count

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

    def get_gcda_count_indices(self):
        '''Return an iterator over (basicblock data, arc index) for the counters
        in this function. Not all arcs in the graph are recorded as actual
        counters, and this function lets the gcda reader work out how to map
        counters to the actual target values.'''
        for bb in self.get_blocks():
            for i in range(len(bb._targets)):
                if not (bb._targets[i][1] & COMPUTED_COUNT):
                    yield bb, i

    def __str__(self):
        return '%s at %s:%d' % (self.name, self.location[0], self.location[1])

class GcnoData(object):
    def __init__(self):
        self.version = None
        self.stamp = None
        self._functions = dict()

    def add_to_coverage(self, covdata, testname, basepath):
        def get_file_data(f):
            if not os.path.isabs(f):
                f = os.path.normpath(os.path.join(basepath, f))
            f = os.path.realpath(f)
            return covdata.get_or_add_file(f, testname)

        for function in self._functions.itervalues():
            rich_bb_graph = build_solver_graph(function)
            solve_arc_counts(rich_bb_graph)
            line_map = build_line_map(rich_bb_graph)
            add_coverage_data(line_map, get_file_data)
            get_file_data(function.location[0]).add_function_hit(
                function.name, rich_bb_graph[0].count, function.location[1])

    def read_gcno_file(self, filename):
        with open(filename, 'rb') as fd:
            self._read_tagged_file(fd, 0x67636e6f)

    def read_gcda_file(self, filename):
        with open(filename, 'rb') as fd:
            self._read_tagged_file(fd, 0x67636461)
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
        # For GCDA files, there's an extraneous null byte at the end. Ignore
        # that one.
        try:
            tag, length = read_struct('=II', fd)
        except:
            return
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
        if len(data) == 0:
            # This is the .gcda version of this function, which is lacking the
            # name/source/line part. Since we load the notes file first, the
            # function should already be present.
            fdata = self._functions[ident]
        else:
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

    @tag_number(0x01a10000)
    def _read_counters(self, data, fndata):
        for bb, arc in fndata.get_gcda_count_indices():
            countlo, data = self._read_int(data)
            counthi, data = self._read_int(data)
            count = countlo | (counthi << 32)
            bb.add_count(arc, count)
        assert len(data) == 0

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

class SolverBasicBlock(object):
    def __init__(self, blockno, bbdata):
        self.blockno = blockno
        self.bbdata = bbdata
        self.in_arcs = []
        self.out_arcs = []
        self.count = -1
        self.is_call_return = False

    def get_count(self):
        '''Return the execution count of this block. If it is not yet known, the
        value -1 is returned instead.'''
        if self.count >= 0:
            return self.count
        if self.in_arcs:
            count = sum(arc.count for arc in self.in_arcs)
            if count == count:
                self.count = count
                return count
        if self.out_arcs:
            count = sum(arc.count for arc in self.out_arcs)
            if count == count:
                self.count = count
                return count
        return -1

    def __repr__(self):
        return "BasicBlock[%d]" % self.blockno

class Arc(object):
    def __init__(self, source, target, flags, count):
        self.source = source
        self.target = target
        self.flags = flags
        self.count = float('NaN') if self.is_computed else count

    @property
    def is_fake(self):
        return bool(self.flags & FAKE_ARC)

    @property
    def is_computed(self):
        return bool(self.flags & COMPUTED_COUNT)

    @property
    def fall_through(self):
        return bool(self.flags & FALLTHROUGH)

    @property
    def is_unconditional(self):
        return bool(self.flags & UNCONDITIONAL)

    @property
    def is_call_non_return(self):
        return bool(self.flags & CALL_NON_RETURN)

    def solve_count(self):
        assert self.count != self.count
        if self.source.count != -1:
            count = self.source.count - sum(
                arc.count for arc in self.source.out_arcs if arc != self)
            if count == count:
                self.count = count
                assert sum(arc.count for arc in self.source.out_arcs) == self.source.count
                return self.target
        if self.target.count != -1:
            count = self.target.count - sum(
                arc.count for arc in self.target.in_arcs if arc != self)
            if count == count:
                self.count = count
                assert sum(arc.count for arc in self.target.in_arcs) == self.target.count
                return self.source
        return False

    def __repr__(self):
        return "Arc(%d->%d:%s)" % (self.source.blockno,
                self.target.blockno,
                str(self.count))

def build_solver_graph(fndata):
    # Build the rich nodes
    newbbs = [SolverBasicBlock(i, fndata.get_block(i)) for i in
        range(len(fndata._bbs))]
    # Add the targets to each of those nodes as arcs
    for bb in newbbs:
        num_fake = 0
        for target, flags, count in bb.bbdata.get_targets():
            arc = Arc(bb, newbbs[target], flags, count)
            bb.out_arcs.append(arc)
            newbbs[target].in_arcs.append(arc)
            num_fake += arc.is_fake
            if arc.is_fake and bb.blockno != 0:
                arc.flags |= CALL_NON_RETURN

        # This helps sort out which blocks to omit when using branchdata output.
        if len(bb.out_arcs) - num_fake == 1:
            for arc in filter(lambda a: not a.is_fake, bb.out_arcs):
                arc.flags |= UNCONDITIONAL
                if num_fake > 0 and bb.blockno != 0:
                    if arc.fall_through and len(arc.target.in_arcs) == 1:
                        arc.target.is_call_return = True

        # Sort the arcs by their target nodes
        bb.out_arcs.sort(lambda a, b: cmp(a.target.blockno, b.target.blockno))
    return newbbs

def solve_arc_counts(nodes):
    '''Update the arc counts such that each arc without a runtime counter gets
    its correct count value. This also adds count values to each block.'''

    # This is the first pass: compute a list of unsolved blocks and arcs.
    unsolved = set(block for block in nodes if block.get_count() == -1)
    unsolved_arcs = set()
    for block in nodes:
        unsolved_arcs.update(filter(lambda x: x.count != x.count,
            block.out_arcs))

    # Now, iterate by propagating first the block counts to unknown arcs and
    # then the arc counts to unknown blocks.
    while len(unsolved) > 0:
        did_change = False
        maybe_solved_blocks = set()
        solved_arcs = set()
        for arc in unsolved_arcs:
            maybe_solved = arc.solve_count()
            if maybe_solved:
                maybe_solved_blocks.add(maybe_solved)
                solved_arcs.add(arc)
                did_change = True
        unsolved_arcs -= solved_arcs

        for block in maybe_solved_blocks.intersection(unsolved):
            if block.get_count() != -1:
                unsolved.remove(block)
                did_change = True

        # If the graph didn't change, something is horribly wrong
        if not did_change:
            display_bb_graph(nodes)
            assert did_change

def build_line_map(blocks):
    filename, line = '', 0
    block_map = dict()
    line_counts = dict()
    # The first two blocks are the entry and exit blocks, which should be
    # ignored.
    for bb in blocks[2:]:
        for filename, line in bb.bbdata.get_lines():
            key = filename, line
            line_counts[key] = line_counts.get(key, 0) + bb.count
            pass
        else:
            pass

        block_map.setdefault((filename, line), []).append(bb)
    return block_map, line_counts

def add_coverage_data(line_map, get_file_data):
    block_map, line_counts = line_map
    for location, blocks in block_map.iteritems():
        fdata = get_file_data(location[0])
        i, j = 0, 0

        # Dump the branch data for all entries on this line.
        for bb in blocks:
            if bb.is_call_return:
                continue
            if len(bb.out_arcs) > 1:
                for arc in bb.out_arcs:
                    if arc.is_call_non_return or arc.is_unconditional:
                        continue
                    fdata.add_branch_hit(location[1], i, j, arc.count)
                    j += 1
            i += 1

    # Work out the line counts to add
    files = set()
    for location, count in line_counts.iteritems():
        files.add(location[0])
        fdata = get_file_data(location[0])
        fdata.add_line_hit(location[1], count)
    return files

# Helper for displaying what these graphs look like
def display_bb_graph(nodes):
    import subprocess
    pipe = subprocess.Popen(['dot', '-Tpng'], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE)
    display = subprocess.Popen(['display'], stdin=pipe.stdout)
    dotf = pipe.stdin
    dotf.write('digraph G {\n')
    for bb in nodes:
        blkno = bb.blockno
        dotf.write('  %d [label="%d"];\n' % (blkno, blkno))
        for arc in bb.out_arcs:
          dotf.write('  %d -> %d [label="%x/%s"];\n' % (
            arc.source.blockno, arc.target.blockno, arc.flags, str(arc.count)))
    dotf.write('}')
    dotf.close()
    display.wait()
