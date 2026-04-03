from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from server.tls import default_tls_dir, ensure_dev_tls_materials


def main() -> None:
    parser = argparse.ArgumentParser(description='Run the COMP3334 IM server over HTTPS/WSS.')
    parser.add_argument('--host', default='127.0.0.1', help='Bind host for the HTTPS server.')
    parser.add_argument('--port', type=int, default=8443, help='Bind port for the HTTPS server.')
    parser.add_argument(
        '--cert-dir',
        default=str(default_tls_dir()),
        help='Directory where the development CA and server certificates are stored.',
    )
    parser.add_argument(
        '--extra-hostname',
        action='append',
        default=[],
        help='Additional DNS names or IPs to place into the server certificate SAN list.',
    )
    parser.add_argument('--reload', action='store_true', help='Enable uvicorn auto-reload.')
    args = parser.parse_args()

    cert_dir = Path(args.cert_dir).expanduser().resolve()
    tls_material = ensure_dev_tls_materials(cert_dir, hostnames=[args.host, *args.extra_hostname])

    print(f'TLS CA certificate: {tls_material.ca_cert_path}')
    print(f'TLS server certificate: {tls_material.server_cert_path}')
    print(f'TLS server key: {tls_material.server_key_path}')
    print(f'Starting HTTPS/WSS server on https://{args.host}:{args.port}')

    uvicorn.run(
        'server.main:app',
        host=args.host,
        port=args.port,
        reload=args.reload,
        ssl_certfile=str(tls_material.server_cert_path),
        ssl_keyfile=str(tls_material.server_key_path),
    )


if __name__ == '__main__':
    main()
