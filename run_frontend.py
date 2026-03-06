#!/usr/bin/env python3
"""
Frontend Server Launcher
A simple HTTP server to serve the static frontend files
"""

import http.server
import socketserver
import os
import sys
import webbrowser
from pathlib import Path


def main():
    # Configuration
    PORT = int(os.environ.get('FRONTEND_PORT', 3000))
    HOST = os.environ.get('FRONTEND_HOST', 'localhost')

    # Change to frontend static directory
    frontend_dir = Path(__file__).parent / 'frontend' / 'static'

    if not frontend_dir.exists():
        print(f"Error: Frontend directory not found at {frontend_dir}")
        sys.exit(1)

    os.chdir(frontend_dir)

    # Create HTTP server
    Handler = http.server.SimpleHTTPRequestHandler

    # Ensure proper MIME types
    Handler.extensions_map['.js'] = 'application/javascript'
    Handler.extensions_map['.html'] = 'text/html'
    Handler.extensions_map['.css'] = 'text/css'

    try:
        with socketserver.TCPServer((HOST, PORT), Handler) as httpd:
            print("=" * 60)
            print("🚀 Frontend Server Started")
            print("=" * 60)
            print(f"Server running at: http://{HOST}:{PORT}")
            print(f"Serving files from: {frontend_dir}")
            print()
            print("Available pages:")
            print(f"  - Main Chat:  http://{HOST}:{PORT}/index.html")
            print(f"  - Login:      http://{HOST}:{PORT}/login.html")
            print(f"  - Legacy:     http://{HOST}:{PORT}/index_legacy.html")
            print()
            print("Press Ctrl+C to stop the server")
            print("=" * 60)

            # Open browser automatically
            if '--no-browser' not in sys.argv:
                webbrowser.open(f'http://{HOST}:{PORT}/login.html')

            httpd.serve_forever()

    except KeyboardInterrupt:
        print("\n\n👋 Server stopped by user")
        sys.exit(0)
    except OSError as e:
        if e.errno == 10048 or 'Address already in use' in str(e):
            print(f"\n❌ Error: Port {PORT} is already in use!")
            print(f"Try a different port: set FRONTEND_PORT=3001 && python run_frontend.py")
        else:
            print(f"\n❌ Error starting server: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
