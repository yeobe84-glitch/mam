from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import os
import sys
import json
import shutil
import threading
import hmac
import hashlib
import secrets
import time
from datetime import datetime
from http import cookies
from urllib.parse import urlparse, parse_qs

# Render sets PORT automatically. Local fallback is 8027.
PORT = int(os.environ.get('PORT', '8027'))
HOST = '0.0.0.0'
ROOT = os.path.dirname(os.path.abspath(__file__))
TARGET = 'sandsu_attendance_ui_exam_message_bookfocus_v59.html'
ONLINE_TARGET = 'sandsu_online_mobile.html'
TENANTS = {'yeop', 'yeom', 'yeong'}
DEFAULT_TENANT = 'yeop'
# For Render Persistent Disk, set SANDSU_DATA_DIR to the disk mount path, for example /var/data.
DATA_DIR = os.environ.get('SANDSU_DATA_DIR') or os.environ.get('DATA_DIR') or os.path.join(ROOT, 'data')
BACKUP_DIR = os.path.join(DATA_DIR, 'backups')
THEMES_DIR = os.path.join(ROOT, 'themes')
MAX_BACKUPS = 14
SESSION_COOKIE = 'sandsu_session'
SESSION_TTL_SECONDS = 60 * 60 * 24 * 7
AUTH_PASSWORD = os.environ.get('SANDSU_PASSWORD') or os.environ.get('APP_PASSWORD') or '1234'
AUTH_SECRET = os.environ.get('SANDSU_SECRET') or os.environ.get('SECRET_KEY') or 'change-this-secret-on-render'
PUBLIC_PATHS = {'/login', '/api/ping'}
DEBUG_AUTH = (os.environ.get('SANDSU_DEBUG_AUTH', '1').lower() not in {'0', 'false', 'no', 'off'})


def _mask_secret(value):
    value = '' if value is None else str(value)
    if not value:
        return '<empty>'
    if len(value) <= 2:
        return '*' * len(value)
    return value[:2] + '***' + f'({len(value)})'


def debug_auth_log(*parts):
    if DEBUG_AUTH:
        print('[AUTH]', *parts, flush=True)


def _sign_session(value):
    return hmac.new(AUTH_SECRET.encode('utf-8'), value.encode('utf-8'), hashlib.sha256).hexdigest()


def make_session_value():
    issued_at = str(int(time.time()))
    nonce = secrets.token_urlsafe(16)
    value = f'{issued_at}:{nonce}'
    return f'{value}:{_sign_session(value)}'


def is_valid_session(raw_cookie):
    if not raw_cookie:
        return False
    try:
        jar = cookies.SimpleCookie(raw_cookie)
        morsel = jar.get(SESSION_COOKIE)
        if not morsel:
            return False
        token = morsel.value
        parts = token.split(':')
        if len(parts) != 3:
            return False
        issued_at, nonce, signature = parts
        value = f'{issued_at}:{nonce}'
        if not hmac.compare_digest(signature, _sign_session(value)):
            return False
        if int(time.time()) - int(issued_at) > SESSION_TTL_SECONDS:
            return False
        return True
    except Exception:
        return False



def ensure_data_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    os.makedirs(THEMES_DIR, exist_ok=True)
    # Ensure tenant files exist. Use academy_data.json as seed when available.
    # If DATA_DIR points to a Render Persistent Disk, also allow seeding from the bundled /data folder.
    seed = os.path.join(DATA_DIR, 'academy_data.json')
    bundled_seed = os.path.join(ROOT, 'data', 'academy_data.json')
    if not os.path.exists(seed) and os.path.exists(bundled_seed):
        try:
            shutil.copy2(bundled_seed, seed)
        except Exception:
            pass
    for tenant in TENANTS:
        path = tenant_data_file(tenant)
        if not os.path.exists(path):
            if os.path.exists(seed):
                try:
                    shutil.copy2(seed, path)
                    continue
                except Exception:
                    pass
            write_json_safely(tenant, {'version': 0, 'updated_at': datetime.now().isoformat(timespec='seconds')})


def tenant_data_file(tenant):
    if tenant not in TENANTS:
        tenant = DEFAULT_TENANT
    return os.path.join(DATA_DIR, f'{tenant}.json')


def tenant_backup_dir(tenant):
    path = os.path.join(BACKUP_DIR, tenant)
    os.makedirs(path, exist_ok=True)
    return path


def cleanup_old_backups(tenant):
    try:
        bdir = tenant_backup_dir(tenant)
        files = []
        for name in os.listdir(bdir):
            if not name.lower().endswith('.json'):
                continue
            path = os.path.join(bdir, name)
            if os.path.isfile(path):
                files.append((os.path.getmtime(path), path))
        files.sort(reverse=True)
        for _, old_path in files[MAX_BACKUPS:]:
            try:
                os.remove(old_path)
            except Exception:
                pass
    except Exception:
        pass


def create_startup_backup_once():
    ensure_data_dirs()
    today = datetime.now().strftime('%Y-%m-%d')
    for tenant in TENANTS:
        data_file = tenant_data_file(tenant)
        if not os.path.exists(data_file):
            cleanup_old_backups(tenant)
            continue
        backup_file = os.path.join(tenant_backup_dir(tenant), f'{tenant}_{today}.json')
        if not os.path.exists(backup_file):
            try:
                shutil.copy2(data_file, backup_file)
            except Exception:
                pass
        cleanup_old_backups(tenant)



def backup_current_data_before_save(tenant):
    try:
        data_file = tenant_data_file(tenant)
        if not os.path.exists(data_file):
            return
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup_file = os.path.join(tenant_backup_dir(tenant), f'{tenant}_{stamp}.json')
        shutil.copy2(data_file, backup_file)
        cleanup_old_backups(tenant)
    except Exception:
        pass

def normalize_payload(payload, tenant=None):
    if not isinstance(payload, dict):
        payload = {'data': payload}
    incoming_version = int(payload.get('version') or 0)
    current_version = 0
    if tenant in TENANTS:
        try:
            current_version = int(get_tenant_meta(tenant).get('version') or 0)
        except Exception:
            current_version = 0
    payload['version'] = max(incoming_version, current_version) + 1
    payload['updated_at'] = datetime.now().isoformat(timespec='seconds')
    return payload


def write_json_safely(tenant, payload):
    ensure_basic_dirs_only()
    data_file = tenant_data_file(tenant)
    tmp_file = data_file + '.tmp'
    with open(tmp_file, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, data_file)


def ensure_basic_dirs_only():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    os.makedirs(THEMES_DIR, exist_ok=True)


def read_tenant_data(tenant):
    ensure_data_dirs()
    data_file = tenant_data_file(tenant)
    if not os.path.exists(data_file):
        return None
    with open(data_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_tenant_meta(tenant):
    ensure_data_dirs()
    data_file = tenant_data_file(tenant)
    exists = os.path.exists(data_file)
    meta = {'exists': exists, 'tenant': tenant, 'version': 0, 'updated_at': '', 'file_mtime': 0}
    if not exists:
        return meta
    try:
        meta['file_mtime'] = os.path.getmtime(data_file)
    except Exception:
        pass
    try:
        with open(data_file, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            meta['version'] = int(payload.get('version') or 0)
            meta['updated_at'] = str(payload.get('updated_at') or '')
    except Exception:
        pass
    return meta


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class SandsuOnlineHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_message(self, format, *args):
        return

    def _is_authenticated(self):
        return is_valid_session(self.headers.get('Cookie'))

    def _is_public_path(self, clean_path):
        if clean_path in PUBLIC_PATHS:
            return True
        return clean_path.startswith('/api/ping')

    def _redirect_to_login(self):
        self.send_response(302)
        self.send_header('Location', '/login')
        self.end_headers()

    def _send_login_page(self, error=''):
        error_html = '<p class="error">비밀번호가 맞지 않습니다.</p>' if error else ''
        body = f'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>수앤수 로그인</title>
<style>
body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#f3f6fb;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#111827}}
.card{{width:min(360px,calc(100vw - 32px));background:white;border:1px solid #e5e7eb;border-radius:18px;box-shadow:0 18px 45px rgba(15,23,42,.12);padding:28px}}
h1{{font-size:22px;margin:0 0 8px}}
p{{margin:0 0 18px;color:#6b7280;font-size:14px}}
label{{display:block;font-size:13px;font-weight:700;margin-bottom:8px}}
input{{width:100%;box-sizing:border-box;border:1px solid #d1d5db;border-radius:12px;padding:13px 14px;font-size:17px;outline:none}}
input:focus{{border-color:#2563eb;box-shadow:0 0 0 3px rgba(37,99,235,.15)}}
button{{width:100%;margin-top:14px;border:0;border-radius:12px;background:#111827;color:white;font-weight:800;padding:13px 14px;font-size:16px;cursor:pointer}}
.error{{color:#dc2626;font-weight:700;margin:0 0 12px}}
</style>
</head>
<body>
<form class="card" method="post" action="/login">
<h1>수앤수 온라인</h1>
<p>접속 비밀번호를 입력하세요.</p>
{error_html}
<label for="password">비밀번호</label>
<input id="password" name="password" type="password" autocomplete="current-password" autofocus>
<button type="submit">로그인</button>
</form>
</body>
</html>'''.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _require_auth_for_json(self):
        if self._is_authenticated():
            return True
        self._send_json(401, {'ok': False, 'error': 'login required'})
        return False

    def _is_valid_api_password(self):
        # Program-side API authentication. The desktop app cannot rely on browser cookies,
        # so it sends the Render password in a header. Web access still uses the login cookie.
        header_password = self.headers.get('X-SANDSU-PASSWORD') or ''
        auth = self.headers.get('Authorization') or ''
        supplied = header_password
        source = 'X-SANDSU-PASSWORD' if header_password else 'missing'
        if auth.lower().startswith('bearer '):
            supplied = auth[7:].strip()
            source = 'Authorization Bearer'
        ok = bool(supplied) and hmac.compare_digest(str(supplied), str(AUTH_PASSWORD))
        debug_auth_log(
            self.command,
            urlparse(self.path).path,
            'source=' + source,
            'received=' + _mask_secret(supplied),
            'expected=' + _mask_secret(AUTH_PASSWORD),
            'ok=' + str(ok)
        )
        return ok

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


    def _send_online_html_for_tenant(self, tenant):
        html_path = os.path.join(ROOT, ONLINE_TARGET)
        if not os.path.exists(html_path):
            self.send_error(404, 'Online HTML target not found')
            return
        with open(html_path, 'r', encoding='utf-8') as f:
            html = f.read()
        patch = f"""
<script>
window.SANDSU_TENANT = {json.dumps(tenant)};
</script>
"""
        if '</head>' in html:
            html = html.replace('</head>', patch + '</head>', 1)
        else:
            html = patch + html
        body = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html_for_tenant(self, tenant):
        html_path = os.path.join(ROOT, TARGET)
        if not os.path.exists(html_path):
            self.send_error(404, 'HTML target not found')
            return
        with open(html_path, 'r', encoding='utf-8') as f:
            html = f.read()
        # Make the existing frontend use tenant-specific API without rewriting the large HTML file.
        patch = f"""
<script>
(function() {{
  window.SANDSU_TENANT = {json.dumps(tenant)};

  function rewriteTenantApiUrl(inputUrl) {{
    if (typeof inputUrl !== 'string') return inputUrl;
    if (inputUrl === '/api/load') return '/api/{tenant}/load';
    if (inputUrl === '/api/save') return '/api/{tenant}/save';
    if (inputUrl === '/api/ping') return '/api/{tenant}/ping';
    if (inputUrl.startsWith('/api/load?')) return inputUrl.replace('/api/load?', '/api/{tenant}/load?');
    if (inputUrl.startsWith('/api/save?')) return inputUrl.replace('/api/save?', '/api/{tenant}/save?');
    if (inputUrl.startsWith('/api/ping?')) return inputUrl.replace('/api/ping?', '/api/{tenant}/ping?');
    try {{
      const u = new URL(inputUrl, window.location.origin);
      if (u.origin === window.location.origin) {{
        if (u.pathname === '/api/load') u.pathname = '/api/{tenant}/load';
        else if (u.pathname === '/api/save') u.pathname = '/api/{tenant}/save';
        else if (u.pathname === '/api/ping') u.pathname = '/api/{tenant}/ping';
        return u.pathname + u.search + u.hash;
      }}
    }} catch (e) {{}}
    return inputUrl;
  }}

  if (window.fetch) {{
    const originalFetch = window.fetch.bind(window);
    window.fetch = function(input, init) {{
      if (typeof input === 'string') {{
        return originalFetch(rewriteTenantApiUrl(input), init);
      }}
      if (input && input.url) {{
        try {{
          const rewritten = rewriteTenantApiUrl(input.url);
          if (rewritten !== input.url) input = new Request(rewritten, input);
        }} catch (e) {{}}
      }}
      return originalFetch(input, init);
    }};
  }}

  if (window.XMLHttpRequest) {{
    const originalOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url) {{
      arguments[1] = rewriteTenantApiUrl(url);
      return originalOpen.apply(this, arguments);
    }};
  }}
}})();
</script>
"""
        if '</head>' in html:
            html = html.replace('</head>', patch + '</head>', 1)
        else:
            html = patch + html
        body = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        clean_path = urlparse(self.path).path.rstrip('/') or '/'
        if clean_path.startswith('/api/'):
            debug_auth_log('REQUEST', 'GET', clean_path)

        if clean_path == '/login':
            self._send_login_page()
            return

        if not self._is_public_path(clean_path) and not self._is_authenticated():
            # Desktop program APIs can authenticate with X-SANDSU-PASSWORD instead of browser cookie.
            parts_for_auth = clean_path.strip('/').split('/')
            program_get_allowed = (
                len(parts_for_auth) == 3
                and parts_for_auth[0] == 'api'
                and parts_for_auth[1] in TENANTS
                and parts_for_auth[2] in {'load', 'meta', 'ping'}
                and self._is_valid_api_password()
            )
            if not program_get_allowed:
                if clean_path.startswith('/api/'):
                    self._send_json(401, {'ok': False, 'error': 'login required'})
                else:
                    self._redirect_to_login()
                return

        if clean_path == '/':
            self.send_response(302)
            self.send_header('Location', f'/{DEFAULT_TENANT}')
            self.end_headers()
            return

        if clean_path.startswith('/legacy/') and clean_path.split('/')[-1] in TENANTS:
            self._send_html_for_tenant(clean_path.split('/')[-1])
            return

        if clean_path.strip('/') in TENANTS:
            self._send_online_html_for_tenant(clean_path.strip('/'))
            return

        # Tenant APIs: /api/yeop/load, /api/yeom/load, /api/yeong/load
        parts = clean_path.strip('/').split('/')
        if len(parts) == 3 and parts[0] == 'api' and parts[1] in TENANTS:
            tenant, action = parts[1], parts[2]
            if action == 'load':
                try:
                    data = read_tenant_data(tenant)
                    self._send_json(200, {'ok': True, 'tenant': tenant, 'data': data})
                except Exception as e:
                    self._send_json(500, {'ok': False, 'error': str(e)})
                return
            if action == 'meta':
                self._send_json(200, {'ok': True, 'tenant': tenant, 'meta': get_tenant_meta(tenant)})
                return
            if action == 'ping':
                self._send_json(200, {'ok': True, 'tenant': tenant, 'target': TARGET})
                return

        # Legacy local API fallback uses yeop.
        if clean_path == '/api/load':
            try:
                self._send_json(200, {'ok': True, 'tenant': DEFAULT_TENANT, 'data': read_tenant_data(DEFAULT_TENANT)})
            except Exception as e:
                self._send_json(500, {'ok': False, 'error': str(e)})
            return

        if clean_path == '/api/themes':
            ensure_data_dirs()
            try:
                files = []
                for name in os.listdir(THEMES_DIR):
                    if not name.lower().endswith('.css'):
                        continue
                    if '/' in name or '\\' in name or name.startswith('.'):
                        continue
                    path = os.path.join(THEMES_DIR, name)
                    if os.path.isfile(path):
                        files.append(name)
                files.sort(key=lambda x: (x != 'default.css', x.lower()))
                self._send_json(200, {'ok': True, 'files': files})
            except Exception as e:
                self._send_json(500, {'ok': False, 'error': str(e)})
            return

        if clean_path == '/api/ping':
            self._send_json(200, {'ok': True, 'tenant': DEFAULT_TENANT, 'target': TARGET})
            return

        # Disable remote shutdown on the online server.
        if clean_path == '/api/shutdown':
            self._send_json(403, {'ok': False, 'error': 'shutdown disabled online'})
            return

        super().do_GET()

    def do_POST(self):
        clean_path = urlparse(self.path).path.rstrip('/') or '/'
        if clean_path.startswith('/api/'):
            debug_auth_log('REQUEST', 'POST', clean_path)

        if clean_path == '/login':
            try:
                length = int(self.headers.get('Content-Length', '0') or '0')
                raw = self.rfile.read(length).decode('utf-8')
                params = parse_qs(raw)
                password = (params.get('password') or [''])[0]
                if hmac.compare_digest(password, AUTH_PASSWORD):
                    self.send_response(302)
                    self.send_header('Set-Cookie', f'{SESSION_COOKIE}={make_session_value()}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL_SECONDS}')
                    self.send_header('Location', f'/{DEFAULT_TENANT}')
                    self.end_headers()
                else:
                    self._send_login_page(error='1')
            except Exception:
                self._send_login_page(error='1')
            return

        parts = clean_path.strip('/').split('/')

        tenant = None
        if len(parts) == 3 and parts[0] == 'api' and parts[1] in TENANTS and parts[2] == 'save':
            tenant = parts[1]
        elif clean_path == '/api/save':
            tenant = DEFAULT_TENANT

        # /api/{teacher}/save can be called either by the logged-in web page(cookie)
        # or by the desktop program(X-SANDSU-PASSWORD header). Other APIs still require login.
        if clean_path.startswith('/api/'):
            if not (tenant and self._is_valid_api_password()) and not self._require_auth_for_json():
                return
        elif not self._is_authenticated():
            self._redirect_to_login()
            return

        if tenant:
            try:
                length = int(self.headers.get('Content-Length', '0') or '0')
                raw = self.rfile.read(length).decode('utf-8')
                payload = json.loads(raw) if raw else {}
                payload = normalize_payload(payload, tenant)
                backup_current_data_before_save(tenant)
                write_json_safely(tenant, payload)
                self._send_json(200, {'ok': True, 'tenant': tenant, 'version': payload.get('version'), 'updated_at': payload.get('updated_at')})
            except Exception as e:
                self._send_json(500, {'ok': False, 'error': str(e)})
            return

        self.send_error(404, 'Not Found')


if __name__ == '__main__':
    ensure_data_dirs()
    create_startup_backup_once()
    print(f'Serving on http://{HOST}:{PORT}')
    print('Tenant URLs: /yeop /yeom /yeong')
    print(f'Target: {TARGET}')
    print(f'Data dir: {DATA_DIR}')
    print('Auth: enabled. Set SANDSU_PASSWORD and SANDSU_SECRET on Render.')
    with ReusableThreadingHTTPServer((HOST, PORT), SandsuOnlineHandler) as httpd:
        httpd.serve_forever()
