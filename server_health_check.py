from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Type
import threading
import os


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Respond to health check requests"""
        if self.path == '/health' or self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK - Trading bot is running')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress HTTP request logs"""
        pass


def start_healthcheck_server(port: int = None) -> HTTPServer:
    """Start health check server in background thread"""
    if port is None:
        port = int(os.getenv('PORT', 8080))

    handler_class: Type[BaseHTTPRequestHandler] = HealthCheckHandler
    server = HTTPServer(('0.0.0.0', port), handler_class)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"\n[HEALTHCHECK] Server started on port {port}")
    return server
