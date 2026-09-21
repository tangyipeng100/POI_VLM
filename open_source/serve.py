#!/usr/bin/env python3
"""Serve the release locally with byte-range support for browser video playback."""

from __future__ import annotations

import argparse
import os
import re
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlsplit, urlunsplit


RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")


class RangeRequestHandler(SimpleHTTPRequestHandler):
    """Simple static handler with the byte ranges expected by HTML video."""

    protocol_version = "HTTP/1.1"

    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            # A browser may close a keep-alive socket after a seek or reload.
            self.close_connection = True

    def translate_path(self, path: str) -> str:
        """Accept both package-root URLs and the earlier /open_source/ URL."""
        parts = urlsplit(path)
        if parts.path == "/open_source":
            parts = parts._replace(path="/")
        elif parts.path.startswith("/open_source/"):
            parts = parts._replace(path=parts.path[len("/open_source"):])
        return super().translate_path(urlunsplit(parts))

    def send_head(self) -> BinaryIO | None:
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            if not self.path.endswith("/"):
                self.send_response(HTTPStatus.MOVED_PERMANENTLY)
                self.send_header("Location", self.path + "/")
                self.end_headers()
                return None
            for index in ("index.html", "index.htm"):
                candidate = os.path.join(path, index)
                if os.path.isfile(candidate):
                    path = candidate
                    break

        if not os.path.isfile(path):
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return None

        size = os.path.getsize(path)
        range_header = self.headers.get("Range")
        start, end = 0, size - 1
        status = HTTPStatus.OK

        if range_header:
            match = RANGE_RE.fullmatch(range_header.strip())
            if not match:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, "Invalid range")
                return None
            first, last = match.groups()
            if first:
                start = int(first)
                end = int(last) if last else end
            elif last:
                start = max(0, size - int(last))
            if start >= size or start > end:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return None
            end = min(end, size - 1)
            status = HTTPStatus.PARTIAL_CONTENT

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-type", self.guess_type(path))
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Last-Modified", self.date_time_string(os.path.getmtime(path)))
        self.end_headers()

        file_object = open(path, "rb")
        if start:
            file_object.seek(start)
        self._range_end = end
        return file_object

    def copyfile(self, source: BinaryIO, output: BinaryIO) -> None:
        range_end = getattr(self, "_range_end", None)
        if range_end is None:
            return super().copyfile(source, output)
        remaining = range_end - source.tell() + 1
        try:
            while remaining > 0:
                block = source.read(min(64 * 1024, remaining))
                if not block:
                    break
                output.write(block)
                remaining -= len(block)
        except (BrokenPipeError, ConnectionResetError):
            # Browsers cancel an in-flight range when the user seeks.
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8876)
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()

    directory = args.directory.resolve()
    if not directory.is_dir():
        raise SystemExit(f"Directory does not exist: {directory}")
    handler = lambda *handler_args, **handler_kwargs: RangeRequestHandler(
        *handler_args, directory=str(directory), **handler_kwargs
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving {directory}")
    print(f"Open http://{args.host}:{args.port}/index.html")
    print(f"Legacy-compatible URL: http://{args.host}:{args.port}/open_source/index.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
