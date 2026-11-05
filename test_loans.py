import os, secrets, sqlite3, tempfile, unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from werkzeug.security import generate_password_hash
from cms import create_app, ROOT


class LoanApplicationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'work')
        self.env = patch.dict(os.environ, {'UACREDIT_APPLICATIONS_ENABLED':'1'})
        self.env.start()
        self.password = secrets.token_urlsafe(18)
        self.config = {'username':'editor','password_hash':generate_password_hash(self.password), 'secret_key':secrets.token_hex(32), 'secure_cookie':False}
        self.app = create_app(self.temp.name, self.config)
        self.app.testing = True
        self.client = self.app.test_client()
        self.payload = {'service':'car','name':'測試客戶','phone':'9123 4567','amount':'10000','details':'請電話聯絡','consent':True}
        self.headers = {'Origin':'http://localhost','Idempotency-Key':'1'*32}

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def submit(self, value=None, headers=None):
        return self.client.post('/loan-applications/', json=self.payload if value is None else value, headers=self.headers if headers is None else headers)

    def login(self):
        self.client.get('/admin/login')
        with self.client.session_transaction() as sess:
            csrf = sess['csrf']
        self.client.post('/admin/login', data={'csrf':csrf,'username':'editor','password':self.password})
        self.client.get('/admin/')
        with self.client.session_transaction() as sess:
            return sess['csrf']

    def db(self):
        return sqlite3.connect(Path(self.temp.name)/'loan_applications.sqlite3')

    def test_success_persists_once_and_retries_are_idempotent(self):
        first = self.submit(); self.assertEqual(first.status_code, 201)
        reference = first.json['reference']; self.assertRegex(reference, r'^UA-[A-F0-9]{16}$')
        self.assertEqual(set(first.json), {'success','reference'})
        second = self.submit(); self.assertEqual(second.status_code, 200); self.assertEqual(second.json, first.json)
        changed = {**self.payload,'amount':'20000'}
        self.assertEqual(self.submit(changed).status_code, 409)
        with closing(self.db()) as conn:
            records = conn.execute('SELECT service,name,phone,amount,consent_version,status FROM loan_applications').fetchall()
            self.assertEqual(records, [('car','測試客戶','91234567','10000','loan-basic-v1','new')])
            self.assertEqual(conn.execute('SELECT count(*) FROM loan_application_audit').fetchone()[0], 1)

    def test_cross_origin_invalid_data_and_sensitive_extra_fields_are_rejected(self):
        self.assertEqual(self.submit(headers={'Origin':'https://evil.invalid','Idempotency-Key':'2'*32}).status_code, 403)
        self.assertEqual(self.submit(headers={'Idempotency-Key':'2'*32}).status_code, 403)
        self.assertEqual(self.client.post('/loan-applications/',data='name=x',headers=self.headers).status_code,415)
        for bad in [{'service':[]},{'service':{}},{'name':[]},{'name':'\ud800'},{'consent':False},{'phone':'123'},{'id_number':'secret'}]:
            self.assertEqual(self.submit({**self.payload,**bad}).status_code,400,repr(bad))
        with closing(self.db()) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM loan_applications').fetchone()[0],0)

    def test_admin_access_csrf_status_and_conflict(self):
        reference=self.submit().json['reference']
        with closing(self.db()) as conn:
            conn.execute("UPDATE loan_applications SET created_at='2026-11-04T18:30:00+00:00' WHERE reference=?", (reference,))
            conn.commit()
        self.assertEqual(self.client.get('/admin/loan-applications/').status_code,302)
        self.assertEqual(self.client.get('/admin/loan-applications/'+reference).status_code,302)
        self.assertEqual(self.client.post('/admin/loan-applications/'+reference+'/status',data={'revision':'1','status':'in_progress'}).status_code,400)
        csrf=self.login()
        listing=self.client.get('/admin/loan-applications/'); self.assertIn('測試客戶',listing.get_data(as_text=True)); self.assertEqual(listing.headers['Cache-Control'],'no-store')
        detail=self.client.get('/admin/loan-applications/'+reference); self.assertEqual(detail.status_code,200); self.assertIn('91234567',detail.get_data(as_text=True)); self.assertIn('2026-11-05 02:30', detail.get_data(as_text=True)); self.assertEqual(detail.headers['Cache-Control'],'no-store')
        path='/admin/loan-applications/'+reference+'/status'
        self.assertEqual(self.client.post(path,data={'csrf':csrf,'revision':'1','status':'in_progress'}).status_code,302)
        self.assertEqual(self.client.post(path,data={'csrf':csrf,'revision':'1','status':'completed'}).status_code,409)
        with closing(self.db()) as conn:
            self.assertEqual(conn.execute('SELECT status,revision FROM loan_applications').fetchone(),('in_progress',2))
            self.assertEqual(conn.execute("SELECT old_status,new_status FROM loan_application_audit WHERE action='status_changed'").fetchone(),('new','in_progress'))

    def test_disabled_by_default_and_request_limit(self):
        with patch.dict(os.environ, {'UACREDIT_APPLICATIONS_ENABLED':'0'}), tempfile.TemporaryDirectory(dir=ROOT/'work') as temp:
            app=create_app(temp,self.config); client=app.test_client()
            self.assertFalse(client.get('/loan-applications/status').json['enabled'])
            self.assertFalse(client.get('/healthz').json['public_applications'])
            self.assertEqual(client.post('/loan-applications/',json=self.payload,headers=self.headers).status_code,503)
        self.assertTrue(self.client.get('/loan-applications/status').json['enabled'])
        for i in range(10):
            response=self.submit(headers={'Origin':'http://localhost','Idempotency-Key':format(i,'032x')})
            self.assertEqual(response.status_code,201)
        self.assertEqual(self.submit(headers={'Origin':'http://localhost','Idempotency-Key':'f'*32}).status_code,429)
        self.assertEqual(self.submit(headers={'Origin':'http://localhost','Idempotency-Key':'0'*32}).status_code,200)

    def test_simultaneous_retries_create_only_one_application(self):
        def submit_again(_):
            with self.app.test_client() as client:
                response=client.post('/loan-applications/',json=self.payload,headers=self.headers)
                return response.status_code,response.json
        with ThreadPoolExecutor(max_workers=5) as pool:
            results=list(pool.map(submit_again, range(5)))
        self.assertEqual(sorted(status for status, _ in results), [200,200,200,200,201])
        self.assertEqual(len({value['reference'] for _, value in results}), 1)
        with closing(self.db()) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM loan_applications').fetchone()[0],1)


if __name__ == '__main__':
    unittest.main()
