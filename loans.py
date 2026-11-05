"""Loan application intake and staff handling for the isolated UACredit service."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import hashlib, hmac, json, os, re, secrets, sqlite3, time
from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for

SERVICES = {'car': '汽車貸款', 'property': '物業貸款'}
STATUSES = {'new': '待處理', 'in_progress': '跟進中', 'completed': '已完成'}
CONSENT_VERSION = 'loan-basic-v1'


def hong_kong_time(value):
    return datetime.fromisoformat(value).astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')


def install_loans(app, data, config, protect):
    bp = Blueprint('loan_applications', __name__)
    enabled = os.environ.get('UACREDIT_APPLICATIONS_ENABLED') == '1'
    app.extensions['loan_applications_enabled'] = enabled
    path = Path(data) / 'loan_applications.sqlite3'
    if not path.exists():
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        except FileExistsError:
            pass

    @contextmanager
    def db():
        conn = sqlite3.connect(path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    with db() as conn:
        conn.execute('PRAGMA secure_delete = ON')
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS loan_applications (
                reference TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                service TEXT NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL,
                amount TEXT NOT NULL, details TEXT NOT NULL, consent_version TEXT NOT NULL,
                status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
                idempotency_digest TEXT NOT NULL UNIQUE, payload_digest TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS loan_application_audit (
                id INTEGER PRIMARY KEY, at TEXT NOT NULL, reference TEXT NOT NULL,
                actor TEXT NOT NULL, action TEXT NOT NULL, old_status TEXT, new_status TEXT
            );
            CREATE TABLE IF NOT EXISTS loan_application_attempts (client_digest TEXT NOT NULL, at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS loan_attempts_client_time ON loan_application_attempts(client_digest,at);
            CREATE INDEX IF NOT EXISTS loan_application_created ON loan_applications(created_at DESC);
        ''')

    def digest(kind, value):
        return hmac.new(str(config['secret_key']).encode(), (kind + ':' + value).encode(), hashlib.sha256).hexdigest()

    def error(message, status):
        return jsonify(success=False, error=message), status

    def same_origin():
        origin = request.headers.get('Origin', '')
        if not origin or request.headers.get('Sec-Fetch-Site', '').lower() in {'cross-site', 'same-site'}:
            return False
        try:
            parsed = urlsplit(origin)
            current = urlsplit(request.host_url)
            return (parsed.scheme in {'http', 'https'} and not parsed.username and not parsed.password
                    and parsed.path in {'', '/'} and not parsed.query and not parsed.fragment
                    and parsed.scheme == current.scheme and parsed.netloc.lower() == current.netloc.lower())
        except ValueError:
            return False

    def rate_limit():
        now = time.time()
        client = digest('ip', request.remote_addr or 'unknown')
        with db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('DELETE FROM loan_application_attempts WHERE at < ?', (now - 600,))
            count = conn.execute('SELECT count(*) FROM loan_application_attempts WHERE client_digest=? AND at>=?', (client, now-600)).fetchone()[0]
            if count >= 10:
                return False
            conn.execute('INSERT INTO loan_application_attempts VALUES (?,?)', (client, now))
        return True

    def validated(value):
        if not isinstance(value, dict) or set(value) - {'service', 'name', 'phone', 'amount', 'details', 'consent'}:
            return None, '請檢查申請資料。'
        service, name, phone = value.get('service'), value.get('name'), value.get('phone')
        amount, details = value.get('amount', ''), value.get('details', '')
        if not isinstance(service, str) or service not in SERVICES or not isinstance(name, str) or not isinstance(phone, str) or not isinstance(amount, str) or not isinstance(details, str):
            return None, '請檢查申請資料。'
        name, phone, amount, details = name.strip(), phone.strip(), amount.strip(), details.strip()
        try:
            name.encode('utf-8'); details.encode('utf-8')
        except UnicodeEncodeError:
            return None, '請檢查申請資料。'
        if not 1 <= len(name) <= 80 or any(ord(c) < 32 or ord(c) == 127 for c in name):
            return None, '請填寫姓名。'
        if not re.fullmatch(r'(?:\+852[ -]?)?[2-9][0-9 -]{7,12}', phone):
            return None, '請填寫有效的香港電話號碼。'
        phone = re.sub(r'[ -]', '', phone)
        if phone.startswith('+852'):
            phone = phone[4:]
        if not re.fullmatch(r'[2-9][0-9]{7}', phone):
            return None, '請填寫有效的香港電話號碼。'
        if amount:
            if not re.fullmatch(r'[0-9]{1,9}(?:\.[0-9]{1,2})?', amount):
                return None, '請填寫有效的貸款金額。'
            try:
                if Decimal(amount) > Decimal('100000000'):
                    return None, '請填寫有效的貸款金額。'
            except InvalidOperation:
                return None, '請填寫有效的貸款金額。'
        if len(details) > 1000 or any(ord(c) < 32 and c not in '\n\r\t' for c in details):
            return None, '補充資料請填寫不多於 1000 字。'
        if value.get('consent') is not True:
            return None, '請先閱讀並同意個人資料使用安排。'
        return {'service': service, 'name': name, 'phone': phone, 'amount': amount, 'details': details}, None

    @bp.get('/loan-applications/status')
    def status():
        response = jsonify(enabled=enabled)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @bp.post('/loan-applications/')
    def submit():
        if not enabled:
            return error('網上申請暫未開通，請直接聯絡我們。', 503)
        if not same_origin():
            return error('無法確認申請來源，請重新開啟頁面再試。', 403)
        if request.mimetype != 'application/json':
            return error('請檢查申請資料。', 415)
        request.max_content_length = 8192
        if request.content_length is not None and request.content_length > 8192:
            return error('申請資料過長，請檢查後再試。', 413)
        key = request.headers.get('Idempotency-Key', '')
        if not re.fullmatch(r'[0-9a-f]{32}', key):
            return error('無法確認本次申請，請重新開啟頁面再試。', 400)
        try:
            value = request.get_json(silent=True)
        except Exception:
            return error('申請資料過長，請檢查後再試。', 413)
        try:
            permitted = rate_limit()
        except sqlite3.Error:
            return error('暫時未能提交，請稍後再試。', 503)
        fields, problem = validated(value)
        if problem:
            if not permitted:
                return error('提交次數較多，請稍後再試。', 429)
            return error(problem, 400)
        payload_digest = digest('payload', json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
        key_digest = digest('idempotency', key)
        now = datetime.now(timezone.utc).isoformat()
        try:
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE')
                existing = conn.execute('SELECT reference,payload_digest FROM loan_applications WHERE idempotency_digest=?', (key_digest,)).fetchone()
                if existing:
                    if not hmac.compare_digest(existing['payload_digest'], payload_digest):
                        return error('申請資料已更改，請重新提交。', 409)
                    return jsonify(success=True, reference=existing['reference']), 200
                if not permitted:
                    return error('提交次數較多，請稍後再試。', 429)
                reference = 'UA-' + secrets.token_hex(8).upper()
                conn.execute('INSERT INTO loan_applications VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (reference, now, now, fields['service'], fields['name'], fields['phone'], fields['amount'], fields['details'], CONSENT_VERSION, 'new', 1, key_digest, payload_digest))
                conn.execute('INSERT INTO loan_application_audit (at,reference,actor,action) VALUES (?,?,?,?)', (now, reference, 'visitor', 'submitted'))
        except sqlite3.Error:
            return error('暫時未能提交，請稍後再試。', 503)
        return jsonify(success=True, reference=reference), 201

    @bp.get('/admin/loan-applications/')
    @protect
    def index():
        page = request.args.get('page', 1, type=int)
        page = max(1, min(page, 100000))
        with db() as conn:
            rows = conn.execute('SELECT reference,created_at,service,name,phone,status,revision FROM loan_applications ORDER BY created_at DESC LIMIT 26 OFFSET ?', ((page-1)*25,)).fetchall()
            conn.execute('INSERT INTO loan_application_audit (at,reference,actor,action) VALUES (?,?,?,?)', (datetime.now(timezone.utc).isoformat(), '', config['username'], 'listed'))
        return render_template('loan_applications.html', applications=rows[:25], more=len(rows)>25, page=page, services=SERVICES, statuses=STATUSES, hong_kong_time=hong_kong_time)

    @bp.get('/admin/loan-applications/<reference>')
    @protect
    def detail(reference):
        if not re.fullmatch(r'UA-[0-9A-F]{16}', reference):
            abort(404)
        with db() as conn:
            record = conn.execute('SELECT * FROM loan_applications WHERE reference=?', (reference,)).fetchone()
            if record:
                conn.execute('INSERT INTO loan_application_audit (at,reference,actor,action) VALUES (?,?,?,?)', (datetime.now(timezone.utc).isoformat(), reference, config['username'], 'viewed'))
        if not record:
            abort(404)
        return render_template('loan_application_detail.html', application=record, services=SERVICES, statuses=STATUSES, hong_kong_time=hong_kong_time)

    @bp.post('/admin/loan-applications/<reference>/status')
    @protect
    def update(reference):
        if not re.fullmatch(r'UA-[0-9A-F]{16}', reference):
            abort(404)
        status = request.form.get('status', '')
        revision = request.form.get('revision', '')
        if status not in STATUSES or not revision.isdigit():
            abort(400, '請選擇有效的處理狀態。')
        with db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            record = conn.execute('SELECT status,revision FROM loan_applications WHERE reference=?', (reference,)).fetchone()
            if not record:
                abort(404)
            if record['revision'] != int(revision):
                abort(409, '這份申請已更新，請重新開啟後再試。')
            if record['status'] != status:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute('UPDATE loan_applications SET status=?,updated_at=?,revision=revision+1 WHERE reference=?', (status, now, reference))
                conn.execute('INSERT INTO loan_application_audit (at,reference,actor,action,old_status,new_status) VALUES (?,?,?,?,?,?)', (now, reference, config['username'], 'status_changed', record['status'], status))
        flash('處理狀態已更新。')
        return redirect(url_for('loan_applications.detail', reference=reference))

    app.register_blueprint(bp)
