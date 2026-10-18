"""Run with: .venv/Scripts/python.exe -m backend"""
import argparse
import os
import secrets
from pathlib import Path

import uvicorn

from .api import create_app


ROOT = Path(__file__).resolve().parents[1]


def admin_token(root=ROOT):
    token = os.environ.get('RELAY_ADMIN_TOKEN', '').strip()
    if token:
        return token
    token_file = root / '.local' / 'admin-token.txt'
    token_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Exclusive creation avoids overwriting an existing admin token on restart.
        with token_file.open('x', encoding='utf-8') as stream:
            stream.write(secrets.token_urlsafe(32))
    except FileExistsError:
        pass
    print(f'Administrator token file: {token_file}', flush=True)
    return token_file.read_text(encoding='utf-8').strip()


def main():
    parser = argparse.ArgumentParser(description='Relay collaboration backend')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--db', type=Path, default=ROOT / 'data' / 'relay.db')
    args = parser.parse_args()
    app = create_app(args.db, admin_token())
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == '__main__':
    main()
