"""Isolated UACredit content desk and application service."""
from pathlib import Path
from functools import wraps
from datetime import datetime, timezone
from contextlib import contextmanager
import fcntl, hashlib, hmac, json, os, re, secrets, shutil, sqlite3, subprocess, sys, time
from flask import Flask, abort, flash, redirect, render_template, request, session, send_from_directory, url_for
from werkzeug.security import check_password_hash
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from original_content import SafeOriginal

ROOT=Path(__file__).parent
CODE_VERSION='2026.11.05.3'

def create_app(data_dir=None,config=None,providers=None):
    data=Path(data_dir or os.environ.get('UACREDIT_DATA','/var/lib/uacredit'))
    data.mkdir(parents=True,exist_ok=True)
    if config is None:
        config=json.loads(Path(os.environ.get('UACREDIT_CONFIG','/etc/uacredit/config.json')).read_text())
    app=Flask(__name__,static_folder=None)
    app.config.update(SECRET_KEY=config['secret_key'],SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Strict',SESSION_COOKIE_SECURE=config.get('secure_cookie',True),MAX_CONTENT_LENGTH=2*1024*1024,PERMANENT_SESSION_LIFETIME=1800)
    # Behind nginx every request arrives from 127.0.0.1; trust exactly the configured proxy hops
    # so rate limits key on the visitor address. Direct (tunnel) access keeps the default of 0.
    hops=int(config.get('trusted_proxy_hops',0))
    if hops:app.wsgi_app=ProxyFix(app.wsgi_app,x_for=hops,x_proto=hops)
    launch=Path(os.environ.get('UACREDIT_LAUNCH',str(ROOT/'content/launch.json')))
    indexable=json.loads(launch.read_text()).get('indexable') is True if launch.exists() else False
    db_path=data/'content.sqlite3'
    @contextmanager
    def db():
        conn=sqlite3.connect(db_path,timeout=15);conn.row_factory=sqlite3.Row
        try:
            with conn:yield conn
        finally:conn.close()
    with db() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS drafts (id INTEGER PRIMARY KEY, record TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1)')
        conn.execute('CREATE TABLE IF NOT EXISTS attempts (client TEXT, at REAL)')
        conn.execute('CREATE TABLE IF NOT EXISTS audit (at TEXT, action TEXT, record_id INTEGER, revision INTEGER)')
    live=data/'live.json'
    if not live.exists():shutil.copyfile(ROOT/'content/site.json',live)
    settings=data/'settings.json'
    if not settings.exists():shutil.copyfile(ROOT/'content/settings.json',settings)
    def source():return json.loads(live.read_text())
    def audit(conn,action,ident=None,revision=None):
        conn.execute('INSERT INTO audit VALUES (?,?,?,?)',(datetime.now(timezone.utc).isoformat(),action,ident,revision))
    def token():
        if 'csrf' not in session:session['csrf']=secrets.token_urlsafe(32)
        return session['csrf']
    @app.context_processor
    def context():return {'csrf':token}
    @contextmanager
    def publish_lock():
        with (data/'publish.lock').open('w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX);yield
    def protect(fn):
        @wraps(fn)
        def wrapper(*args,**kwargs):
            if not session.get('admin'):return redirect(url_for('login'))
            return fn(*args,**kwargs)
        return wrapper
    @app.before_request
    def csrf_check():
        if request.endpoint in {'accounts.kyc_webhook','loan_applications.submit'}:return
        if request.method=='POST':
            given=request.form.get('csrf','')
            if not given or not hmac.compare_digest(given,session.get('csrf','')):abort(400,'頁面已過期，請重新開啟後再試。')
    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
        response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if not indexable or request.path.startswith(('/admin','/account','/healthz')):response.headers['X-Robots-Tag']='noindex, nofollow'
        if request.path.startswith(('/admin','/account','/loan-applications')):response.headers['Cache-Control']='no-store'
        return response
    @app.route('/admin/login',methods=['GET','POST'])
    def login():
        if request.method=='POST':
            client=request.remote_addr or 'unknown'
            now=time.time()
            with db() as conn:
                conn.execute('DELETE FROM attempts WHERE at < ?',(now-600,))
                n=conn.execute('SELECT COUNT(*) FROM attempts WHERE client=?',(client,)).fetchone()[0]
                if n>=5:abort(429,'嘗試次數較多，請10分鐘後再試。')
                # Evaluate both checks so response time does not reveal whether the username matched.
                name_ok=hmac.compare_digest(request.form.get('username','').encode(),config['username'].encode())
                password_ok=check_password_hash(config['password_hash'],request.form.get('password','')[:256])
                ok=name_ok and password_ok
                if ok:
                    conn.execute('DELETE FROM attempts WHERE client=?',(client,));audit(conn,'login')
                    session.clear();session['admin']=True;session.permanent=True
                    return redirect(url_for('dashboard'))
                conn.execute('INSERT INTO attempts VALUES (?,?)',(client,now))
            flash('帳戶或密碼不正確。')
        return render_template('login.html')
    @app.post('/admin/logout')
    @protect
    def logout():session.clear();return redirect(url_for('login'))
    @app.get('/admin/')
    @protect
    def dashboard():
        s=source()
        with db() as conn:drafts={x['id']:x for x in conn.execute('SELECT * FROM drafts')}
        records={r['id']:r for r in s['records']}
        for ident,d in drafts.items():records[ident]=json.loads(d['record'])
        return render_template('dashboard.html',records=list(records.values()),drafts=drafts)
    def get_record(ident):
        with db() as conn:row=conn.execute('SELECT * FROM drafts WHERE id=?',(ident,)).fetchone()
        if row:return json.loads(row['record']),row['revision']
        for r in source()['records']:
            if r['id']==ident:return r,0
        abort(404)
    @app.route('/admin/edit/<int:ident>',methods=['GET','POST'])
    @protect
    def edit(ident):
        record,revision=get_record(ident)
        if request.method=='POST':
            title=request.form.get('title','').strip()
            content=request.form.get('content','')
            if not title or len(title)>250:abort(400,'請填寫250字以內的標題。')
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE')
                current=conn.execute('SELECT revision FROM drafts WHERE id=?',(ident,)).fetchone()
                if int(request.form.get('revision','-1')) != (current[0] if current else 0):abort(409,'這篇內容已更新。請保留你的文字，重新開啟後再修改。')
                record['title']['rendered']=title
                if ident==2:
                    record['display']={k:request.form.get(k,default).strip()[:40] for k,default in [('hero_line_1','汽車上會・汽車翻按'),('hero_line_2','物業貸款')]}
                if ident==110:
                    display={}
                    for key,default in [('phone_main','2886 8345'),('phone_secondary','2886 8044'),('phone_complaints','2886 8144'),('whatsapp','6085 5201')]:
                        value=request.form.get(key,default).strip()
                        if not re.fullmatch(r'[0-9 ]{8,12}',value) or len(value.replace(' ',''))!=8:abort(400,'請填寫8位香港電話號碼。')
                        display[key]=value
                    email=request.form.get('email','cs@uacredit.com.hk').strip()
                    if not re.fullmatch(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',email):abort(400,'請填寫有效電郵。')
                    display['email']=email
                    for key,default in [('address_line_1','九龍馬頭圍道39號'),('address_line_2','紅磡商業中心A座3樓306A室')]:display[key]=request.form.get(key,default).strip()[:120]
                    record['display']=display
                record['content']['rendered']=SafeOriginal(source()['assets']).render(content)
                if record['type']=='posts':record['categories']=[int(x) for x in request.form.getlist('categories') if x.isdigit() and int(x) in {c['id'] for c in source()['categories']}]
                record['modified']=datetime.now(timezone.utc).isoformat()
                conn.execute('INSERT INTO drafts VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET record=excluded.record,revision=excluded.revision',(ident,json.dumps(record,ensure_ascii=False),revision+1))
                audit(conn,'save_draft',ident,revision+1)
            flash('草稿已儲存，網站尚未改動。');return redirect(url_for('edit',ident=ident))
        body=SafeOriginal(source()['assets']).render(record['content']['rendered'])
        return render_template('edit.html',record=record,revision=revision,body=body,categories=source()['categories'])
    @app.post('/admin/new')
    @protect
    def new_record():
        slug=request.form.get('slug','').strip()
        if not re.fullmatch(r'[a-z][a-z0-9-]{1,79}',slug):abort(400,'網址請使用2至80個英文字母、數字或連字號，並以英文字母開頭。')
        with db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            allrecords=source()['records']+[json.loads(x['record']) for x in conn.execute('SELECT record FROM drafts')]
            if slug in {r['route'] for r in allrecords}|{'updates','all-pages','faq','privacy','assets','admin','account','healthz'}:abort(409,'這個網址已使用，請選擇另一個。')
            ident=max(r['id'] for r in allrecords)+1
            record={'id':ident,'route':slug,'slug':slug,'link':'https://www.uacredit.hk/'+slug,'date':datetime.now(timezone.utc).isoformat(),'modified':datetime.now(timezone.utc).isoformat(),'title':{'rendered':'新消息'},'content':{'rendered':'<p>在這裡填寫內容。</p>'},'type':'posts','categories':[],'featured_media':0,'source_images':[]}
            conn.execute('INSERT INTO drafts VALUES (?,?,1)',(ident,json.dumps(record,ensure_ascii=False)));audit(conn,'create_draft',ident,1)
        return redirect(url_for('edit',ident=ident))
    def atomic_json(path,value):
        temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2));os.replace(temp,path)
    @app.post('/admin/publish/<int:ident>')
    @protect
    def publish(ident):
        record,revision=get_record(ident)
        expected=int(request.form.get('revision','-1'))
        with publish_lock(),db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT * FROM drafts WHERE id=?',(ident,)).fetchone()
            if row is None or row['revision']!=expected:abort(409,'草稿已更新，請重新開啟後再發佈。')
            s=source();current=[r for r in s['records'] if r['id']!=ident];current.append(json.loads(row['record']));s['records']=current
            stamp=datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')+'-'+secrets.token_hex(3)
            release=data/'releases'/stamp;release.mkdir(parents=True)
            (release/'previous.json').write_bytes(live.read_bytes())
            staged=release/'site.json';atomic_json(staged,s)
            previous_current=(data/'current').resolve() if (data/'current').exists() else None
            previous_live=live.read_bytes()
            switched=False
            try:
                env={**os.environ,'UACREDIT_CONTENT':str(staged),'UACREDIT_SETTINGS':str(settings),'UACREDIT_BUILD_DIR':str(release/'www')}
                result=subprocess.run([sys.executable,str(ROOT/'build.py')],env=env,capture_output=True,text=True,timeout=45)
                if result.returncode or not (release/'www/index.html').exists():raise RuntimeError('build failed')
                (release/'www/assets').symlink_to(ROOT/'dist/assets',target_is_directory=True)
                (release/'code_version').write_text(CODE_VERSION)
                pointer=data/'current.new';pointer.symlink_to(release/'www',target_is_directory=True);os.replace(pointer,data/'current')
                switched=True
                atomic_json(live,s)
                conn.execute('DELETE FROM drafts WHERE id=?',(ident,));audit(conn,'publish',ident,expected)
            except Exception:
                if switched:
                    if previous_current:
                        rollback=data/'current.rollback';rollback.symlink_to(previous_current,target_is_directory=True);os.replace(rollback,data/'current')
                    else:(data/'current').unlink(missing_ok=True)
                    rollback_live=data/'live.rollback';rollback_live.write_bytes(previous_live);os.replace(rollback_live,live)
                shutil.rmtree(release,ignore_errors=True)
                abort(500,'發佈未完成，請重試。原有網站內容仍然保留。')
            releases=sorted((data/'releases').iterdir(),key=lambda p:p.name)
            for old in releases[:-2]:shutil.rmtree(old)
        flash('已發佈，網站內容已更新。');return redirect(url_for('dashboard'))
    @app.get('/healthz')
    def health():
        providers=app.extensions['uacredit_accounts']
        return {'status':'ok','site':'uacredit','version':CODE_VERSION,'public_applications':app.extensions['loan_applications_enabled'],'customer_accounts':True,
                'contact_verification_configured':bool(providers['otp'].ready),'email_verification_configured':bool(providers['otp'].supports('email')),
                'whatsapp_verification_configured':bool(providers['otp'].supports('phone')),'identity_verification_configured':bool(providers['kyc'].ready)}
    @app.get('/')
    @app.get('/<path:path>')
    def public(path=''):
        if path.startswith(('admin/','content/','.')):abort(404)
        if path.rstrip('/') in {'news','author/uacredit'}:return redirect('/updates/',code=301)
        base=(data/'current').resolve() if (data/'current').exists() else ROOT/'dist'
        if path.startswith('assets/'):return send_from_directory(ROOT/'dist',path)
        target=path if Path(path).suffix else path.rstrip('/')+'/index.html' if path else 'index.html'
        if (base/target).is_file():return send_from_directory(base,target)
        return send_from_directory(base,'404.html'),404
    @app.errorhandler(HTTPException)
    def customer_error(error):
        if request.path.startswith('/account'):
            heading={400:'請檢查後再試',403:'暫時未能繼續',409:'資料未能更新',429:'請稍後再試',503:'服務尚未可用'}.get(error.code,'未能開啟這個頁面')
            return render_template('accounts/error.html',heading=heading,message=error.description),error.code
        return error
    def refresh_published():
        # A published copy shadows the code's own pages. After a code upgrade, rebuild it from the
        # live content with the new templates; on any failure keep serving the existing copy.
        pointer=data/'current'
        if not pointer.exists():return
        old=pointer.resolve().parent
        with publish_lock():
            marker=old/'code_version'
            if marker.exists() and marker.read_text()==CODE_VERSION:return
            release=data/'releases'/(datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')+'-'+secrets.token_hex(3))
            try:
                release.mkdir(parents=True)
                (release/'previous.json').write_bytes(live.read_bytes());staged=release/'site.json';atomic_json(staged,json.loads(live.read_text()))
                env={**os.environ,'UACREDIT_CONTENT':str(staged),'UACREDIT_SETTINGS':str(settings),'UACREDIT_BUILD_DIR':str(release/'www')}
                result=subprocess.run([sys.executable,str(ROOT/'build.py')],env=env,capture_output=True,text=True,timeout=45)
                if result.returncode or not (release/'www/index.html').exists():raise RuntimeError('build failed')
                (release/'www/assets').symlink_to(ROOT/'dist/assets',target_is_directory=True);(release/'code_version').write_text(CODE_VERSION)
                new=data/'current.new';new.symlink_to(release/'www',target_is_directory=True);os.replace(new,pointer)
            except Exception as exc:
                shutil.rmtree(release,ignore_errors=True);print('published copy refresh skipped:',exc,file=sys.stderr);return
            for stale in sorted((data/'releases').iterdir(),key=lambda p:p.name)[:-2]:shutil.rmtree(stale)
    from accounts import install_accounts
    install_accounts(app,data,config,providers)
    from loans import install_loans
    install_loans(app,data,config,protect)
    app.data_dir=data
    refresh_published()
    return app

if __name__=='__main__':create_app().run(host='127.0.0.1',port=8744)
