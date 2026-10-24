#!/usr/bin/env python3
"""Development LAN release server: only signed feed files and its archive, with Range."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import re
import urllib.parse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory', type=Path)
parser.add_argument('--bind', default='127.0.0.1')
parser.add_argument('--port', type=int, default=8787)
args = parser.parse_args()
address = ipaddress.ip_address(args.bind)
if not address.is_private or address.is_unspecified:
    parser.error('Bind to a specific private LAN IP or loopback')
root = args.directory.resolve()


class ReleaseHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            feed = json.loads((root / 'release.json').read_text())
            archives = [p['file'] for p in feed['packages']] if feed.get('schema')==2 else [feed['package']['file']]
            if not all(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]*\.tar\.gz', archive) for archive in archives):
                raise ValueError('Invalid release artifact filename')
            name = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).removeprefix('/')
            if name not in ('release.json', 'release.json.sig', *archives):
                self.send_error(404)
                return
            path = root / name
            if path.is_symlink() or not path.is_file():
                self.send_error(404)
                return
            size = path.stat().st_size
            start, end, partial = 0, size - 1, False
            if self.headers.get('Range'):
                match = re.fullmatch(r'bytes=([0-9]+)-([0-9]+)', self.headers['Range'])
                if not match or not (0 <= int(match[1]) <= int(match[2]) < size):
                    self.send_error(416)
                    return
                start, end, partial = int(match[1]), int(match[2]), True
            self.send_response(206 if partial else 200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(end - start + 1))
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Cache-Control', 'no-store')
            if partial:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            with path.open('rb') as source:
                source.seek(start)
                remaining = end - start + 1
                while remaining:
                    block = source.read(min(1024**2, remaining))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return  # Client may intentionally interrupt a download.
        except (ValueError, KeyError):
            self.send_error(503)


print(f'Serving signed release at http://{args.bind}:{args.port}/release.json', flush=True)
ThreadingHTTPServer((args.bind, args.port), ReleaseHandler).serve_forever()
