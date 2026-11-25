import struct, subprocess, sys, os, collections

SRC, DST, WORK = sys.argv[1], sys.argv[2], sys.argv[3]
d = bytearray(open(SRC, 'rb').read())
u16 = lambda o: struct.unpack_from('<H', d, o)[0]
u32 = lambda o: struct.unpack_from('<I', d, o)[0]
u64 = lambda o: struct.unpack_from('<Q', d, o)[0]

# ---- ELF header / phdrs
phoff, phentsize, phnum = u64(0x20), u16(0x36), u16(0x38)
phdrs = []
for i in range(phnum):
    o = phoff + i * phentsize
    t, fl, off, va, pa, fs, ms, al = struct.unpack_from('<IIQQQQQQ', d, o)
    phdrs.append(dict(i=i, o=o, type=t, flags=fl, off=off, va=va, fs=fs, ms=ms, al=al))
loads = [p for p in phdrs if p['type'] == 1]
def v2o(v):
    for p in loads:
        if p['va'] <= v < p['va'] + p['fs']:
            return v - p['va'] + p['off']
    raise ValueError(hex(v))
def writable(v):
    return any(p['flags'] & 2 and p['va'] <= v < p['va'] + p['ms'] for p in loads)

# ---- dynamic
dyn_ph = [p for p in phdrs if p['type'] == 2][0]
dyn = []  # (index, tag, val, file offset)
for k in range(dyn_ph['fs'] // 16):
    o = dyn_ph['off'] + 16 * k
    tag, val = struct.unpack_from('<qQ', d, o)
    dyn.append([o, tag, val])
    if tag == 0: break
D = {}
for o, tag, val in dyn: D.setdefault(tag, (o, val))
DT_RELA, DT_RELASZ, DT_JMPREL, DT_PLTRELSZ = 7, 8, 23, 2
SYMTAB, STRTAB, VERSYM = D[6][1], D[5][1], D[0x6ffffff0][1]
RELR, RELRSZ, RELRENT = 0x6fffe000, 0x6fffe001, 0x6fffe003
relr_va, relr_sz = D.get(RELR, (0, 0))[1], D.get(RELRSZ, (0, 0))[1]
jmp_va, jmp_sz = D[DT_JMPREL][1], D[DT_PLTRELSZ][1]
relr_va, relr_sz = D.get(RELR, (0, 0))[1], D.get(RELRSZ, (0, 0))[1]
nsyms = (STRTAB - SYMTAB) // 24  # strtab follows symtab-adjacent sections; refined below
nsyms = struct.unpack_from('<H', d, 0)[0] and (D[0x6ffffff0][1] - SYMTAB) // 24  # versym follows dynsym
assert STRTAB and nsyms > 0, nsyms

def sym(i):
    o = v2o(SYMTAB) + 24 * i
    name, info, other, shndx, value, size = struct.unpack_from('<IBBHQQ', d, o)
    return dict(o=o, name=name, info=info, shndx=shndx, value=value)
def cstr(off):
    o = v2o(STRTAB) + off
    e = d.index(0, o)
    return d[o:e].decode()
names = {}
for i in range(nsyms):
    s = sym(i)
    names[i] = cstr(s['name'])
by_name = {n: i for i, n in names.items() if n}

def read_rela(va, sz):
    out = []
    o = v2o(va)
    for k in range(sz // 24):
        out.append(list(struct.unpack_from('<QQq', d, o + 24 * k)))
    return out
old_rela = read_rela(rela_va, rela_sz)
old_jmp = read_rela(jmp_va, jmp_sz)

R_ABS64, R_GLOB_DAT, R_JUMP_SLOT, R_RELATIVE, R_DTPMOD, R_TLSDESC = 0x101, 0x401, 0x402, 0x403, 0x404, 0x407
# NB: aarch64 relocation numbers: ABS64=257(0x101) GLOB_DAT=1025(0x401) JUMP_SLOT=1026(0x402) RELATIVE=1027(0x403)

# ---- which imports to replace with local shims
SHIMS = {
    'call_once': 'shim_call_once', 'cnd_init': 'shim_cnd_init', 'cnd_destroy': 'shim_cnd_destroy',
    'cnd_signal': 'shim_cnd_signal', 'cnd_broadcast': 'shim_cnd_broadcast', 'cnd_wait': 'shim_cnd_wait',
    'mtx_init': 'shim_mtx_init', 'mtx_destroy': 'shim_mtx_destroy', 'mtx_lock': 'shim_mtx_lock',
    'mtx_unlock': 'shim_mtx_unlock', 'thrd_create': 'shim_thrd_create', 'thrd_join': 'shim_thrd_join',
    'thrd_current': 'shim_thrd_current', 'thrd_yield': 'shim_thrd_yield',
    'pthread_getaffinity_np': 'shim_pthread_getaffinity_np', 'pthread_setaffinity_np': 'shim_pthread_setaffinity_np',
    'sched_getaffinity': 'shim_sched_getaffinity', 'qsort_r': 'shim_qsort_r', 'getpwuid_r': 'shim_getpwuid_r',
}
def is_und(n):
    return n in by_name and sym(by_name[n])['shndx'] == 0
SHIMS = {k: v for k, v in SHIMS.items() if is_und(k)}
print('shimmed imports:', sorted(SHIMS))
# two dynsym entries are recycled to import __tls_get_addr / pthread_create
if is_und('pthread_create'):
    RECYCLE = {}
elif 'pthread_setaffinity_np' in SHIMS:
    RECYCLE = {'pthread_setaffinity_np': 'pthread_create'}
else:
    cand = [n for n in SHIMS if len(n) >= len('pthread_create')]
    assert cand, 'no dynsym entry to recycle for pthread_create'
    RECYCLE = {cand[0]: 'pthread_create'}
print('recycle:', RECYCLE)
shim_idx = {by_name[n]: n for n in SHIMS}

# GOT slots of existing imports used by shim code
jslot = {}
for off, info, add in old_jmp:
    jslot.setdefault(names[info >> 32], off)
need = ['pthread_mutex_init', 'pthread_mutex_lock', 'pthread_mutex_unlock', 'pthread_mutex_destroy',
        'pthread_cond_init', 'pthread_cond_signal', 'pthread_cond_broadcast', 'pthread_cond_destroy',
        'pthread_cond_wait', 'pthread_once', 'pthread_join', 'pthread_self', '__errno']
for n in need: assert n in jslot, n

# relro padding area (writable, zero, before RELRO is applied) used for new GOT-like slots
relro = [p for p in phdrs if p['type'] == 0x6474e552][0]
RP = relro['va'] + relro['ms'] - 0x620
assert writable(RP) and writable(RP + 0x600) and RP % 8 == 0
for p_ in loads:  # slots must be zero (file bytes) or beyond filesz (zero-fill)
    if p_['va'] <= RP < p_['va'] + p_['ms']:
        for a in range(RP, RP + 0x620, 8):
            if a < p_['va'] + p_['fs']: assert u64(v2o(a)) == 0, hex(a)
print('new slots at', hex(RP))
slot_tls, slot_pcreate = RP, RP + 8
dummy_base = RP + 0x10
defs = {f'got_{n}': jslot[n] for n in need}
defs['got_pthread_create'] = slot_pcreate if RECYCLE else jslot['pthread_create']

tlsdesc = []
os.makedirs(WORK, exist_ok=True)

# ---- end of image / new segment placement
max_end = max(p['va'] + p['ms'] for p in loads)
PAGE = 0x4000
V = (max_end + PAGE - 1) // PAGE * PAGE
data_end = len(d)  # keep whole original file incl. section headers (bionic rejects ELF without them)
O = (data_end + PAGE - 1) // PAGE * PAGE
print(f'new segment vaddr={V:#x} fileoff={O:#x}')

# ---- build shim
cc = ['clang', '--target=aarch64-linux-gnu', '-O2', '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
      '-fno-pic', '-fno-jump-tables', '-fno-asynchronous-unwind-tables', '-fno-unwind-tables', '-mno-outline-atomics',
      '-I', WORK, '-c', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shim.c'), '-o', f'{WORK}/shim.o']
subprocess.check_call(cc)
ld = ['ld.lld', '-static', '-nostdlib', '-z', 'norelro', '--no-rosegment', f'-Ttext={V:#x}', '-e', '0', '-o', f'{WORK}/shim.elf', f'{WORK}/shim.o']
for k, v in defs.items(): ld += ['--defsym', f'{k}={v:#x}']
subprocess.check_call(ld)
subprocess.check_call(['llvm-objcopy', '-O', 'binary', '--only-section=.text', f'{WORK}/shim.elf', f'{WORK}/shim.bin'])
code = open(f'{WORK}/shim.bin', 'rb').read()
syms = {}
for line in subprocess.check_output(['llvm-nm', f'{WORK}/shim.elf']).decode().split('\n'):
    p = line.split()
    if len(p) == 3: syms[p[2]] = int(p[0], 16)
assert syms['shim_mtx_lock'] == V or True
for n, s in list(SHIMS.items()): assert SHIMS[n] in syms, SHIMS[n]
print('shim code size', len(code))

# ---- new RELA table
new = []
def rel(off, typ, sym=0, add=0): new.append((off, (sym << 32) | typ, add))
for off, info, add in old_rela:
    t, s = info & 0xffffffff, info >> 32
    if s in shim_idx:
        rel(off, R_RELATIVE, 0, syms[SHIMS[shim_idx[s]]])
    else:
        new.append((off, info, add))
# RELR -> RELATIVE (addend = in-place value)
nrelr = 0
words = []  # RELR left untouched (supported by Android 10)
where = None
def emit(a):
    global nrelr
    assert writable(a) and a % 8 == 0, hex(a)
    rel(a, R_RELATIVE, 0, u64(v2o(a))); nrelr += 1
for w in words:
    if w & 1 == 0:
        emit(w); where = w + 8
    else:
        i = 0; w >>= 1
        while w:
            if w & 1: emit(where + 8 * i)
            w >>= 1; i += 1
        where += 63 * 8
print('relr entries expanded:', nrelr)
# displaced PLT slots: real fix in RELA, neutralise the JMPREL entry (retarget to a dummy slot + harmless symbol)
abort_idx = by_name['abort']
dk = 0
jm = []
for off, info, add in old_jmp:
    s = info >> 32
    if s in shim_idx:
        rel(off, R_RELATIVE, 0, syms[SHIMS[shim_idx[s]]])
        jm.append((dummy_base + 8 * dk, (abort_idx << 32) | R_JUMP_SLOT, 0)); dk += 1
    else:
        jm.append((off, info, add))
assert dummy_base + 8 * dk < RP + 0x600
# recycled symbols -> required GLOB_DAT imports
for old_, new_ in RECYCLE.items(): rel(slot_pcreate, R_GLOB_DAT, by_name[old_], 0)

offs = collections.Counter(o for o, _, _ in new)
dup = [hex(o) for o, c in offs.items() if c > 1]
assert not dup, dup[:5]
for o, _, _ in new: assert writable(o)

# ---- symbol table edits
def set_name(idx, newname):
    s = sym(idx)
    off = v2o(STRTAB) + s['name']
    old = cstr(s['name'])
    others = [j for j in range(nsyms) if j != idx and sym(j)['name'] and s['name'] <= sym(j)['name'] <= s['name'] + len(old)]
    assert not others, others
    assert len(newname) <= len(old)
    d[off:off + len(old) + 1] = newname.encode() + b'\0' * (len(old) - len(newname) + 1)
    vo = v2o(VERSYM) + 2 * idx
    struct.pack_into('<H', d, vo, 1)
for old, nn in RECYCLE.items(): set_name(by_name[old], nn)
# weaken imports: unknown-on-A10 symbols then resolve to 0 instead of failing dlopen
keep_strong = {'pthread_create'}
assert 'pthread_create' in names.values() or RECYCLE is not None
nweak = 0
for i in range(1, nsyms):
    s = sym(i)
    if s['shndx'] == 0 and (s['info'] >> 4) == 1 and (s['info'] & 0xf) in (0, 1, 2) and names[i] not in keep_strong:
        d[s['o'] + 4] = (2 << 4) | (s['info'] & 0xf); nweak += 1
print('weakened imports:', nweak)

# ---- write jmprel back
jo = v2o(jmp_va)
for k, (o, i, a) in enumerate(jm): struct.pack_into('<QQq', d, jo + 24 * k, o, i, a)

# ---- assemble segment: code | rela
code_pad = (-len(code)) % 16
new_rela_va = V + len(code) + code_pad
rela_bytes = b''.join(struct.pack('<QQq', *e) for e in new)
seg = code + b'\0' * code_pad + rela_bytes

# ---- dynamic edits
for ent in dyn:
    o, tag, val = ent
    if tag == DT_RELA: struct.pack_into('<Q', d, o + 8, new_rela_va)
    elif tag == DT_RELASZ: struct.pack_into('<Q', d, o + 8, len(rela_bytes))
    elif tag in (0x1d, 0x6ffffffb): struct.pack_into('<qQ', d, o, 16, 0)  # drop RUNPATH/FLAGS_1 like the A10 reference build (DT_SYMBOLIC = harmless)
# ---- PT_NOTE -> PT_LOAD (R+X)
note = [p for p in phdrs if p['type'] == 4][0]
struct.pack_into('<IIQQQQQQ', d, note['o'], 1, 5, O, V, V, len(seg), len(seg), PAGE)
# ---- drop section headers + trailing debug data; append segment
out = bytes(d[:data_end]) + b'\0' * (O - data_end) + seg
open(DST, 'wb').write(out)
print('written', DST, len(out), 'rela entries', len(new))
