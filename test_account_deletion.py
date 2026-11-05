"""Guest browsing and customer-requested deletion use disposable local data only."""
import hashlib,json,secrets,tempfile,time,unittest
from pathlib import Path
from werkzeug.security import generate_password_hash
from cms import create_app,ROOT

class FixtureOTP:
    ready=True
    def supports(self,kind):return kind in ('email','phone')
    def send(self,contact,kind):pass
    def check(self,contact,code):return code=='123456'
class UnavailableIdentity:
    ready=False
    sandbox=True
    config={}
    def validate_webhook(self,raw,headers):return False

class GuestAndDeletionTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'work')
        self.password=secrets.token_urlsafe(20)
        self.config={'username':'test-staff','password_hash':generate_password_hash(secrets.token_urlsafe(20)),'secret_key':secrets.token_hex(32),'secure_cookie':False}
        self.app=create_app(self.temp.name,self.config,providers=(FixtureOTP(),UnavailableIdentity()));self.app.testing=True
        self.client=self.app.test_client();self.db=self.app.extensions['uacredit_accounts']['db']
    def tearDown(self):self.temp.cleanup()
    def csrf(self,client=None):
        with (client or self.client).session_transaction() as session:return session['csrf']
    def post(self,path,data=None,client=None):
        client=client or self.client
        return client.post(path,data={'csrf':self.csrf(client),**(data or {})})
    def register(self,email='deletion-test@example.test',client=None):
        client=client or self.client;client.get('/account/register/')
        response=self.post('/account/register/',{'kind':'email','contact':email,'password':self.password,'confirm':self.password,'consent':'yes'},client)
        self.assertEqual(response.status_code,302);client.get(response.location)
        self.assertEqual(self.post('/account/register/confirm/',{'code':'123456'},client).status_code,302);client.get('/account/')
        with client.session_transaction() as session:return session['customer_id']
    def read(self,path,client=None):
        response=(client or self.client).get(path);text=response.get_data(as_text=True);status=response.status_code;response.close();return status,text
    def test_all_original_public_content_is_open_to_guests(self):
        source=json.loads((ROOT/'content/site.json').read_text())
        routes={'/'+record['route'].strip('/')+'/' for record in source['records']}
        routes={path.replace('//','/') for path in routes}
        routes.update('/category/'+category['slug']+'/' for category in source['categories'])
        routes.update(['/updates/','/all-pages/','/faq/','/privacy/'])
        for path in sorted(routes):
            with self.subTest(path=path):
                status,text=self.read(path)
                self.assertEqual(status,200)
                self.assertIn('環聯',text)
        with self.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM customers').fetchone()[0],0)
    def test_private_data_requires_login_but_deletion_instructions_do_not(self):
        for path in ['/account/','/account/password/','/account/identity/','/account/delete/','/admin/users/']:
            with self.subTest(path=path):self.assertEqual(self.client.get(path).status_code,302)
        status,text=self.read('/account/delete-info/')
        self.assertEqual(status,200);self.assertIn('刪除帳戶與資料',text);self.assertIn('毋須開立帳戶',text)
    def test_confirmation_password_and_csrf_are_required(self):
        ident=self.register();self.client.get('/account/delete/')
        self.assertEqual(self.client.post('/account/delete/',data={'password':self.password,'confirm_delete':'delete-account'}).status_code,400)
        self.assertEqual(self.post('/account/delete/',{'password':self.password}).status_code,400)
        self.assertEqual(self.post('/account/delete/',{'password':'incorrect-test-only','confirm_delete':'delete-account'}).status_code,400)
        with self.db() as c:self.assertIsNotNone(c.execute('SELECT id FROM customers WHERE id=?',(ident,)).fetchone())
        self.assertEqual(self.client.get('/account/').status_code,200)
    def test_deletion_removes_associated_data_revokes_sessions_and_preserves_others(self):
        ident=self.register();old_cookie=self.client.get_cookie('session')
        other=self.app.test_client();other_id=self.register('other-deletion-test@example.test',other)
        with self.db() as c:
            for uid,email,prefix in [(ident,'deletion-test@example.test','delete'),(other_id,'other-deletion-test@example.test','keep')]:
                c.execute('INSERT INTO challenges(id,user_id,contact,kind,purpose,expires) VALUES (?,?,?,?,?,?)',(prefix+'-challenge',uid,email,'email','verify',time.time()+600))
                c.execute('INSERT INTO identity_events VALUES (?,?,?,?)',(prefix+'-event',time.time(),uid,'pending'))
                c.execute('INSERT INTO account_audit VALUES (?,?,?,?)',('test-only',uid,'test-action',uid))
                key=hashlib.sha256((self.config['secret_key']+'reset-contact:'+email).encode()).hexdigest()
                c.execute('INSERT INTO account_attempts VALUES (?,?)',(key,time.time()))
            c.execute('INSERT INTO challenges(id,user_id,contact,kind,purpose,expires) VALUES (?,?,?,?,?,?)',('dummy-challenge','dummy:test','deletion-test@example.test','email','reset',time.time()+600))
        self.client.get('/account/delete/')
        response=self.post('/account/delete/',{'password':self.password,'confirm_delete':'delete-account','customer_id':other_id})
        self.assertEqual(response.status_code,303);self.assertTrue(response.location.endswith('/account/delete-info/'))
        status,text=self.read(response.location);self.assertEqual(status,200);self.assertIn('相關帳戶資料已刪除',text)
        with self.db() as c:
            self.assertIsNone(c.execute('SELECT id FROM customers WHERE id=?',(ident,)).fetchone())
            self.assertIsNotNone(c.execute('SELECT id FROM customers WHERE id=?',(other_id,)).fetchone())
            for table,column in [('challenges','user_id'),('identity_events','user_id')]:
                self.assertEqual(c.execute(f'SELECT COUNT(*) FROM {table} WHERE {column}=?',(ident,)).fetchone()[0],0)
                self.assertEqual(c.execute(f'SELECT COUNT(*) FROM {table} WHERE {column}=?',(other_id,)).fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM account_audit WHERE actor=? OR subject=?',(ident,ident)).fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM challenges WHERE contact=?',('deletion-test@example.test',)).fetchone()[0],0)
            self.assertGreater(c.execute('SELECT COUNT(*) FROM account_audit WHERE subject=?',(other_id,)).fetchone()[0],0)
            removed_key=hashlib.sha256((self.config['secret_key']+'reset-contact:deletion-test@example.test').encode()).hexdigest()
            self.assertEqual(c.execute('SELECT COUNT(*) FROM account_attempts WHERE key=?',(removed_key,)).fetchone()[0],0)
        old_client=self.app.test_client();old_client.set_cookie('session',old_cookie.value)
        self.assertEqual(old_client.get('/account/').status_code,302)
        self.assertEqual(other.get('/account/').status_code,200)
        self.assertEqual(self.read('/')[0],200)
        self.client.get('/account/login/')
        self.assertEqual(self.post('/account/login/',{'contact':'deletion-test@example.test','password':self.password}).status_code,400)

if __name__=='__main__':unittest.main()
