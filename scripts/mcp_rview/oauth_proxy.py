#!/usr/bin/env python3
"""OAuth2 proxy for mcp-rview.

Reads CLIENT_ID and CLIENT_SECRET from the environment.
All other settings have defaults matching the tony-dell deployment.
"""
import base64
import hashlib
import hmac
import http.client
import http.server
import json
import os
import secrets
import socketserver
import sys
import time
import urllib.parse

ADDR = os.environ.get('OAUTH_PROXY_ADDR', '127.0.0.1')
PORT = int(os.environ.get('OAUTH_PROXY_PORT', '9004'))
UP = (
    os.environ.get('OAUTH_PROXY_UPSTREAM_ADDR', '127.0.0.1'),
    int(os.environ.get('OAUTH_PROXY_UPSTREAM_PORT', '9003')),
)
P = os.environ.get('OAUTH_PROXY_MCP_PATH', '/mcp')
ISS = os.environ.get('OAUTH_PROXY_ISSUER', 'https://tony-dell.taila0626a.ts.net')
TOK = ISS + '/oauth2/token'
AUTH = ISS + '/oauth2/token'

CID = os.environ['CLIENT_ID']
CS = os.environ['CLIENT_SECRET']
KS = secrets.token_urlsafe(32).encode()
TTL = 3600
CODE_TTL = 120

codes = {}  # code -> {client_id, redirect_uri, code_challenge, iat}


def b64u(s):
    return base64.urlsafe_b64encode(s).decode().rstrip('=')


def pkce_verify(verifier, challenge):
    """S256 code challenge verification."""
    h = hashlib.sha256(verifier.encode()).digest()
    return b64u(h) == challenge


def issue():
    i = int(time.time())
    return base64.urlsafe_b64encode(
        json.dumps({
            'c': CID,
            'i': i,
            's': hmac.new(KS, f'{CID}:{i}'.encode(), hashlib.sha256).hexdigest(),
        }).encode()
    ).decode().rstrip('=')


def verify(tok):
    try:
        tok += '=' * (-len(tok) % 4)
        d = json.loads(base64.urlsafe_b64decode(tok.encode()).decode())
        if d.get('c') != CID or not isinstance(d.get('i'), int) or int(time.time()) - d['i'] > TTL:
            return False
        return hmac.compare_digest(d.get('s', ''), hmac.new(KS, f"{CID}:{d['i']}".encode(), hashlib.sha256).hexdigest())
    except Exception:
        return False


class H(http.server.BaseHTTPRequestHandler):
    def _j(self, c, b):
        self.send_response(c)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _b(self):
        l = self.headers.get('Content-Length')
        return self.rfile.read(int(l)) if l else b''

    def _q(self):
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

    def _a(self):
        a = self.headers.get('Authorization', '')
        if not a.startswith('Bearer ') or not verify(a[7:]):
            self._j(401, json.dumps({'error': 'invalid_token'}).encode())
            return
        return a[7:]

    def _p(self, m, b):
        c = http.client.HTTPConnection(*UP)
        h = {k: v for k, v in self.headers.items() if k.lower() not in ('host', 'authorization', 'content-length')}
        h['Content-Length'] = str(len(b))
        c.request(m, P, body=b, headers=h)
        r = c.getresponse()
        d = r.read()
        c.close()
        self.send_response(r.status)
        for k, v in r.getheaders():
            if k.lower() not in ('transfer-encoding', 'content-length'):
                self.send_header(k, v)
        self.send_header('Content-Length', str(len(d)))
        self.end_headers()
        self.wfile.write(d)

    def _redirect(self, url):
        self.send_response(302)
        self.send_header('Location', url)
        self.send_header('Content-Length', '0')
        self.end_headers()
        self.wfile.write(b'')

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if self.path == '/.well-known/oauth-authorization-server':
            self._j(200, json.dumps({
                'issuer': ISS,
                'authorization_endpoint': AUTH,
                'token_endpoint': TOK,
                'token_endpoint_auth_methods_supported': ['client_secret_post'],
                'grant_types_supported': ['client_credentials', 'authorization_code'],
                'response_types_supported': ['token', 'code'],
                'response_modes_supported': ['query'],
                'code_challenge_methods_supported': ['S256'],
            }).encode())
            return

        if parsed.path in ('/oauth2/token', '/oauth2/authorize'):
            q = self._q()
            if q.get('response_type', [''])[0] == 'code':
                if not hmac.compare_digest(q.get('client_id', [''])[0], CID):
                    self._j(401, json.dumps({'error': 'invalid_client'}).encode())
                    return
                redirect_uri = q.get('redirect_uri', [''])[0]
                if not redirect_uri:
                    self._j(400, json.dumps({'error': 'invalid_request'}).encode())
                    return
                code = secrets.token_urlsafe(32)
                codes[code] = {
                    'client_id': CID,
                    'redirect_uri': redirect_uri,
                    'code_challenge': q.get('code_challenge', [''])[0],
                    'iat': time.time(),
                }
                state = q.get('state', [''])[0]
                cb = redirect_uri + ('&' if '?' in redirect_uri else '?') + urllib.parse.urlencode({'code': code, 'state': state})
                self._redirect(cb)
                return

        if self.path == P and self._a():
            self._p('GET', b'')
        else:
            self._j(404, json.dumps({'error': 'not_found'}).encode())

    def do_POST(self):
        if self.path == '/oauth2/token':
            q = urllib.parse.parse_qs(self._b().decode('utf-8', 'replace'))
            grant = q.get('grant_type', [''])[0]

            if grant == 'client_credentials':
                if (
                    not hmac.compare_digest(q.get('client_id', [''])[0], CID)
                    or not hmac.compare_digest(q.get('client_secret', [''])[0], CS)
                ):
                    self._j(401, json.dumps({'error': 'invalid_client'}).encode())
                    return
                self._j(200, json.dumps({'access_token': issue(), 'token_type': 'Bearer', 'expires_in': TTL}).encode())
                return

            if grant == 'authorization_code':
                code = q.get('code', [''])[0]
                info = codes.pop(code, None)
                if not info or time.time() - info['iat'] > CODE_TTL:
                    self._j(400, json.dumps({'error': 'invalid_grant'}).encode())
                    return
                if not hmac.compare_digest(q.get('client_id', [''])[0], info['client_id']):
                    self._j(401, json.dumps({'error': 'invalid_client'}).encode())
                    return
                if q.get('redirect_uri', [''])[0] != info['redirect_uri']:
                    self._j(400, json.dumps({'error': 'invalid_grant'}).encode())
                    return
                verifier = q.get('code_verifier', [''])[0]
                if info['code_challenge'] and not pkce_verify(verifier, info['code_challenge']):
                    self._j(400, json.dumps({'error': 'invalid_grant'}).encode())
                    return
                self._j(200, json.dumps({'access_token': issue(), 'token_type': 'Bearer', 'expires_in': TTL}).encode())
                return

            self._j(400, json.dumps({'error': 'unsupported_grant_type'}).encode())
            return

        if self.path == P and self._a():
            self._p('POST', self._b())
        else:
            self._j(404, json.dumps({'error': 'not_found'}).encode())

    def do_PUT(self):
        self._a() and self._p('PUT', self._b())

    def do_DELETE(self):
        self._a() and self._p('DELETE', b'')

    def do_PATCH(self):
        self._a() and self._p('PATCH', self._b())


def main():
    os.makedirs('/home/tony/.config', exist_ok=True)
    t = issue()
    c = {
        'client_id': CID,
        'client_secret': CS,
        'access_token': t,
        'token_endpoint': TOK,
        'well_known_url': ISS + '/.well-known/oauth-authorization-server',
    }
    with open('/tmp/mcp-rview-oauth-creds.json', 'w') as f:
        json.dump(c, f)
    print(f'client_id={CID}')
    print(f'client_secret=***')
    print(f'access_token={t}')
    sys.stdout.flush()
    socketserver.TCPServer((ADDR, PORT), H).serve_forever()


if __name__ == '__main__':
    main()
