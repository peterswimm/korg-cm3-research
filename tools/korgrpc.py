#!/usr/bin/env python3
"""Minimal client for the KorgProtocolMessage rpcz API on CM3/CM4 Korg synths.

Transport (from upstream rpcz connection_manager.cc / rpc_channel_impl.cc):
  client DEALER  -> [b"", event_id:u64le, rpcz.rpc_request_header, request payload]
  server replies -> [b"", event_id:u64le, rpcz.rpc_response_header, response payload]
The service is addressed by its short name (e.g. "ProductService").

Prereq: compile the recovered protos once:
  (cd analysis/protos/<set> && find . -name '*.proto' | sed 's|^\\./||' |
     xargs ../../../.venv/bin/python -m grpc_tools.protoc -I. --python_out=../../../build/py/<set>)

usage:
  korgrpc.py discover [--timeout 5]
  korgrpc.py list   [--protos wavestate_3_2_1] [--service ProductService]
  korgrpc.py call   HOST:PORT Service Method ['{"json": "request"}'] [--protos ...]
  korgrpc.py selftest
"""
import argparse
import importlib.util
import itertools
import json
import os
import struct
import sys
import threading
import time
from pathlib import Path

import zmq
from google.protobuf import descriptor_pool, json_format, message_factory

ROOT = Path(__file__).resolve().parent.parent


def load_protos(proto_set):
    """Import every generated *_pb2 module so their descriptors land in the default pool."""
    base = ROOT / "build" / "py" / proto_set
    if not base.is_dir():
        sys.exit(f"missing {base}: compile analysis/protos/{proto_set} first (see module docstring)")
    sys.path.insert(0, str(base))
    for path in sorted(base.rglob("*_pb2.py")):
        mod = ".".join(path.relative_to(base).with_suffix("").parts)
        importlib.import_module(mod)
    return descriptor_pool.Default()


def iter_services(pool, proto_set):
    base = ROOT / "analysis" / "protos" / proto_set
    for p in sorted(base.rglob("*.proto")):
        fd = pool.FindFileByName(str(p.relative_to(base)))
        yield from fd.services_by_name.values()


def find_method(pool, proto_set, service, method):
    for svc in iter_services(pool, proto_set):
        if svc.name == service or svc.full_name == service:
            return svc, svc.methods_by_name[method]
    sys.exit(f"no service {service!r} in {proto_set}")


class RpczClient:
    def __init__(self, endpoint, timeout_ms=5000):
        self.ctx = zmq.Context.instance()
        self.sock = self.ctx.socket(zmq.DEALER)
        self.sock.setsockopt(zmq.LINGER, 0)
        self.sock.connect(endpoint)
        self.timeout_ms = timeout_ms
        self.ids = itertools.count(int(time.time()) & 0xFFFF)

    def call_raw(self, service, method, payload, header_cls, resp_header_cls):
        event_id = next(self.ids)
        hdr = header_cls(event_id=event_id, deadline=self.timeout_ms, service=service, method=method)
        self.sock.send_multipart([b"", struct.pack("<Q", event_id), hdr.SerializeToString(), payload])
        deadline = time.monotonic() + self.timeout_ms / 1000
        while True:
            left = int((deadline - time.monotonic()) * 1000)
            if left <= 0 or not self.sock.poll(left):
                raise TimeoutError(f"{service}.{method}: no reply in {self.timeout_ms} ms")
            frames = self.sock.recv_multipart()
            if len(frames) < 3 or frames[0] != b"":
                continue
            if struct.unpack("<Q", frames[1])[0] != event_id:
                continue
            rh = resp_header_cls()
            rh.ParseFromString(frames[2])
            return rh, (frames[3] if len(frames) > 3 else b"")


def rpcz_headers(pool):
    get = message_factory.GetMessageClass
    return (get(pool.FindMessageTypeByName("rpcz.rpc_request_header")),
            get(pool.FindMessageTypeByName("rpcz.rpc_response_header")))


def cmd_call(args):
    pool = load_protos(args.protos)
    svc, m = find_method(pool, args.protos, args.service, args.method)
    req_cls = message_factory.GetMessageClass(m.input_type)
    resp_cls = message_factory.GetMessageClass(m.output_type)
    req = json_format.Parse(args.request or "{}", req_cls())
    client = RpczClient(f"tcp://{args.endpoint}", args.timeout_ms)
    rh, payload = client.call_raw(svc.name, m.name, req.SerializeToString(), *rpcz_headers(pool))
    out = {"header": json_format.MessageToDict(rh, always_print_fields_with_no_presence=True)}
    if rh.status == 0 and payload is not None:
        resp = resp_cls()
        resp.ParseFromString(payload)
        out["response"] = json_format.MessageToDict(resp)
    print(json.dumps(out, indent=2))


def cmd_list(args):
    pool = load_protos(args.protos)
    for svc in iter_services(pool, args.protos):
        if args.service and svc.name != args.service:
            continue
        print(svc.full_name)
        for m in svc.methods:
            print(f"  {m.name}({m.input_type.name}) -> {m.output_type.name}")


def cmd_discover(args):
    from zeroconf import ServiceBrowser, Zeroconf

    zc = Zeroconf()
    seen = {}

    class L:
        def add_service(self, z, t, name):
            info = z.get_service_info(t, name, 3000)
            if info:
                addrs = info.parsed_addresses()
                seen[name] = (addrs, info.port, {k.decode(): (v or b"").decode(errors="replace")
                                                  for k, v in info.properties.items()})
                print(f"{name}\n  addresses={addrs} port={info.port} txt={seen[name][2]}")

        def update_service(self, *a):
            pass

        def remove_service(self, *a):
            pass

    ServiceBrowser(zc, "_korg-synth._tcp.local.", L())
    time.sleep(args.timeout)
    zc.close()
    if not seen:
        print("no _korg-synth._tcp services found (is the synth on USB with USB Network = NCM?)")


def cmd_selftest(args):
    """Run a fake rpcz ROUTER server on loopback and round-trip ProductService.ShowPopupMessage through it."""
    proto_set = "system_updater_1_1_0"
    pool = load_protos(proto_set)
    req_hdr_cls, resp_hdr_cls = rpcz_headers(pool)
    svc, m = find_method(pool, proto_set, "ProductService", "ShowPopupMessage")
    req_cls = message_factory.GetMessageClass(m.input_type)
    resp_cls = message_factory.GetMessageClass(m.output_type)

    ctx = zmq.Context.instance()
    srv = ctx.socket(zmq.ROUTER)
    port = srv.bind_to_random_port("tcp://127.0.0.1")
    got = {}

    def serve():
        ident, empty, eid, hdr, payload = srv.recv_multipart()
        h = req_hdr_cls()
        h.ParseFromString(hdr)
        r = req_cls()
        r.ParseFromString(payload)
        got.update(service=h.service, method=h.method, event_id=struct.unpack("<Q", eid)[0],
                   hdr_event_id=h.event_id, request=json_format.MessageToDict(r))
        srv.send_multipart([ident, b"", eid, resp_hdr_cls(status=0).SerializeToString(),
                            resp_cls().SerializeToString()])

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    req = req_cls()
    # populate the first string field, whatever it's called, so the payload is non-empty
    for f in req.DESCRIPTOR.fields:
        if f.type == f.TYPE_STRING and not f.is_repeated:
            setattr(req, f.name, "hello from korgrpc")
            break
    client = RpczClient(f"tcp://127.0.0.1:{port}", 2000)
    rh, _ = client.call_raw(svc.name, m.name, req.SerializeToString(), req_hdr_cls, resp_hdr_cls)
    t.join(2)
    assert got["service"] == "ProductService" and got["method"] == "ShowPopupMessage", got
    assert got["event_id"] == got["hdr_event_id"], got
    assert rh.status == 0
    print("selftest OK:", json.dumps(got))
    srv.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("discover")
    d.add_argument("--timeout", type=float, default=5)
    li = sub.add_parser("list")
    li.add_argument("--protos", default="wavestate_3_2_1")
    li.add_argument("--service")
    c = sub.add_parser("call")
    c.add_argument("endpoint", help="HOST:PORT from `discover`")
    c.add_argument("service")
    c.add_argument("method")
    c.add_argument("request", nargs="?")
    c.add_argument("--protos", default="wavestate_3_2_1")
    c.add_argument("--timeout-ms", type=int, default=5000)
    sub.add_parser("selftest")
    args = ap.parse_args()
    {"discover": cmd_discover, "list": cmd_list, "call": cmd_call, "selftest": cmd_selftest}[args.cmd](args)


if __name__ == "__main__":
    os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "upb")
    main()
