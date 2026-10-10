#!/usr/bin/env python3
"""Recover .proto definitions from serialized FileDescriptorProtos embedded in a binary.

protoc-generated C++ embeds each .proto file's FileDescriptorProto as a byte blob.
We find candidates by their leading `name` field (tag 0x0a, length, "*.proto"),
walk the wire format to find where the blob ends, parse it, and render .proto text.

usage: extract_protos.py <binary> <out_dir>
"""
import re
import sys
from pathlib import Path

from google.protobuf import descriptor_pb2 as dp

# FileDescriptorProto field number -> expected wire type
FDP_FIELDS = {1: 2, 2: 2, 3: 2, 4: 2, 5: 2, 6: 2, 7: 2, 8: 2, 9: 2, 10: 0, 11: 0, 12: 2, 14: 0}


def read_varint(buf, i):
    shift = result = 0
    while True:
        if i >= len(buf) or shift > 63:
            raise ValueError
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def blob_end(buf, start):
    """Walk FileDescriptorProto fields from start; return offset just past the last valid one."""
    i = start
    last_good = start
    while i < len(buf):
        try:
            key, j = read_varint(buf, i)
            field, wt = key >> 3, key & 7
            if FDP_FIELDS.get(field) != wt:
                break
            if wt == 0:
                _, j = read_varint(buf, j)
            else:
                ln, j = read_varint(buf, j)
                j += ln
                if j > len(buf):
                    break
        except ValueError:
            break
        i = last_good = j
    return last_good


LABELS = {1: "optional", 2: "required", 3: "repeated"}
TYPES = {v: k[5:].lower() for k, v in dp.FieldDescriptorProto.Type.items()}


def field_type(f):
    if f.type in (dp.FieldDescriptorProto.TYPE_MESSAGE, dp.FieldDescriptorProto.TYPE_ENUM,
                  dp.FieldDescriptorProto.TYPE_GROUP):
        return f.type_name
    return TYPES[f.type]


def render_enum(e, ind):
    out = [f"{ind}enum {e.name} {{"]
    for v in e.value:
        out.append(f"{ind}  {v.name} = {v.number};")
    out.append(f"{ind}}}")
    return out


def render_field(f, syntax, ind):
    label = LABELS.get(f.label, "")
    if syntax == "proto3" and label == "optional" and not f.proto3_optional:
        label = ""
    opts = []
    if f.HasField("default_value"):
        dv = f.default_value
        if f.type == dp.FieldDescriptorProto.TYPE_STRING:
            dv = '"' + dv.replace('"', '\\"') + '"'
        opts.append(f"default = {dv}")
    if f.options.HasField("packed"):
        opts.append(f"packed = {str(f.options.packed).lower()}")
    if f.options.deprecated:
        opts.append("deprecated = true")
    o = f" [{', '.join(opts)}]" if opts else ""
    return f"{ind}{(label + ' ') if label else ''}{field_type(f)} {f.name} = {f.number}{o};"


def render_message(m, syntax, ind=""):
    out = [f"{ind}message {m.name} {{"]
    for e in m.enum_type:
        out += render_enum(e, ind + "  ")
    for n in m.nested_type:
        if n.options.map_entry:
            continue
        out += render_message(n, syntax, ind + "  ")
    oneofs = {}
    for f in m.field:
        if f.HasField("oneof_index") and not f.proto3_optional:
            oneofs.setdefault(f.oneof_index, []).append(f)
    emitted = set()
    for f in m.field:
        if f.HasField("oneof_index") and not f.proto3_optional:
            idx = f.oneof_index
            if idx in emitted:
                continue
            emitted.add(idx)
            out.append(f"{ind}  oneof {m.oneof_decl[idx].name} {{")
            for of in oneofs[idx]:
                out.append(render_field(of, "proto3", ind + "    ").replace("optional ", ""))
            out.append(f"{ind}  }}")
        else:
            out.append(render_field(f, syntax, ind + "  "))
    for r in m.extension_range:
        out.append(f"{ind}  extensions {r.start} to {r.end - 1};")
    for x in m.extension:
        out.append(f"{ind}  extend {x.extendee} {{ {render_field(x, syntax, '').strip()} }}")
    out.append(f"{ind}}}")
    return out


def render_file(fd):
    syntax = fd.syntax or "proto2"
    out = [f"// Recovered from embedded FileDescriptorProto: {fd.name}", f'syntax = "{syntax}";']
    if fd.package:
        out.append(f"package {fd.package};")
    for d in fd.dependency:
        out.append(f'import "{d}";')
    if fd.options.HasField("optimize_for"):
        out.append(f"option optimize_for = {dp.FileOptions.OptimizeMode.Name(fd.options.optimize_for)};")
    out.append("")
    for e in fd.enum_type:
        out += render_enum(e, "") + [""]
    for m in fd.message_type:
        out += render_message(m, syntax) + [""]
    for x in fd.extension:
        out.append(f"extend {x.extendee} {{ {render_field(x, syntax, '').strip()} }}")
    for s in fd.service:
        out.append(f"service {s.name} {{")
        for meth in s.method:
            cs = "stream " if meth.client_streaming else ""
            ss = "stream " if meth.server_streaming else ""
            out.append(f"  rpc {meth.name}({cs}{meth.input_type}) returns ({ss}{meth.output_type});")
        out.append("}")
    return "\n".join(out) + "\n"


def main():
    binary, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    buf = binary.read_bytes()
    found = {}
    for m in re.finditer(rb"\x0a([\x01-\x7f])([\w/.\-]+?\.proto)", buf):
        if len(m.group(2)) != m.group(1)[0]:
            continue
        start = m.start()
        end = blob_end(buf, start)
        fd = dp.FileDescriptorProto()
        try:
            fd.ParseFromString(buf[start:end])
        except Exception:
            continue
        if not (fd.message_type or fd.enum_type or fd.service or fd.extension):
            continue
        prev = found.get(fd.name)
        if prev is None or len(fd.SerializeToString()) > len(prev.SerializeToString()):
            found[fd.name] = fd
    for name, fd in sorted(found.items()):
        if name.startswith("google/protobuf/"):
            continue
        p = out_dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(render_file(fd))
    print(f"{binary.name}: recovered {len(found)} descriptors -> {out_dir}")


if __name__ == "__main__":
    main()
