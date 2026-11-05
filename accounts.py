"""Customer accounts and provider-authoritative verification, isolated from lending."""
from concurrent.futures import ThreadPoolExecutor,wait
from contextlib import contextmanager
from datetime import datetime,timezone
from functools import wraps
from pathlib import Path
import hashlib,json,os,re,secrets,sqlite3,threading,time,uuid
from flask import Blueprint,abort,flash,g,redirect,render_template,request,session,url_for
from werkzeug.security import generate_password_hash,check_password_hash
from identity_providers import TwilioVerify,SumsubIdentity,ProviderUnavailable,ProviderFailure

def normalize(kind,value):
    value=value.strip()
    if kind=='email':
        if len(value)>254 or not re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+',value):raise ValueError('請填寫有效的電郵地址。')
        return value.lower()
    if kind=='phone':
        digits=re.sub(r'[\s()-]','',value)
        if re.fullmatch(r'[4-9]\d{7}',digits):digits='+852'+digits
        if not re.fullmatch(r'\+852[4-9]\d{7}',digits):raise ValueError('請填寫8位香港手機號碼，或加上 +852。')
        return digits
    raise ValueError('請選擇手機或電郵。')

def install_accounts(app,data,admin_config,providers=None):
    path=Path(os.environ.get('UACREDIT_IDENTITY_CONFIG','/etc/uacredit/identity.json'))
    cfg=json.loads(path.read_text()) if path.exists() else {}
    otp,kyc=providers or (TwilioVerify(cfg.get('twilio',{})),SumsubIdentity(cfg.get('sumsub',{})))
    bp=Blueprint('accounts',__name__)
    @bp.app_context_processor
    def verification_channels():
        return {'email_ready':otp.supports('email'),'whatsapp_ready':otp.supports('phone')}
    @contextmanager
    def db():
        conn=sqlite3.connect(data/'accounts.sqlite3',timeout=20);conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA secure_delete=ON')
        try:
            with conn:yield conn
        finally:conn.close()
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS customers(id TEXT PRIMARY KEY,email TEXT UNIQUE,phone TEXT UNIQUE,password_hash TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,email_verified INTEGER NOT NULL DEFAULT 0,phone_verified INTEGER NOT NULL DEFAULT 0,auth_version INTEGER NOT NULL DEFAULT 1,kyc_status TEXT NOT NULL DEFAULT 'not_started',kyc_at REAL NOT NULL DEFAULT 0,created_at TEXT NOT NULL,consent_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS account_attempts(key TEXT,at REAL);
        CREATE TABLE IF NOT EXISTS challenges(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,contact TEXT NOT NULL,kind TEXT NOT NULL,purpose TEXT NOT NULL,expires REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,consumed INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS pending_registrations(id TEXT PRIMARY KEY,contact TEXT NOT NULL,kind TEXT NOT NULL,password_hash TEXT NOT NULL,consent_at TEXT NOT NULL,expires REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS identity_events(digest TEXT PRIMARY KEY,at REAL,user_id TEXT,status TEXT);
        CREATE TABLE IF NOT EXISTS account_audit(at TEXT,actor TEXT,action TEXT,subject TEXT);
        ''')
        c.execute('DELETE FROM pending_registrations WHERE expires<?',(time.time(),))
        c.execute('DELETE FROM challenges WHERE expires<?',(time.time(),))
    dummy_hash=generate_password_hash(secrets.token_urlsafe(24))
    def audit(c,action,subject=None,actor=None):c.execute('INSERT INTO account_audit VALUES (?,?,?,?)',(datetime.now(timezone.utc).isoformat(),actor or session.get('customer_id','anonymous'),action,subject))
    def limit(key,maximum,seconds,record=True):
        # Store only a keyed hash of the contact/IP rate-limit key.
        key=hashlib.sha256((admin_config['secret_key']+key).encode()).hexdigest()
        with db() as c:
            c.execute('BEGIN IMMEDIATE');now=time.time()
            c.execute('DELETE FROM account_attempts WHERE at < ?',(now-86400,))
            c.execute('DELETE FROM challenges WHERE expires<?',(now,));c.execute('DELETE FROM pending_registrations WHERE expires<?',(now,))
            count=c.execute('SELECT COUNT(*) FROM account_attempts WHERE key=? AND at>?',(key,now-seconds)).fetchone()[0]
            if count>=maximum:abort(429,'操作次數較多，請稍後再試。')
            if record:c.execute('INSERT INTO account_attempts VALUES (?,?)',(key,now))
    def customer():
        ident=session.get('customer_id')
        if not ident:return None
        with db() as c:r=c.execute('SELECT * FROM customers WHERE id=?',(ident,)).fetchone()
        if not r or not r['enabled'] or r['auth_version']!=session.get('customer_version'):
            session.pop('customer_id',None);session.pop('customer_version',None);return None
        return r
    def logged_in(fn):
        @wraps(fn)
        def wrapped(*a,**kw):
            g.customer=customer()
            if g.customer is None:return redirect(url_for('accounts.login'))
            return fn(*a,**kw)
        return wrapped
    def staff(fn):
        @wraps(fn)
        def wrapped(*a,**kw):
            if not session.get('admin'):return redirect('/admin/login')
            return fn(*a,**kw)
        return wrapped
    def signed_in(r):
        session.clear();session['customer_id']=r['id'];session['customer_version']=r['auth_version'];session.permanent=True
    def form_error(message):flash(message);return render_template('accounts/auth.html',mode=request.endpoint.split('.')[-1],otp_ready=otp.ready),400
    sender=ThreadPoolExecutor(max_workers=2,thread_name_prefix='uacredit-otp');deliveries=set();deliveries_lock=threading.Lock()
    def deliver(contact,kind,ident):
        try:otp.send(contact,kind)
        except Exception:
            # Failed delivery downgrades the challenge so no later provider check can approve it.
            with db() as c:c.execute("UPDATE challenges SET user_id='dummy:'||id WHERE id=?",(ident,))
    def drain(timeout=None):
        with deliveries_lock:pending=set(deliveries)
        wait(pending,timeout=timeout)
    def anonymous_challenge(contact,kind,purpose,ident):
        # Known and unknown contacts return without waiting on the provider, so response time
        # does not reveal account presence. The dummy identity is never sent to the provider.
        with db() as c:r=c.execute('SELECT id FROM customers WHERE (email=? OR phone=?) AND enabled=1',(contact,contact)).fetchone()
        user_id=r['id'] if r else 'dummy:'+ident
        with db() as c:
            c.execute('DELETE FROM challenges WHERE expires<?',(time.time(),))
            c.execute('DELETE FROM challenges WHERE contact=? AND purpose=?',(contact,purpose))
            c.execute('INSERT INTO challenges(id,user_id,contact,kind,purpose,expires) VALUES (?,?,?,?,?,?)',(ident,user_id,contact,kind,purpose,time.time()+600))
            if purpose=='reset' and not user_id.startswith('dummy:'):audit(c,'password_reset_requested',user_id)
        if r:
            future=sender.submit(deliver,contact,kind,ident)
            with deliveries_lock:deliveries.add(future)
            future.add_done_callback(lambda f:(deliveries_lock.acquire(),deliveries.discard(f),deliveries_lock.release()))
    def redeem(ident,purpose,code,user_id=None,check=None):
        # Count the attempt in a short transaction, then ask the provider without holding
        # the SQLite write lock. Returns (None, False) for a missing or spent challenge.
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM challenges WHERE id=? AND purpose=?',(ident,purpose)).fetchone()
            if not row or row['consumed'] or row['expires']<time.time() or row['attempts']>=5 or (user_id and row['user_id']!=user_id):return None,False
            c.execute('UPDATE challenges SET attempts=attempts+1 WHERE id=?',(row['id'],))
        return row,(check or anonymous_check)(row,code)
    def consume(c,row):
        # Only one request may redeem a challenge, even when two arrive with the same code.
        return c.execute('UPDATE challenges SET consumed=1 WHERE id=? AND consumed=0 AND expires>?',(row['id'],time.time())).rowcount==1
    def anonymous_check(row,code):
        if row['user_id'].startswith('dummy:'):return False
        try:return otp.check(row['contact'],code)
        except (ProviderUnavailable,ProviderFailure):return False
    @bp.route('/account/register/',methods=['GET','POST'])
    def register():
        if request.method=='POST':
            if not otp.ready:abort(503,'手機及電郵驗證服務尚未開通，暫時未能建立帳戶。')
            limit('register:'+str(request.remote_addr),8,3600)
            try:kind=request.form.get('kind','email');contact=normalize(kind,request.form.get('contact',''))
            except ValueError as e:return form_error(str(e))
            if not otp.supports(kind):return form_error('所選驗證方式尚未開通，請選擇已開通的方式。')
            password=request.form.get('password','')
            if not 12<=len(password)<=128 or password!=request.form.get('confirm',''):return form_error('請設定12至128個字元的密碼，並確認兩次輸入相同。')
            if request.form.get('consent')!='yes':return form_error('請閱讀並同意客戶帳戶的私隱說明。')
            limit('register-contact:'+contact,1,60)
            with db() as c:
                c.execute('DELETE FROM pending_registrations WHERE expires<?',(time.time(),))
            try:otp.send(contact,kind)
            except (ProviderUnavailable,ProviderFailure) as e:abort(503,str(e))
            ident=secrets.token_urlsafe(24);stamp=datetime.now(timezone.utc).isoformat()
            with db() as c:
                c.execute('DELETE FROM pending_registrations WHERE id=?',(session.get('registration_id'),))
                c.execute('INSERT INTO pending_registrations(id,contact,kind,password_hash,consent_at,expires) VALUES (?,?,?,?,?,?)',(ident,contact,kind,generate_password_hash(password),stamp,time.time()+600))
            session['registration_id']=ident
            flash('已提交驗證碼發送請求，請在10分鐘內完成開戶。')
            return redirect(url_for('accounts.register_confirm'))
        return render_template('accounts/auth.html',mode='register',otp_ready=otp.ready)
    @bp.route('/account/register/confirm/',methods=['GET','POST'])
    def register_confirm():
        error=None
        ident=session.get('registration_id')
        with db() as c:row=c.execute('SELECT * FROM pending_registrations WHERE id=?',(ident,)).fetchone()
        if not row or row['expires']<time.time() or row['attempts']>=5:
            with db() as c:c.execute('DELETE FROM pending_registrations WHERE id=?',(ident,))
            session.pop('registration_id',None);abort(400,'驗證已過期或失效，請重新開始開戶。')
        if request.method=='POST':
            if not otp.ready:abort(503,'驗證服務暫時未能使用，請稍後再試。')
            code=request.form.get('code','')
            if not re.fullmatch(r'\d{4,10}',code):abort(400,'請填寫有效的驗證碼。')
            with db() as c:
                c.execute('BEGIN IMMEDIATE')
                updated=c.execute('UPDATE pending_registrations SET attempts=attempts+1 WHERE id=? AND expires>? AND attempts<5',(ident,time.time())).rowcount
            if not updated:abort(400,'驗證已過期或失效，請重新開始開戶。')
            try:approved=otp.check(row['contact'],code)
            except (ProviderUnavailable,ProviderFailure) as e:abort(503,str(e))
            if approved:
                user_id=str(uuid.uuid4());stamp=datetime.now(timezone.utc).isoformat()
                try:
                    with db() as c:
                        c.execute('BEGIN IMMEDIATE')
                        pending=c.execute('SELECT * FROM pending_registrations WHERE id=? AND expires>?',(ident,time.time())).fetchone()
                        if not pending:abort(400,'驗證已過期或失效，請重新開始開戶。')
                        c.execute('INSERT INTO customers(id,email,phone,password_hash,email_verified,phone_verified,created_at,consent_at) VALUES (?,?,?,?,?,?,?,?)',(user_id,pending['contact'] if pending['kind']=='email' else None,pending['contact'] if pending['kind']=='phone' else None,pending['password_hash'],int(pending['kind']=='email'),int(pending['kind']=='phone'),stamp,pending['consent_at']))
                        c.execute('DELETE FROM pending_registrations WHERE id=?',(ident,));audit(c,'register',user_id)
                        user=c.execute('SELECT * FROM customers WHERE id=?',(user_id,)).fetchone()
                except sqlite3.IntegrityError:abort(409,'未能建立帳戶。請嘗試登入，或使用「忘記密碼」。')
                signed_in(user);flash('帳戶已建立，聯絡資料已驗證。');return redirect(url_for('accounts.profile'))
            error='驗證碼不正確，請重新輸入。'
        return render_template('accounts/register_confirm.html',kind=row['kind'],error=error)
    @bp.route('/account/login/',methods=['GET','POST'])
    def login():
        if request.method=='POST':
            # Only failed attempts count, so customers behind one network address are not locked out by each other's sign-ins.
            ip_key='login:'+str(request.remote_addr);limit(ip_key,15,600,record=False)
            raw=request.form.get('contact','');kind='email' if '@' in raw else 'phone'
            try:contact=normalize(kind,raw)
            except ValueError:contact='invalid'
            with db() as c:r=c.execute('SELECT * FROM customers WHERE email=? OR phone=?',(contact,contact)).fetchone()
            good=check_password_hash(r['password_hash'] if r else dummy_hash,request.form.get('password','')[:129])
            if not r or not good or not r['enabled']:
                limit(ip_key,15,600)
                return form_error('手機、電郵或密碼不正確，或帳戶暫時未能使用。')
            signed_in(r)
            with db() as c:audit(c,'login',r['id'])
            return redirect(url_for('accounts.profile'))
        return render_template('accounts/auth.html',mode='login')
    @bp.post('/account/logout/')
    def logout():session.clear();return redirect(url_for('accounts.login'))
    @bp.route('/account/code-login/',methods=['GET','POST'])
    def code_login():
        if request.method=='POST':
            if not otp.ready:abort(503,'手機及電郵驗證服務尚未開通，請先使用密碼登入。')
            if request.form.get('phase','send')=='send':
                raw=request.form.get('contact','');kind='email' if '@' in raw else 'phone'
                try:contact=normalize(kind,raw)
                except ValueError as e:abort(400,str(e))
                if not otp.supports(kind):abort(503,'所選驗證方式尚未開通，請先使用密碼登入。')
                limit('code-login-ip:'+str(request.remote_addr),5,3600);limit('code-login-contact:'+contact,1,60)
                ident=secrets.token_urlsafe(24)
                anonymous_challenge(contact,kind,'login',ident)
                session['login_challenge']=ident
                flash('如聯絡資料符合條件，我們會嘗試發出登入驗證碼。')
            else:
                code=request.form.get('code','')
                if not re.fullmatch(r'\d{4,10}',code):abort(400,'請填寫有效的驗證碼。')
                row,approved=redeem(session.get('login_challenge'),'login',code)
                if row is None:abort(400,'驗證碼已失效，請重新取得。')
                if approved:
                    column='phone' if row['kind']=='phone' else 'email'
                    with db() as c:
                        c.execute('BEGIN IMMEDIATE')
                        user=c.execute(f'SELECT * FROM customers WHERE id=? AND enabled=1 AND {column}=?',(row['user_id'],row['contact'])).fetchone()
                        if user and consume(c,row):
                            c.execute(f'UPDATE customers SET {column}_verified=1 WHERE id=?',(user['id'],));audit(c,'code_login',user['id'])
                        else:user=None
                    if user:
                        signed_in(user);return redirect(url_for('accounts.profile'))
                flash('驗證碼不正確或服務暫時未能使用，請重新輸入或稍後再試。')
        return render_template('accounts/code_login.html',ready=otp.ready,confirm=bool(session.get('login_challenge')))
    @bp.route('/account/forgot/',methods=['GET','POST'])
    def forgot():
        if request.method=='POST':
            if not otp.ready:abort(503,'手機及電郵驗證服務尚未開通，暫時未能自助重設密碼。')
            phase=request.form.get('phase','send')
            if phase=='send':
                raw=request.form.get('contact','');kind='email' if '@' in raw else 'phone'
                try:contact=normalize(kind,raw)
                except ValueError as e:abort(400,str(e))
                if not otp.supports(kind):abort(503,'所選驗證方式尚未開通，請聯絡環聯協助。')
                limit('reset-ip:'+str(request.remote_addr),5,3600);limit('reset-contact:'+contact,1,60)
                ident=secrets.token_urlsafe(24)
                anonymous_challenge(contact,kind,'reset',ident)
                session['reset_challenge']=ident
                flash('如聯絡資料符合條件，我們會嘗試發出驗證碼。請在10分鐘內完成重設。')
            else:
                password=request.form.get('password','');code=request.form.get('code','')
                if not 12<=len(password)<=128 or password!=request.form.get('confirm','') or not re.fullmatch(r'\d{4,10}',code):abort(400,'請檢查驗證碼及新密碼。')
                row,approved=redeem(session.get('reset_challenge'),'reset',code)
                if row is None:abort(400,'驗證碼已失效，請重新開始。')
                if approved:
                    column='phone' if row['kind']=='phone' else 'email';new_hash=generate_password_hash(password)
                    with db() as c:
                        c.execute('BEGIN IMMEDIATE')
                        changed=consume(c,row) and c.execute(f'UPDATE customers SET password_hash=?,auth_version=auth_version+1,{column}_verified=1 WHERE id=? AND enabled=1 AND {column}=?',(new_hash,row['user_id'],row['contact'])).rowcount
                        if changed:audit(c,'password_reset',row['user_id'])
                    if changed:
                        session.clear();flash('密碼已重設，請使用新密碼登入。');return redirect(url_for('accounts.login'))
                flash('驗證碼不正確或服務暫時未能使用，請重新輸入或稍後再試。')
        return render_template('accounts/forgot.html',ready=otp.ready,confirm=bool(session.get('reset_challenge')))
    @bp.get('/account/')
    @logged_in
    def profile():return render_template('accounts/profile.html',user=g.customer,otp_ready=otp.ready,kyc_ready=kyc.ready,kyc_sandbox=kyc.sandbox)
    @bp.post('/account/verify/send/')
    @logged_in
    def send_verify():
        if not otp.ready:abort(503,'手機及電郵驗證服務尚未開通，請稍後再試。')
        kind=request.form.get('kind','email')
        try:contact=normalize(kind,request.form.get('contact',''))
        except ValueError as e:abort(400,str(e))
        if not otp.supports(kind):abort(503,'所選驗證方式尚未開通。')
        # Rate limits come first so a signed-in customer cannot probe other customers' contacts freely.
        limit('send-user:'+g.customer['id'],5,3600);limit('send-contact:'+contact,1,60)
        with db() as c:
            clash=c.execute('SELECT id FROM customers WHERE (email=? OR phone=?) AND id!=?',(contact,contact,g.customer['id'])).fetchone()
        if clash:abort(409,'這項聯絡資料未能加入，請聯絡環聯。')
        try:otp.send(contact,kind)
        except (ProviderUnavailable,ProviderFailure) as e:abort(503,str(e))
        challenge=secrets.token_urlsafe(24)
        with db() as c:
            c.execute('DELETE FROM challenges WHERE expires<?',(time.time(),))
            c.execute('DELETE FROM challenges WHERE user_id=? AND purpose=?',(g.customer['id'],'verify'))
            c.execute('INSERT INTO challenges(id,user_id,contact,kind,purpose,expires) VALUES (?,?,?,?,?,?)',(challenge,g.customer['id'],contact,kind,'verify',time.time()+600));audit(c,'verification_sent',g.customer['id'])
        session['verify_challenge']=challenge
        flash('已提交驗證碼發送請求，驗證碼10分鐘內有效。');return redirect(url_for('accounts.confirm_verify'))
    @bp.route('/account/verify/confirm/',methods=['GET','POST'])
    @logged_in
    def confirm_verify():
        ident=session.get('verify_challenge');expired='驗證已過期或失效，請重新取得驗證碼。'
        with db() as c:row=c.execute('SELECT * FROM challenges WHERE id=? AND user_id=? AND purpose=?',(ident,g.customer['id'],'verify')).fetchone()
        if not row or row['consumed'] or row['expires']<time.time() or row['attempts']>=5:abort(400,expired)
        if request.method=='POST':
            code=request.form.get('code','')
            if not re.fullmatch(r'\d{4,10}',code):abort(400,'請填寫有效的驗證碼。')
            failure=[]
            def check(row,code):
                try:return otp.check(row['contact'],code)
                except (ProviderUnavailable,ProviderFailure) as e:failure.append(str(e));return False
            row,approved=redeem(ident,'verify',code,g.customer['id'],check)
            if row is None:abort(400,expired)
            if failure:abort(503,failure[0])
            if approved:
                column='email' if row['kind']=='email' else 'phone'
                with db() as c:
                    c.execute('BEGIN IMMEDIATE')
                    if not consume(c,row):abort(400,expired)
                    try:c.execute(f'UPDATE customers SET {column}=?,{column}_verified=1 WHERE id=?',(row['contact'],g.customer['id']))
                    except sqlite3.IntegrityError:abort(409,'這項聯絡資料未能加入，請聯絡環聯。')
                    audit(c,'contact_verified',g.customer['id'])
                flash('聯絡資料已驗證。');return redirect(url_for('accounts.profile'))
            flash('驗證碼不正確，請重新輸入。')
        return render_template('accounts/confirm.html',kind=row['kind'])
    @bp.route('/account/password/',methods=['GET','POST'])
    @logged_in
    def password():
        if request.method=='POST':
            limit('password:'+g.customer['id'],5,600)
            new=request.form.get('password','')
            if not check_password_hash(g.customer['password_hash'],request.form.get('current','')[:129]) or not 12<=len(new)<=128 or new!=request.form.get('confirm',''):abort(400,'目前密碼不正確，或新密碼未符合要求。')
            with db() as c:c.execute('UPDATE customers SET password_hash=?,auth_version=auth_version+1 WHERE id=?',(generate_password_hash(new),g.customer['id']));audit(c,'password_changed',g.customer['id'])
            session.clear();flash('密碼已更新，請重新登入。');return redirect(url_for('accounts.login'))
        return render_template('accounts/password.html')
    @bp.get('/account/delete-info/')
    def deletion_info():return render_template('accounts/delete_info.html')
    @bp.route('/account/delete/',methods=['GET','POST'])
    @logged_in
    def delete_account():
        if request.method=='POST':
            ident=g.customer['id']
            limit('delete-account:'+ident,5,600)
            if request.form.get('confirm_delete')!='delete-account':abort(400,'請先確認你要刪除帳戶。')
            password=request.form.get('password','')
            if not password or len(password)>128:abort(400,'請輸入目前密碼以確認刪除。')
            with db() as c:
                c.execute('BEGIN IMMEDIATE')
                current=c.execute('SELECT * FROM customers WHERE id=?',(ident,)).fetchone()
                if not current or not current['enabled'] or current['auth_version']!=session.get('customer_version'):
                    abort(403,'登入狀態已更新，請重新登入後再試。')
                if not check_password_hash(current['password_hash'],password):abort(400,'目前密碼不正確，帳戶尚未刪除。')
                c.execute('DELETE FROM challenges WHERE user_id=?',(ident,))
                c.execute('DELETE FROM identity_events WHERE user_id=?',(ident,))
                c.execute('DELETE FROM account_audit WHERE actor=? OR subject=?',(ident,ident))
                rate_keys=['send-user:'+ident,'password:'+ident,'kyc:'+ident,'delete-account:'+ident]
                for contact in [current['email'],current['phone']]:
                    if contact:
                        c.execute('DELETE FROM challenges WHERE contact=?',(contact,))
                        c.execute('DELETE FROM pending_registrations WHERE contact=?',(contact,))
                        rate_keys.extend(prefix+contact for prefix in ['send-contact:','reset-contact:','code-login-contact:','register-contact:'])
                hashes=[hashlib.sha256((admin_config['secret_key']+key).encode()).hexdigest() for key in rate_keys]
                c.executemany('DELETE FROM account_attempts WHERE key=?',[(key,) for key in hashes])
                c.execute('DELETE FROM customers WHERE id=?',(ident,))
            session.clear()
            flash('帳戶及本網站保存的相關帳戶資料已刪除。你仍可直接瀏覽服務、消息及優惠。')
            return redirect(url_for('accounts.deletion_info'),code=303)
        return render_template('accounts/delete.html')
    @bp.route('/account/identity/',methods=['GET','POST'])
    @logged_in
    def identity():
        if request.method=='POST':
            if not kyc.ready:abort(503,'香港身份證驗證服務尚未開通。')
            if not (g.customer['email_verified'] or g.customer['phone_verified']):abort(403,'請先驗證手機或電郵。')
            if request.form.get('consent')!='yes':abort(400,'請先閱讀並確認身份驗證說明。')
            limit('kyc:'+g.customer['id'],3,3600)
            try:link=kyc.create_link(g.customer['id'])
            except (ProviderUnavailable,ProviderFailure) as e:abort(503,str(e))
            with db() as c:c.execute("UPDATE customers SET kyc_status='pending' WHERE id=? AND kyc_status NOT IN ('verified','test_verified')",(g.customer['id'],));audit(c,'kyc_started',g.customer['id'])
            return redirect(link,code=303)
        return render_template('accounts/identity.html',user=g.customer,ready=kyc.ready,sandbox=kyc.sandbox)
    @bp.post('/account/identity/webhook')
    def kyc_webhook():
        raw=request.get_data()
        if not kyc.validate_webhook(raw,request.headers):abort(403)
        try:event=json.loads(raw)
        except ValueError:abort(400)
        if event.get('type')!='applicantReviewed':return {'received':True}
        if event.get('testMode') is True:return {'received':True}
        if event.get('levelName')!=kyc.config.get('level_name') or event.get('applicantType')!='individual':abort(400)
        if event.get('sandboxMode') is not kyc.sandbox:abort(400)
        if event.get('reviewStatus')!='completed':return {'received':True}
        try:
            at=datetime.fromisoformat(event.get('createdAtMs',event.get('createdAt','')).replace('Z','+00:00'))
            if at.tzinfo is None:at=at.replace(tzinfo=timezone.utc)
            stamp=at.timestamp()
        except (ValueError,TypeError):abort(400)
        result=event.get('reviewResult',{});answer=result.get('reviewAnswer')
        if answer not in {'GREEN','RED'}:abort(400)
        status=('test_verified' if kyc.sandbox else 'verified') if answer=='GREEN' else ('resubmit' if result.get('reviewRejectType')=='RETRY' else 'not_verified')
        digest=hashlib.sha256(raw).hexdigest();ident=event.get('externalUserId')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            r=c.execute('SELECT * FROM customers WHERE id=?',(ident,)).fetchone()
            if not r:abort(404)
            if c.execute('SELECT 1 FROM identity_events WHERE digest=?',(digest,)).fetchone():return {'received':True}
            c.execute('INSERT INTO identity_events VALUES (?,?,?,?)',(digest,stamp,ident,status))
            if stamp>r['kyc_at'] or (stamp==r['kyc_at'] and answer=='RED'):
                c.execute('UPDATE customers SET kyc_status=?,kyc_at=? WHERE id=?',(status,stamp,ident));audit(c,'kyc_'+status,ident,'provider')
        return {'received':True}
    @bp.get('/account/privacy/')
    def privacy():return render_template('accounts/privacy.html',otp_ready=otp.ready,kyc_ready=kyc.ready,kyc_sandbox=kyc.sandbox)
    @bp.get('/admin/users/')
    @staff
    def users():
        query=request.args.get('q','').strip().lower()[:254]
        page=max(1,min(request.args.get('page',1,type=int) or 1,10000))
        where='WHERE instr(lower(coalesce(email,\'\')),?)>0 OR instr(coalesce(phone,\'\'),?)>0' if query else ''
        params=[query,query] if query else []
        with db() as c:
            total=c.execute('SELECT COUNT(*) FROM customers '+where,params).fetchone()[0]
            rows=c.execute('SELECT id,email,phone,enabled,email_verified,phone_verified,kyc_status,created_at FROM customers '+where+' ORDER BY created_at DESC LIMIT 50 OFFSET ?',params+[(page-1)*50]).fetchall()
        return render_template('users.html',users=rows,total=total,page=page,query=query,more=page*50<total)
    @bp.post('/admin/users/<ident>/status')
    @staff
    def user_status(ident):
        enabled=request.form.get('enabled')
        if enabled not in {'0','1'}:abort(400)
        with db() as c:
            if not c.execute('SELECT 1 FROM customers WHERE id=?',(ident,)).fetchone():abort(404)
            c.execute('UPDATE customers SET enabled=?,auth_version=auth_version+1 WHERE id=?',(int(enabled),ident));audit(c,'account_enabled' if enabled=='1' else 'account_disabled',ident,'staff')
        flash('帳戶狀態已更新，原有登入已失效。');return redirect(url_for('accounts.users'))
    app.register_blueprint(bp)
    app.extensions['uacredit_accounts']={'db':db,'otp':otp,'kyc':kyc,'drain':drain}
