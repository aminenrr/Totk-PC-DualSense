"""Port a button-prompt UI mod made for an older TotK (an emulator RomFS mod) onto the game's own files, on top of a
romfs-patches folder (tools/make_romfs_patches.py), into a new overlay folder for romfs_patches = <out>
(runtime/romfs.c overlay_init loads one TOTK_ROMFS_PATCHES folder; two overlays may not replace the same file).

Nothing of the mod is copied whole: an archive of another game version would lose that version's UI changes.
- UI/LayoutArchive/Common.Product.<NNN>.Nin_NX_NVN.blarc.zs of the mod (any version): the textures of its
  timg/__Combined.bntx that differ from the game's own copy of that archive (or, when the RomFS lacks that version,
  from the archive this game runs) are written into the image data of the same-named textures of the archive this
  game runs, taken from the base folder when it patched it (the 60 fps capture fix stays). A texture must keep its
  format, size, tiling and mips, or it is skipped and listed.
- Font/Font*.Nin_NX_NVN.bfarc.zs of the mod: its scft/External.bfotf (the button glyph font) replaces the game's,
  when the game's archive has that member.
Other members the mod changed (layouts, animations: a black screen fix duplicates the base folder's) are listed, not
taken. The report is printed as JSON. Run with the setup's python (compression.zstd).
"""
import argparse
import compression.zstd as zstd
import hashlib
import json
import re
import shutil
import struct
from pathlib import Path

ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
ap.add_argument('--romfs', type=Path, required=True, help='the install folder\'s romfs (romfs.bin and index.json)')
ap.add_argument('--base', type=Path, required=True, help='the romfs-patches folder to build on')
ap.add_argument('--mod', type=Path, required=True, help='the mod\'s romfs folder (holds UI/ and Font/)')
ap.add_argument('--out', type=Path, required=True, help='the new overlay folder (replaced)')
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


COMMON = {'v111': '110', 'v121': '110', 'v143': '140'}
ARCHIVE = f'UI/LayoutArchive/Common.Product.{COMMON[args.version]}.Nin_NX_NVN.blarc.zs'
BNTX = 'timg/__Combined.bntx'
FONT = 'scft/External.bfotf'
mod_common = sorted(args.mod.glob('UI/LayoutArchive/Common.Product.*.Nin_NX_NVN.blarc.zs'))
assert len(mod_common) <= 1, mod_common
mod_common = mod_common[0].relative_to(args.mod).as_posix() if mod_common else None
mod_fonts = sorted(p.relative_to(args.mod).as_posix() for p in args.mod.glob('Font/Font*.Nin_NX_NVN.bfarc.zs'))
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
    wanted = {ARCHIVE} | set(mod_fonts) | ({mod_common} if mod_common in files else set())
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
    game = bytearray(unpack(current(ARCHIVE)))
    mod = unpack((args.mod / mod_common).read_bytes())
    # The reference the mod's changes are measured against: the game's own copy of the mod's archive version.
    reference = unpack(originals[mod_common]) if mod_common in originals else unpack(originals[ARCHIVE])
    gm, mm, rm = sarc_members(game), sarc_members(mod), sarc_members(reference)
    gt, mt, rt = (bntx_textures(d, m[BNTX][0]) for d, m in ((game, gm), (mod, mm), (reference, rm)))
    taken, skipped = [], {}
    for name, (shape, at, size) in sorted(mt.items()):
        ref = rt.get(name)
        if ref and ref[0] == shape and reference[ref[1]:ref[1] + ref[2]] == mod[at:at + size]:
            continue   # unchanged by the mod
        if name not in gt:
            skipped[name] = 'not in this game version'
        elif gt[name][0] != shape:
            skipped[name] = 'format, size, tiling or mips differ'
        else:
            game[gt[name][1]:gt[name][1] + size] = mod[at:at + size]
            taken.append(name)
    others = sorted(n for n, (lo, hi) in mm.items()
                    if n != BNTX and (n not in rm or reference[rm[n][0]:rm[n][1]] != mod[lo:hi]))
    assert taken, f'no texture of the mod could be taken; skipped: {skipped}'
    outputs[ARCHIVE] = bytes(game)
    report['common'] = dict(mod_archive=mod_common, reference='same version' if mod_common in originals
                            else ARCHIVE, textures=taken, skipped=skipped, other_members_not_taken=others)
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
