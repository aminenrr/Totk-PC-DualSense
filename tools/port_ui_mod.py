"""Port a button-prompt UI mod made for an older TotK (an emulator RomFS mod) onto the game's own files, on top of a
romfs-patches folder (tools/make_romfs_patches.py), into a new overlay folder for romfs_patches = <out>
(runtime/romfs.c overlay_init loads one TOTK_ROMFS_PATCHES folder; two overlays may not replace the same file).

Nothing of the mod is copied whole: an archive of another game version would lose that version's UI changes.
- UI/LayoutArchive/Common.Product.<NNN>.Nin_NX_NVN.blarc.zs of the mod (any version): the button and controller
  textures of its timg/__Combined.bntx (TEXTURES, or --textures) replace the same-named ones in the archive this game
  runs, in the mod's own format and size (bntx_transplant), taken from the base folder when it patched it (the 60 fps
  capture fix stays). Other textures the mod's archive has differently are the game's own changes since that version
  (1.2.0 redrew the 72x72 icons at 108x108) and stay.
- Font/Font*.Nin_NX_NVN.bfarc.zs of the mod, with --fonts only (a 1.1 External.bfotf in the 1.4.3 archives
  crashed the game at start, 2026-11-01): its scft/External.bfotf (the button glyph font) replaces the game's,
  when the game's archive has that member.
Other members the mod changed (layouts, animations: a black screen fix duplicates the base folder's) are listed, not
taken. The report is printed as JSON. Run with the setup's python (compression.zstd).
- System/Resource/ResourceSizeTable.Product.<newest>.rsizetable.zs: the entries of the files that grew grow with them.
- The same archive's controller-picture animations (ANIMS): curves the mod moved, key for key, take its values.
"""
import argparse
import compression.zstd as zstd
import hashlib
import json
import zlib
import re
import shutil
import struct
from pathlib import Path

ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
ap.add_argument('--romfs', type=Path, required=True, help='the install folder\'s romfs (romfs.bin and index.json)')
ap.add_argument('--base', type=Path, required=True, help='the romfs-patches folder to build on')
ap.add_argument('--mod', type=Path, required=True, help='the mod\'s romfs folder (holds UI/ and Font/)')
ap.add_argument('--out', type=Path, required=True, help='the new overlay folder (replaced)')
ap.add_argument('--fonts', action='store_true', help='also take the mod\'s scft/External.bfotf (crashed 1.4.3 at start with a 1.1 mod)')
ap.add_argument('--textures', help='comma-separated texture names to take (default TEXTURES)')
ap.add_argument('--version', choices=('v111', 'v121', 'v143'), default='v143')
args = ap.parse_args()
if not (args.mod / 'UI').is_dir() and not (args.mod / 'Font').is_dir():
    # an unzipped mod folder: the romfs folder somewhere inside it
    found = sorted(p for p in args.mod.rglob('romfs') if p.is_dir() and ((p / 'UI').is_dir() or (p / 'Font').is_dir()))
    assert len(found) == 1, f'{args.mod}: expected one romfs folder with UI/ or Font/ inside, found {found}'
    args.mod = found[0]
index = json.loads((args.romfs / 'index.json').read_text())
assert index['status'] == 'pass'
files = {f['path']: f for f in index['files']}


# sarc_nodes, sarc_members and sarc_replace: the same as tools/make_romfs_patches.py.
def sarc_nodes(data):
    assert data[:4] == b'SARC' and data[6:8] == b'\xff\xfe'
    header, size, start = struct.unpack_from('<HxxII', data, 4)
    assert size == len(data) and data[header:header + 4] == b'SFAT'
    count = struct.unpack_from('<H', data, header + 6)[0]
    names = header + 12 + count * 16
    assert data[names:names + 4] == b'SFNT'
    names += 8
    out = []
    for i in range(count):
        node = header + 12 + i * 16
        _, attribute, lo, hi = struct.unpack_from('<4I', data, node)
        offset = names + (attribute & 0xffffff) * 4
        out.append((data[offset:data.index(0, offset, start)].decode(), node, start + lo, start + hi))
    return out


def sarc_members(data):
    return {name: (lo, hi) for name, _, lo, hi in sarc_nodes(data)}


def sarc_replace(data, new):
    start = struct.unpack_from('<I', data, 12)[0]
    out = bytearray(data[:start])
    for name, node, lo, hi in sorted(sarc_nodes(data), key=lambda n: n[2]):
        align = min(lo & -lo, 0x2000) if lo else 0x2000
        out += bytes(-len(out) % align)
        body = new.get(name, data[lo:hi])
        struct.pack_into('<II', out, node + 8, len(out) - start, len(out) - start + len(body))
        out += body
    struct.pack_into('<I', out, 8, len(out))
    return bytes(out)


def bntx_textures(data, base):
    """name (without the ^ suffix) -> (shape, absolute image start, image size) of every texture of the BNTX at
    data[base:] (the layout of tools/make_romfs_patches.py bntx_swap)."""
    assert data[base:base + 4] == b'BNTX' and data[base + 0x20:base + 0x24] == b'NX  '
    count, table = struct.unpack_from('<IQ', data, base + 0x24)
    found = {}
    for k in range(count):
        info = base + struct.unpack_from('<Q', data, base + table + 8 * k)[0]
        assert data[info:info + 4] == b'BRTI'
        name = base + struct.unpack_from('<Q', data, info + 0x60)[0]
        name = data[name + 2:name + 2 + struct.unpack_from('<H', data, name)[0]].decode().split('^')[0]
        mips = base + struct.unpack_from('<Q', data, info + 0x70)[0]
        shape = bytes(data[info + 0x10:info + 0x3c]) + bytes(data[info + 0x50:info + 0x54])
        start, size = base + struct.unpack_from('<Q', data, mips)[0], struct.unpack_from('<I', data, info + 0x50)[0]
        found[name] = (shape, start, size)
    return found


BRTI_COPY = (0x11, 0x5c)   # from dim to channel types: everything that describes the image but the flags byte


def bntx_transplant(game, mod, names):
    """The BNTX game with the textures named (without the ^ suffix) replaced by those of the BNTX mod, in the mod's
    own format, size and tiling. The image data goes at the end of the BRTD block (the texture memory pool), which
    grows by it, page aligned; the relocation table after it moves along. The old images stay, unused. Each texture
    keeps its own mip count or fewer (its mip offset array has that many slots)."""
    out = bytearray(game)
    assert out[:4] == b'BNTX' and out[0x20:0x24] == b'NX  ' and mod[:4] == b'BNTX'
    rlt, size = struct.unpack_from('<II', out, 0x18)
    assert size == len(out) and out[rlt:rlt + 4] == b'_RLT'
    brtd = struct.unpack_from('<Q', out, 0x30)[0]
    assert out[brtd:brtd + 4] == b'BRTD' and brtd + struct.unpack_from('<I', out, brtd + 8)[0] == rlt
    sections = struct.unpack_from('<I', out, rlt + 8)[0]
    data_section = [s for s in range(sections) if struct.unpack_from('<I', out, rlt + 0x18 + 0x18 * s)[0] == brtd]
    assert len(data_section) == 1, 'no relocation section for the BRTD block'
    tail, appended = bytes(out[rlt:]), bytearray()

    def infos(d):
        count, table = struct.unpack_from('<IQ', d, 0x24)
        found = {}
        for k in range(count):
            info = struct.unpack_from('<Q', d, table + 8 * k)[0]
            assert d[info:info + 4] == b'BRTI'
            name = struct.unpack_from('<Q', d, info + 0x60)[0]
            found[d[name + 2:name + 2 + struct.unpack_from('<H', d, name)[0]].decode().split('^')[0]] = info
        return found
    gi, mi = infos(out), infos(mod)
    for name in names:
        g, m = gi[name], mi[name]
        gmips, mmips = struct.unpack_from('<H', out, g + 0x16)[0], struct.unpack_from('<H', mod, m + 0x16)[0]
        assert 1 <= mmips <= gmips, (name, gmips, mmips)
        moffs = struct.unpack_from(f'<{mmips}Q', mod, struct.unpack_from('<Q', mod, m + 0x70)[0])
        isize, align = struct.unpack_from('<II', mod, m + 0x50)
        appended += bytes(-(rlt + len(appended)) % max(align, 0x200))
        at = rlt + len(appended)
        appended += mod[moffs[0]:moffs[0] + isize]
        out[g + BRTI_COPY[0]:g + BRTI_COPY[1]] = mod[m + BRTI_COPY[0]:m + BRTI_COPY[1]]
        gmp = struct.unpack_from('<Q', out, g + 0x70)[0]
        for k in range(gmips):
            struct.pack_into('<Q', out, gmp + 8 * k, at + (moffs[k] - moffs[0] if k < mmips else 0))
    appended += bytes(-(rlt + len(appended)) % 0x1000)
    grow = len(appended)
    out[rlt:] = appended + tail
    new_rlt = rlt + grow
    struct.pack_into('<II', out, 0x18, new_rlt, len(out))
    struct.pack_into('<I', out, new_rlt + 4, new_rlt)
    struct.pack_into('<I', out, brtd + 8, struct.unpack_from('<I', out, brtd + 8)[0] + grow)
    s = new_rlt + 0x10 + 0x18 * data_section[0]
    struct.pack_into('<I', out, s + 0xc, struct.unpack_from('<I', out, s + 0xc)[0] + grow)
    return bytes(out)


def flan(d):
    """(pane or material, tag, index, target) -> (curve type, [(key values, absolute key offset)]) of a FLAN."""
    assert d[:4]==b'FLAN'
    bom=d[4:6]; E='>' if bom==b'\xfe\xff' else '<'
    hs,=struct.unpack_from(E+'H',d,6); n,=struct.unpack_from(E+'H',d,0x10)
    off=hs; out={}
    for _ in range(n):
        mg=d[off:off+4]; sz,=struct.unpack_from(E+'I',d,off+4)
        if mg==b'pai1':
            p=off
            fs,loop,tc,ac,ato=struct.unpack_from(E+'HBxHHI',d,p+8)
            for i in range(ac):
                eo=p+struct.unpack_from(E+'I',d,p+ato+4*i)[0]
                name=d[eo:eo+28].split(b'\0')[0].decode()
                tcnt,ismat=struct.unpack_from('BB',d,eo+28)
                for t in range(tcnt):
                    to=eo+struct.unpack_from(E+'I',d,eo+32+4*t)[0]
                    tm=d[to:to+4].decode(); cnt=d[to+4]
                    for c in range(cnt):
                        io=to+struct.unpack_from(E+'I',d,to+8+4*c)[0]
                        idx,tgt,ct,kc,ko=struct.unpack_from(E+'BBBxHxxI',d,io)
                        ks=[]
                        for k in range(kc):
                            ka=io+ko+(12 if ct==2 else 8)*k
                            if ct==2: ks.append((struct.unpack_from(E+'3f',d,ka),ka))
                            else: ks.append((struct.unpack_from(E+'fH',d,ka),ka))
                        out[(name,tm,idx,tgt)]=(ct,ks)
        off+=sz
    return out,E


def flan_merge(game, mod):
    """The FLAN the mod's controller picture needs, and how many of its curves differ from the game's. When the mod's
    FLAN animates every curve the game's does (the 1.1 files are the 1.4.3 ones plus the mod's edits, 2026-11-01), it is
    taken whole: its edits go together (it also adds curves, such as moving the d-pad label when that row shows), and
    taking only the moved points misplaced labels in game. Otherwise each curve with the same key frames takes the mod's
    values."""
    g, E = flan(game); m, E2 = flan(mod)
    assert E == E2
    changed = sum(1 for k in set(g) | set(m) if k not in g or k not in m or [x[0] for x in g[k][1]] != [x[0] for x in m[k][1]])
    if set(g) <= set(m):
        return bytes(mod), changed
    out, taken = bytearray(game), 0
    for k, (ct, gk) in g.items():
        if k not in m or m[k][0] != ct or len(m[k][1]) != len(gk) or [x[0][0] for x in m[k][1]] != [x[0][0] for x in gk]:
            continue
        if [x[0] for x in m[k][1]] == [x[0] for x in gk]:
            continue
        n = 12 if ct == 2 else 8
        for (_, ga), (_, ma) in zip(gk, m[k][1]):
            out[ga:ga + n] = mod[ma:ma + n]
        taken += 1
    return bytes(out), taken

# StavaasEVG's Dualsense UI (gamebanana.com/mods/445517), checked by decoding both versions: the PlayStation face
# buttons, L1/L2, d-pad, R1/R2 shapes, prompt button bases and the controller picture.
TEXTURES = ('Nt_KeyTexA_00', 'Nt_KeyTexB_00', 'Nt_KeyTexX_00', 'Nt_KeyTexY_00', 'Nt_KeyTexL_00', 'Nt_KeyTexZL_00',
            'ButtonIconL46NN_00', 'ButtonIconL46NN_01', 'ConProR_00', 'ConProR_Line', 'ConProZR_00', 'ConProZR_Line',
            'Nt_KeyBtnBaseBoxLL_00', 'Nt_KeyBtnSubBaseAL_00', 'Nt_KeyBtnSubBaseBL_00', 'Controller_Pro', 'Controller_Pro1',
            'ControllerSh_Pro', 'ControllerSh_Pro1')
# The callout points and lines of the controller pictures (System > Basic Controls, the tutorials) move with them.
ANIMS = r'anim/Pa(SystemController|ActionGuide)_00_\w+\.bflan'
COMMON = {'v111': '110', 'v121': '110', 'v143': '140'}
ARCHIVE = f'UI/LayoutArchive/Common.Product.{COMMON[args.version]}.Nin_NX_NVN.blarc.zs'
BNTX = 'timg/__Combined.bntx'
FONT = 'scft/External.bfotf'
mod_common = sorted(args.mod.glob('UI/LayoutArchive/Common.Product.*.Nin_NX_NVN.blarc.zs'))
assert len(mod_common) <= 1, mod_common
mod_common = mod_common[0].relative_to(args.mod).as_posix() if mod_common else None
mod_fonts = [] if not args.fonts else sorted(p.relative_to(args.mod).as_posix() for p in args.mod.glob('Font/Font*.Nin_NX_NVN.bfarc.zs'))
assert mod_common or mod_fonts, f'no UI/LayoutArchive/Common.Product.*.blarc.zs or Font/*.bfarc.zs in {args.mod}'
base_lines = {}
for line in (args.base / 'manifest.tsv').read_text().splitlines():
    if line and not line.startswith('#'):
        p, size, sha, orig = line.split('\t')
        base_lines[p] = (int(size), sha, orig)

with (args.romfs / 'romfs.bin').open('rb') as image:
    def read(path):
        f = files[path]
        image.seek(f['offset'])
        b = image.read(f['size'])
        assert len(b) == f['size']
        return b
    dictionaries = {}
    pack = zstd.decompress(read('Pack/ZsDic.pack.zs'))
    for name, (lo, hi) in sarc_members(pack).items():
        d = zstd.ZstdDict(pack[lo:hi])
        dictionaries[d.dict_id] = d
    # 1.4.3: System/Resource/ResourceSizeTable.Product.143.Nin_NX_NVN.rsizetable.zs
    restbl = sorted((p for p in files if re.fullmatch(r'System/Resource/ResourceSizeTable\.Product\.\d+(\.\w+)?\.rsizetable\.zs', p)),
                    key=lambda p: int(p.split('.')[2]))
    assert restbl, 'no System/Resource/ResourceSizeTable.Product.*.rsizetable.zs in the RomFS'
    RESTBL = restbl[-1]
    wanted = {ARCHIVE, RESTBL} | set(mod_fonts)
    originals = {p: read(p) for p in wanted if p in files}


def unpack(raw):
    return zstd.decompress(raw, zstd_dict=dictionaries.get(zstd.get_frame_info(raw).dictionary_id))


def current(path):
    """The file as the base folder serves it, or the game's own."""
    if path in base_lines:
        return (args.base / path).read_bytes()
    return originals[path]


outputs, report = {}, {}
if mod_common:
    game = unpack(current(ARCHIVE))
    mod = unpack((args.mod / mod_common).read_bytes())
    gm, mm = sarc_members(game), sarc_members(mod)
    gb, mb = game[gm[BNTX][0]:gm[BNTX][1]], mod[mm[BNTX][0]:mm[BNTX][1]]
    gt, mt = bntx_textures(gb, 0), bntx_textures(mb, 0)
    names = args.textures.split(',') if args.textures else TEXTURES
    taken, skipped = [], {}
    for name in names:
        if name not in mt or name not in gt:
            skipped[name] = 'not in the mod' if name not in mt else 'not in this game version'
        elif gt[name][0] == mt[name][0] and gb[gt[name][1]:gt[name][1] + gt[name][2]] == mb[mt[name][1]:mt[name][1] + mt[name][2]]:
            skipped[name] = 'the same as the game\'s'
        else:
            taken.append(name)
    assert taken, f'no texture of the mod could be taken: {skipped}'
    members = {BNTX: bntx_transplant(gb, mb, taken)}
    curves = {}
    for name in sorted(gm):
        if re.fullmatch(ANIMS, name) and name in mm and game[gm[name][0]:gm[name][1]] != mod[mm[name][0]:mm[name][1]]:
            body, count = flan_merge(game[gm[name][0]:gm[name][1]], mod[mm[name][0]:mm[name][1]])
            if count:
                members[name], curves[name] = body, count
    outputs[ARCHIVE] = sarc_replace(game, members)
    report['common'] = dict(mod_archive=mod_common, textures=taken, skipped=skipped, callout_curves=curves)
fonts = {}
for path in mod_fonts:
    if path not in originals:
        fonts[path] = 'not in this game'
        continue
    game = unpack(current(path))
    mod = unpack((args.mod / path).read_bytes())
    gm, mm = sarc_members(game), sarc_members(mod)
    if FONT not in gm or FONT not in mm:
        fonts[path] = f'no {FONT}'
        continue
    body = mod[mm[FONT][0]:mm[FONT][1]]
    if body == game[gm[FONT][0]:gm[FONT][1]]:
        fonts[path] = 'unchanged'
        continue
    outputs[path] = sarc_replace(game, {FONT: body})
    others = sorted(n for n, (lo, hi) in mm.items() if n != FONT and (n not in gm or game[gm[n][0]:gm[n][1]] != mod[lo:hi]))
    fonts[path] = dict(taken=FONT, other_members_not_taken=others)
report['fonts'] = fonts

# The resource size table: the game sizes each file's load buffer from its entry (the path without .zs, by CRC32 or in the
# name table), so a file that grew past it crashed the game (2026-11-01, both at start with the fonts and at the title
# with Common). Each grown file's entry grows by as much as the file, 32-byte aligned, keeping the game's own margin.
if outputs:
    table = bytearray(unpack(current(RESTBL)))
    version, block, crcs, names = struct.unpack_from('<4I', table, 6)
    assert table[:6] == b'RESTBL' and len(table) == 0x16 + 8 * crcs + (block + 4) * names, 'unknown RESTBL layout'
    def find(key):
        hits = [0x16 + 8 * i + 4 for i in range(crcs)
                if struct.unpack_from('<I', table, 0x16 + 8 * i)[0] == zlib.crc32(key.encode())]
        start = 0x16 + 8 * crcs
        hits += [start + (block + 4) * i + block for i in range(names)
                 if table[start + (block + 4) * i:start + (block + 4) * i + block].split(b'\0')[0] == key.encode()]
        return hits

    grown = {}
    for path, contents in outputs.items():
        delta = (len(contents) + 31 & ~31) - (len(unpack(current(path))) + 31 & ~31)
        if delta <= 0:
            continue
        for key in dict.fromkeys((path[:-3] if path.endswith('.zs') else path, path)):
            hits = find(key)
            if hits:
                break
        assert hits, f'{path} is not in {RESTBL}'
        for at in hits:
            struct.pack_into('<I', table, at, struct.unpack_from('<I', table, at)[0] + delta)
        grown[key] = delta

    if grown:
        outputs[RESTBL] = bytes(table)
    report['size_table'] = dict(file=RESTBL, grown=grown)

if args.out.exists():
    shutil.rmtree(args.out)
lines = []
for path, (size, sha, orig) in base_lines.items():
    if path in outputs:
        continue
    target = args.out / path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.base / path, target)
    lines.append('\t'.join([path, str(size), sha, orig]))
for path, contents in outputs.items():
    raw = originals[path]
    dictionary = dictionaries.get(zstd.get_frame_info(raw).dictionary_id)
    data = zstd.compress(contents, level=19, zstd_dict=dictionary)
    assert zstd.decompress(data, zstd_dict=dictionary) == contents
    target = args.out / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    lines.append('\t'.join([path, str(len(data)), hashlib.sha256(data).hexdigest(), hashlib.sha256(raw).hexdigest()]))
(args.out / 'manifest.tsv').write_text('# path\tsize\tsha256\toriginal_sha256 (tools/port_ui_mod.py)\n'
                                       + ''.join(line + '\n' for line in sorted(lines)))
print(json.dumps(dict(status='pass', out=str(args.out), **report), indent=1))
