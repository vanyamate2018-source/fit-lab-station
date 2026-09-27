"""Read-only local viewer. No camera controls, secrets or filesystem browsing."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from socketserver import TCPServer
import json


class LocalViewerServer(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer performs reverse DNS here, blocking GUI startup offline.
        # This viewer binds numeric LAN addresses and does not need a hostname.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def serve_viewer(host, port=8890, status=None):
    assets = Path(__file__).with_name('assets')
    routes = {
        '/': ('viewer.html', 'text/html; charset=utf-8'),
        '/index.html': ('viewer.html', 'text/html; charset=utf-8'),
        '/app-icon.png': ('viewer-icon.png', 'image/png'),
        '/apple-touch-icon.png': ('viewer-icon.png', 'image/png'),
        '/favicon.png': ('viewer-favicon.png', 'image/png'),
        '/manifest.webmanifest': ('viewer.webmanifest', 'application/manifest+json'),
        '/recorder.js': ('viewer-recorder.js', 'text/javascript; charset=utf-8'),
        '/install.js': ('viewer-install.js', 'text/javascript; charset=utf-8'),
    }
    content = {route: ((assets / filename).read_bytes(), mime) for route, (filename, mime) in routes.items()}
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(3)
        def do_GET(self):
            route = self.path.split('?', 1)[0]
            if route == '/status.json':
                page = json.dumps(status() if status else {'state': 'streaming'}).encode()
                mime = 'application/json'
            elif route not in content:
                self.send_error(404)
                return
            else:
                page, mime = content[route]
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(page)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(page)
        do_HEAD = do_GET
        def log_message(self, *_):
            pass
    server = LocalViewerServer((host, port), Handler)
    server.daemon_threads = True
    Thread(target=server.serve_forever, daemon=True, name='FIT-LAB viewer').start()
    return server


class ViewerService:
    """Keep the page available while a stream stops/restarts; no video auto-start."""
    def __init__(self, session):
        self.session = session
        self.servers = {}

    def update(self, addresses):
        from master.viewer_network import is_lan_address
        desired = {host for host in addresses if is_lan_address(host)}
        for host in set(self.servers) - desired:
            self._close(host)
        for host in desired - set(self.servers):
            try:
                self.servers[host] = serve_viewer(host, status=lambda h=host: self.status(h))
            except OSError:
                continue

    def status(self, host):
        state = self.session.state
        active = state.get('stream_host') == host and state.get('stream_mode') == 'web'
        return {'state': state.get('streaming', 'stopped') if active else 'stopped'}

    def _close(self, host):
        server = self.servers.pop(host)
        # Shutdown waits for serve_forever; keep it off the UI thread.
        def stop():
            server.shutdown()
            server.server_close()
        Thread(target=stop, daemon=True).start()

    def close(self):
        for host in list(self.servers):
            self._close(host)
