"""Provider calls are simulated here only. These tests do not prove live verification."""
import hashlib,hmac,json,secrets,tempfile,time,unittest
from datetime import datetime,timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.parse import parse_qs
from werkzeug.security import generate_password_hash
from cms import create_app,ROOT
from identity_providers import SumsubIdentity,TwilioVerify,ProviderFailure

class FakeOTP:
    def __init__(self):self.channels={'email','phone'}
    @property
    def ready(self):return bool(self.channels)
    def supports(self,kind):return kind in self.channels
    def send(self,contact,kind):self.last=(contact,kind)
    def check(self,contact,code):return code=='123456'
class FakeKYC(SumsubIdentity):
    def create_link(self,user_id):return 'https://in.sumsub.com/websdk/p/test-only'

class AccountsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'work');self.password=secrets.token_urlsafe(20)
        self.config={'username':'test-staff','password_hash':generate_password_hash(self.password),'secret_key':secrets.token_hex(32),'secure_cookie':False}
        self.otp=FakeOTP();self.kyc=FakeKYC({'enabled':True,'hkid_level_confirmed':True,'app_token':'test-only','secret_key':'test-only','webhook_secret':'test-hook-only','level_name':'hkid-test','environment':'sandbox'})
        self.app=create_app(self.temp.name,self.config,providers=(self.otp,self.kyc));self.app.testing=True;self.client=self.app.test_client();self.ext=self.app.extensions['uacredit_accounts']
    def tearDown(self):self.temp.cleanup()
    def csrf(self,client=None):
        with (client or self.client).session_transaction() as s:return s['csrf']
    def post(self,url,data=None,client=None):
        c=client or self.client;return c.post(url,data={'csrf':self.csrf(c),**(data or {})})
    def register(self,kind='email',contact='customer@example.test'):
        self.client.get('/account/register/')
        r=self.post('/account/register/',{'kind':kind,'contact':contact,'password':self.password,'confirm':self.password,'consent':'yes'})
        self.assertEqual(r.status_code,302);self.assertTrue(r.location.endswith('/account/register/confirm/'))
        self.client.get(r.location);self.assertEqual(self.post('/account/register/confirm/',{'code':'123456'}).status_code,302);self.client.get('/account/')
        with self.client.session_transaction() as s:return s['customer_id']
    def verify_contact(self,kind='email',contact='customer@example.test'):
        self.assertEqual(self.post('/account/verify/send/',{'kind':kind,'contact':contact}).status_code,302)
        self.client.get('/account/verify/confirm/')
        self.assertEqual(self.post('/account/verify/confirm/',{'code':'123456'}).status_code,302)
        self.client.get('/account/')
    def test_register_phone_email_and_role_boundary(self):
        ident=self.register()
        with self.ext['db']() as c:r=c.execute('SELECT * FROM customers WHERE id=?',(ident,)).fetchone()
        self.assertEqual(r['email_verified'],1);self.assertEqual(r['kyc_status'],'not_started');self.assertNotEqual(r['password_hash'],self.password)
        self.assertEqual(self.client.get('/admin/users/').status_code,302)
        with self.ext['db']() as c:c.execute('UPDATE customers SET email_verified=0 WHERE id=?',(ident,))
        self.assertEqual(self.post('/account/identity/',{'consent':'yes'}).status_code,403)
        self.assertEqual(self.post('/account/logout/').status_code,302)
        self.register('phone','91234567')
        self.post('/account/logout/');self.client.get('/account/login/')
        self.assertEqual(self.post('/account/login/',{'contact':'+852 9123 4567','password':self.password}).status_code,302)
    def test_verification_one_use_and_linking(self):
        ident=self.register();self.verify_contact('phone','91234567')
        with self.ext['db']() as c:r=c.execute('SELECT * FROM customers WHERE id=?',(ident,)).fetchone()
        self.assertEqual(r['phone'],'+85291234567');self.assertEqual(r['phone_verified'],1);self.assertEqual(r['email_verified'],1)
        self.assertEqual(self.post('/account/verify/confirm/',{'code':'123456'}).status_code,400)
    def test_wrong_code_attempts_bounded(self):
        self.register();self.post('/account/verify/send/',{'kind':'email','contact':'customer@example.test'})
        self.client.get('/account/verify/confirm/')
        for _ in range(5):self.assertEqual(self.post('/account/verify/confirm/',{'code':'000000'}).status_code,200)
        self.assertEqual(self.post('/account/verify/confirm/',{'code':'123456'}).status_code,400)
    def test_code_login_marks_contact_and_consumes_challenge(self):
        ident=self.register();self.post('/account/logout/');self.client.get('/account/code-login/')
        self.assertEqual(self.post('/account/code-login/',{'phase':'send','contact':'customer@example.test'}).status_code,200)
        self.assertEqual(self.post('/account/code-login/',{'phase':'confirm','code':'123456'}).status_code,302)
        with self.ext['db']() as c:self.assertEqual(c.execute('SELECT email_verified FROM customers WHERE id=?',(ident,)).fetchone()[0],1)
        with self.client.session_transaction() as s:self.assertEqual(s['customer_id'],ident)
    def test_password_recovery_revokes_old_session(self):
        self.register();old_cookie=self.client.get_cookie('session')
        self.post('/account/logout/');self.client.get('/account/forgot/')
        self.assertEqual(self.post('/account/forgot/',{'phase':'send','contact':'customer@example.test'}).status_code,200)
        new=secrets.token_urlsafe(20)
        self.assertEqual(self.post('/account/forgot/',{'phase':'confirm','code':'123456','password':new,'confirm':new}).status_code,302)
        other=self.app.test_client();other.set_cookie('session',old_cookie.value)
        self.assertEqual(other.get('/account/').status_code,302)
        self.client.get('/account/login/')
        self.assertEqual(self.post('/account/login/',{'contact':'customer@example.test','password':new}).status_code,302)

    def test_anonymous_challenges_match_and_never_authenticate_unknown_contacts(self):
        self.register();self.post('/account/logout/')
        for path in ('/account/code-login/','/account/forgot/'):
            known=self.app.test_client();unknown=self.app.test_client()
            known.get(path);unknown.get(path)
            sent_known=self.post(path,{'phase':'send','contact':'customer@example.test'},known)
            sent_unknown=self.post(path,{'phase':'send','contact':'unknown@example.test'},unknown)
            self.assertEqual((sent_known.status_code,sent_unknown.status_code),(200,200))
            self.assertIn('如聯絡資料符合條件，我們會嘗試發出',sent_known.get_data(as_text=True))
            self.assertIn('如聯絡資料符合條件，我們會嘗試發出',sent_unknown.get_data(as_text=True))
            extra={'password':'new-password-for-test','confirm':'new-password-for-test'} if path.endswith('forgot/') else {}
            for _ in range(5):
                bad=self.post(path,{'phase':'confirm','code':'000000',**extra},known)
                with patch.object(self.otp,'check',return_value=True) as check:
                    fake=self.post(path,{'phase':'confirm','code':'123456',**extra},unknown)
                check.assert_not_called()
                self.assertEqual((bad.status_code,fake.status_code),(200,200))
                for response in (bad,fake):self.assertIn('驗證碼不正確或服務暫時未能使用',response.get_data(as_text=True))
            self.assertEqual(self.post(path,{'phase':'confirm','code':'123456',**extra},known).status_code,400)
            self.assertEqual(self.post(path,{'phase':'confirm','code':'123456',**extra},unknown).status_code,400)
            with unknown.session_transaction() as session:self.assertNotIn('customer_id',session)

    def test_provider_failures_do_not_reveal_account_presence(self):
        self.register();self.post('/account/logout/')
        for path in ('/account/code-login/','/account/forgot/'):
            known=self.app.test_client();unknown=self.app.test_client();known.get(path);unknown.get(path)
            with patch.object(self.otp,'send',side_effect=ProviderFailure('unavailable')):
                sent_known=self.post(path,{'phase':'send','contact':'customer@example.test'},known)
                sent_unknown=self.post(path,{'phase':'send','contact':'unknown@example.test'},unknown)
                self.ext['drain']()
            self.assertEqual((sent_known.status_code,sent_unknown.status_code),(200,200))
            extra={'password':'new-password-for-test','confirm':'new-password-for-test'} if path.endswith('forgot/') else {}
            with patch.object(self.otp,'check',return_value=True) as check:
                for client in (known,unknown):
                    response=self.post(path,{'phase':'confirm','code':'123456',**extra},client)
                    self.assertEqual(response.status_code,200)
                    self.assertIn('驗證碼不正確或服務暫時未能使用',response.get_data(as_text=True))
                check.assert_not_called()

    def test_new_challenge_invalidates_previous_for_known_and_unknown(self):
        self.register();self.post('/account/logout/')
        for path,contact in [('/account/code-login/','customer@example.test'),('/account/code-login/','unknown@example.test'),('/account/forgot/','customer@example.test'),('/account/forgot/','unknown@example.test')]:
            first=self.app.test_client();second=self.app.test_client();first.get(path);second.get(path)
            self.assertEqual(self.post(path,{'phase':'send','contact':contact},first).status_code,200)
            prefix='code-login-contact:' if 'code-login' in path else 'reset-contact:'
            key=hashlib.sha256((self.config['secret_key']+prefix+contact).encode()).hexdigest()
            with self.ext['db']() as c:c.execute('DELETE FROM account_attempts WHERE key=?',(key,))
            self.assertEqual(self.post(path,{'phase':'send','contact':contact},second).status_code,200)
            extra={'password':'new-password-for-test','confirm':'new-password-for-test'} if path.endswith('forgot/') else {}
            self.assertEqual(self.post(path,{'phase':'confirm','code':'000000',**extra},first).status_code,400)

    def test_real_challenge_check_failure_is_generic_and_limited(self):
        self.register();self.post('/account/logout/');self.client.get('/account/code-login/')
        self.post('/account/code-login/',{'phase':'send','contact':'customer@example.test'})
        with patch.object(self.otp,'check',side_effect=ProviderFailure('unavailable')):
            for _ in range(5):
                result=self.post('/account/code-login/',{'phase':'confirm','code':'123456'})
                self.assertEqual(result.status_code,200)
                self.assertIn('驗證碼不正確或服務暫時未能使用',result.get_data(as_text=True))
        self.assertEqual(self.post('/account/code-login/',{'phase':'confirm','code':'123456'}).status_code,400)

    def test_challenge_replay_and_concurrent_success_are_rejected(self):
        self.register();self.post('/account/logout/');self.client.get('/account/code-login/')
        self.post('/account/code-login/',{'phase':'send','contact':'customer@example.test'})
        cookie=self.client.get_cookie('session').value;token=self.csrf()
        def confirm(_):
            client=self.app.test_client();client.set_cookie('session',cookie)
            return client.post('/account/code-login/',data={'csrf':token,'phase':'confirm','code':'123456'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(confirm,range(2)))
        self.assertEqual(sorted(statuses),[302,400])
        self.assertEqual(confirm(0),400)

    def test_disabled_account_cannot_reset_with_prior_challenge(self):
        ident=self.register();self.post('/account/logout/');self.client.get('/account/forgot/')
        self.post('/account/forgot/',{'phase':'send','contact':'customer@example.test'})
        with self.ext['db']() as c:
            original=c.execute('SELECT password_hash FROM customers WHERE id=?',(ident,)).fetchone()[0]
            c.execute('UPDATE customers SET enabled=0 WHERE id=?',(ident,))
        result=self.post('/account/forgot/',{'phase':'confirm','code':'123456','password':'new-password-for-test','confirm':'new-password-for-test'})
        self.assertEqual(result.status_code,200)
        self.assertIn('驗證碼不正確或服務暫時未能使用',result.get_data(as_text=True))
        with self.ext['db']() as c:self.assertEqual(c.execute('SELECT password_hash FROM customers WHERE id=?',(ident,)).fetchone()[0],original)

    def test_replaced_contact_cannot_use_its_outstanding_challenges(self):
        for kind,old,new in [('email','customer@example.test','replacement@example.test'),('phone','91234567','98765432')]:
            with self.subTest(kind=kind):
                ident=self.register(kind,old)
                login=self.app.test_client();reset=self.app.test_client()
                login.get('/account/code-login/');reset.get('/account/forgot/')
                self.assertEqual(self.post('/account/code-login/',{'phase':'send','contact':old},login).status_code,200)
                self.assertEqual(self.post('/account/forgot/',{'phase':'send','contact':old},reset).status_code,200)
                self.verify_contact(kind,new)
                with self.ext['db']() as c:original=c.execute(f'SELECT password_hash,auth_version,{kind},{kind}_verified FROM customers WHERE id=?',(ident,)).fetchone()
                login_result=self.post('/account/code-login/',{'phase':'confirm','code':'123456'},login)
                reset_result=self.post('/account/forgot/',{'phase':'confirm','code':'123456','password':'new-password-for-test','confirm':'new-password-for-test'},reset)
                for result in (login_result,reset_result):
                    self.assertEqual(result.status_code,200)
                    self.assertIn('驗證碼不正確或服務暫時未能使用',result.get_data(as_text=True))
                with login.session_transaction() as session:self.assertNotIn('customer_id',session)
                with self.ext['db']() as c:
                    current=c.execute(f'SELECT password_hash,auth_version,{kind},{kind}_verified FROM customers WHERE id=?',(ident,)).fetchone()
                    self.assertEqual(tuple(current),tuple(original))
                    self.assertEqual(current[kind],new if kind=='email' else '+852'+new)
                    self.assertEqual(current[kind+'_verified'],1)

    def test_staff_disable_revokes_user_session(self):
        ident=self.register();staff=self.app.test_client();staff.get('/admin/login')
        self.post('/admin/login',{'username':'test-staff','password':self.password},staff);staff.get('/admin/users/')
        self.assertEqual(self.post('/admin/users/'+ident+'/status',{'enabled':'0'},staff).status_code,302)
        self.assertEqual(self.client.get('/account/').status_code,302)
    def test_signed_kyc_callback_environment_replay_and_ordering(self):
        ident=self.register();self.verify_contact();self.assertEqual(self.post('/account/identity/',{'consent':'yes'}).status_code,303)
        event={'externalUserId':ident,'levelName':'hkid-test','applicantType':'individual','type':'applicantReviewed','sandboxMode':True,'reviewStatus':'completed','reviewResult':{'reviewAnswer':'GREEN'},'createdAtMs':datetime.now(timezone.utc).isoformat()}
        def deliver(e,signed=True):
            raw=json.dumps(e,separators=(',',':')).encode();headers={'Content-Type':'application/json','X-Payload-Digest-Alg':'HMAC_SHA256_HEX'}
            if signed:headers['X-Payload-Digest']=hmac.new(b'test-hook-only',raw,hashlib.sha256).hexdigest()
            return self.client.post('/account/identity/webhook',data=raw,headers=headers)
        self.assertEqual(deliver(event,False).status_code,403)
        event['testMode']=True;self.assertEqual(deliver(event).status_code,200)
        with self.ext['db']() as c:self.assertEqual(c.execute('SELECT kyc_status FROM customers WHERE id=?',(ident,)).fetchone()[0],'pending')
        del event['testMode']
        self.assertEqual(deliver(event).status_code,200);self.assertEqual(deliver(event).status_code,200)
        with self.ext['db']() as c:
            self.assertEqual(c.execute('SELECT kyc_status FROM customers WHERE id=?',(ident,)).fetchone()[0],'test_verified')
            self.assertEqual(c.execute('SELECT COUNT(*) FROM identity_events').fetchone()[0],1)
        event['sandboxMode']=False;self.assertEqual(deliver(event).status_code,400)
        event['sandboxMode']=True;event['createdAtMs']='2020-01-01T00:00:00+00:00';event['reviewResult']={'reviewAnswer':'RED'}
        self.assertEqual(deliver(event).status_code,200)
        with self.ext['db']() as c:self.assertEqual(c.execute('SELECT kyc_status FROM customers WHERE id=?',(ident,)).fetchone()[0],'test_verified')
    def test_providers_unconfigured_fail_closed(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'work') as d:
            app=create_app(d,self.config);client=app.test_client();client.get('/account/register/')
            unavailable=client.get('/account/register/').get_data(as_text=True)
            self.assertIn('開戶服務尚未開通',unavailable)
            self.assertIn('以訪客瀏覽',unavailable)
            self.assertNotIn('name="contact"',unavailable)
            client.get('/account/login/')  # A valid session token must not bypass unavailable registration.
            response=self.post('/account/register/',{'kind':'email','contact':'other@example.test','password':self.password,'confirm':self.password,'consent':'yes'},client)
            self.assertEqual(response.status_code,503)
            self.assertFalse(client.get('/healthz').json['contact_verification_configured'])
            self.assertFalse(client.get('/healthz').json['identity_verification_configured'])
            with app.extensions['uacredit_accounts']['db']() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM customers').fetchone()[0],0)
            self.assertEqual(client.post('/account/identity/webhook',data='{}').status_code,403)

    def test_registration_requires_correct_code_and_expires_after_five_attempts(self):
        self.client.get('/account/register/')
        response=self.post('/account/register/',{'kind':'phone','contact':'91234567','password':self.password,'confirm':self.password,'consent':'yes'})
        self.assertEqual(response.status_code,302);self.client.get(response.location)
        with self.ext['db']() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM customers').fetchone()[0],0)
        for _ in range(5):
            wrong=self.post('/account/register/confirm/',{'code':'000000'})
            self.assertEqual(wrong.status_code,200)
            self.assertIn('aria-describedby="registration-code-error"',wrong.get_data(as_text=True))
            self.assertIn('驗證碼不正確',wrong.get_data(as_text=True))
        expired=self.post('/account/register/confirm/',{'code':'123456'})
        self.assertEqual(expired.status_code,400)
        self.assertIn('重新開始開戶',expired.get_data(as_text=True))
        with self.ext['db']() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM customers').fetchone()[0],0)

    def test_expired_registration_cannot_create_account(self):
        self.client.get('/account/register/')
        self.assertEqual(self.post('/account/register/',{'kind':'email','contact':'expired@example.test','password':self.password,'confirm':self.password,'consent':'yes'}).status_code,302)
        with self.ext['db']() as c:c.execute('UPDATE pending_registrations SET expires=?',(time.time()-1,))
        self.client.get('/account/register/confirm/')
        with self.ext['db']() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM customers').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM pending_registrations').fetchone()[0],0)

    def test_delivery_failure_does_not_create_registration(self):
        def fail_send(contact,kind):raise ProviderFailure('服務暫時未能回應。')
        self.otp.send=fail_send;self.client.get('/account/register/')
        self.assertEqual(self.post('/account/register/',{'kind':'email','contact':'delivery@example.test','password':self.password,'confirm':self.password,'consent':'yes'}).status_code,503)
        with self.ext['db']() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM customers').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM pending_registrations').fetchone()[0],0)

    def test_existing_contact_not_disclosed_before_ownership_verification(self):
        self.register();self.post('/account/logout/')
        key=hashlib.sha256((self.config['secret_key']+'register-contact:customer@example.test').encode()).hexdigest()
        with self.ext['db']() as c:c.execute('DELETE FROM account_attempts WHERE key=?',(key,))
        self.client.get('/account/register/')
        response=self.post('/account/register/',{'kind':'email','contact':'customer@example.test','password':self.password,'confirm':self.password,'consent':'yes'})
        self.assertEqual(response.status_code,302);self.client.get(response.location)
        self.assertEqual(self.post('/account/register/confirm/',{'code':'123456'}).status_code,409)
        with self.ext['db']() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM customers').fetchone()[0],1)

    def test_provider_configuration_requires_explicit_valid_settings(self):
        twilio={'enabled':True,'account_sid':'AC'+'1'*32,'service_sid':'VA'+'2'*32,'auth_token':'fixture','email_enabled':True,'whatsapp_enabled':True,'whatsapp_no_sms_fallback_confirmed':True}
        self.assertTrue(TwilioVerify(twilio).ready)
        self.assertFalse(TwilioVerify({**twilio,'enabled':'false'}).ready)
        self.assertFalse(TwilioVerify({**twilio,'service_sid':'VA-invalid'}).ready)
        self.assertFalse(TwilioVerify({**twilio,'email_enabled':False,'whatsapp_no_sms_fallback_confirmed':False}).ready)
        self.assertFalse(TwilioVerify({**twilio,'email_enabled':'true'}).supports('email'))
        config=dict(self.kyc.config)
        self.assertTrue(SumsubIdentity(config).ready)
        self.assertFalse(SumsubIdentity({**config,'hkid_level_confirmed':'false'}).ready)
        self.assertFalse(SumsubIdentity({**config,'environment':'unknown'}).ready)

    def test_twilio_sends_only_the_selected_channel(self):
        config={'enabled':True,'account_sid':'AC'+'1'*32,'service_sid':'VA'+'2'*32,'auth_token':'fixture','email_enabled':True,'whatsapp_enabled':True,'whatsapp_no_sms_fallback_confirmed':True}
        provider=TwilioVerify(config)
        with patch('identity_providers.request_json',return_value={'status':'pending'}) as request:
            provider.send('+85291234567','phone')
            self.assertEqual(parse_qs(request.call_args.args[1].decode())['Channel'],['whatsapp'])
            provider.send('test@example.test','email')
            self.assertEqual(parse_qs(request.call_args.args[1].decode())['Channel'],['email'])
        with patch('identity_providers.request_json',return_value={'status':'approved'}) as request:
            self.assertTrue(provider.check('+85291234567','123456'))
            self.assertTrue(request.call_args.args[0].endswith('/VerificationCheck'))
        with patch('identity_providers.request_json',return_value={'status':'pending'}):
            self.assertFalse(provider.check('test@example.test','000000'))
        provider.config['whatsapp_no_sms_fallback_confirmed']=False
        with patch('identity_providers.request_json') as request:
            from identity_providers import ProviderUnavailable
            with self.assertRaises(ProviderUnavailable):provider.send('+85291234567','phone')
            request.assert_not_called()

    def test_registration_channels_are_independent_and_fail_closed(self):
        self.otp.channels={'email'}
        page=self.client.get('/account/register/').get_data(as_text=True)
        self.assertIn('WhatsApp驗證尚未開通',page)
        response=self.post('/account/register/',{'kind':'phone','contact':'91234567','password':self.password,'confirm':self.password,'consent':'yes'})
        self.assertEqual(response.status_code,400)
        self.assertFalse(hasattr(self.otp,'last'))
        self.assertFalse(self.client.get('/healthz').json['whatsapp_verification_configured'])
        self.assertTrue(self.client.get('/healthz').json['email_verification_configured'])
        self.register('email','independent@example.test')
        self.post('/account/logout/')
        self.otp.channels={'phone'}
        page=self.client.get('/account/register/').get_data(as_text=True)
        self.assertIn('電郵驗證尚未開通',page)
        response=self.post('/account/register/',{'kind':'email','contact':'another@example.test','password':self.password,'confirm':self.password,'consent':'yes'})
        self.assertEqual(response.status_code,400)
        self.register('phone','98765432')
        self.assertEqual(self.otp.last,('+85298765432','phone'))

    def test_unavailable_channel_fails_before_account_lookup(self):
        self.register('phone','91234567')
        self.post('/account/logout/')
        self.otp.channels={'email'}
        for path in ('/account/code-login/','/account/forgot/'):
            self.client.get(path)
            for contact in ('91234567','98765432'):
                response=self.post(path,{'phase':'send','contact':contact})
                self.assertEqual(response.status_code,503)
                self.assertIn('所選驗證方式尚未開通',response.get_data(as_text=True))

    def test_expired_anonymous_challenges_are_removed_on_next_request(self):
        with self.ext['db']() as c:
            c.execute('INSERT INTO challenges(id,user_id,contact,kind,purpose,expires) VALUES (?,?,?,?,?,?)',('expired','dummy:expired','expired@example.test','email','login',time.time()-1))
        self.client.get('/account/code-login/')
        self.post('/account/code-login/',{'phase':'send','contact':'other@example.test'})
        with self.ext['db']() as c:
            self.assertIsNone(c.execute('SELECT id FROM challenges WHERE id=?',('expired',)).fetchone())

    def test_manual_test_webhook_cannot_verify_production_customer(self):
        ident=self.register();self.kyc.config['environment']='production'
        self.assertEqual(self.post('/account/identity/',{'consent':'yes'}).status_code,303)
        event={'externalUserId':ident,'levelName':'hkid-test','applicantType':'individual','type':'applicantReviewed','sandboxMode':False,'testMode':True,'reviewStatus':'completed','reviewResult':{'reviewAnswer':'GREEN'},'createdAtMs':datetime.now(timezone.utc).isoformat()}
        raw=json.dumps(event,separators=(',',':')).encode();digest=hmac.new(b'test-hook-only',raw,hashlib.sha256).hexdigest()
        self.assertEqual(self.client.post('/account/identity/webhook',data=raw,headers={'Content-Type':'application/json','X-Payload-Digest-Alg':'HMAC_SHA256_HEX','X-Payload-Digest':digest}).status_code,200)
        with self.ext['db']() as c:self.assertEqual(c.execute('SELECT kyc_status FROM customers WHERE id=?',(ident,)).fetchone()[0],'pending')

    def failed_login(self,client,ip):
        return client.post('/account/login/',data={'csrf':self.csrf(client),'contact':'nobody@example.test','password':'wrong-password-x'},environ_base={'REMOTE_ADDR':'127.0.0.1'},headers={'X-Forwarded-For':ip})
    def test_trusted_proxy_separates_visitors_and_spoofing_needs_trust(self):
        trusted=create_app(self.temp.name,{**self.config,'trusted_proxy_hops':1},providers=(self.otp,self.kyc));trusted.testing=True
        a=trusted.test_client();b=trusted.test_client();a.get('/account/login/');b.get('/account/login/')
        for _ in range(15):self.assertEqual(self.failed_login(a,'203.0.113.10').status_code,400)
        self.assertEqual(self.failed_login(a,'203.0.113.10').status_code,429)
        self.assertEqual(self.failed_login(b,'203.0.113.11').status_code,400)
        # Without a trusted proxy, a forged header does not create a fresh bucket.
        direct=self.app.test_client();direct.get('/account/login/')
        for i in range(15):self.failed_login(direct,'198.51.100.%d'%i)
        self.assertEqual(self.failed_login(direct,'198.51.100.99').status_code,429)
    def test_successful_logins_do_not_consume_shared_budget(self):
        self.register();self.post('/account/logout/')
        for _ in range(20):
            self.client.get('/account/login/')
            self.assertEqual(self.post('/account/login/',{'contact':'customer@example.test','password':self.password}).status_code,302)
            self.client.get('/account/');self.post('/account/logout/')
    def assert_unlocked(self):
        import sqlite3
        conn=sqlite3.connect(self.app.data_dir/'accounts.sqlite3',timeout=0)
        try:conn.execute('BEGIN IMMEDIATE');conn.rollback()
        finally:conn.close()
    def test_provider_check_runs_without_database_write_lock(self):
        ident=self.register();self.post('/account/logout/')
        seen=[]
        def check(contact,code):self.assert_unlocked();seen.append(contact);return code=='123456'
        self.otp.check=check
        self.client.get('/account/code-login/');self.post('/account/code-login/',{'phase':'send','contact':'customer@example.test'})
        self.assertEqual(self.post('/account/code-login/',{'phase':'confirm','code':'123456'}).status_code,302)
        self.client.get('/account/forgot/')
        self.post('/account/forgot/',{'phase':'send','contact':'customer@example.test'})
        self.assertEqual(self.post('/account/forgot/',{'phase':'confirm','code':'123456','password':'another-password-1','confirm':'another-password-1'}).status_code,302)
        self.client.get('/account/login/');self.post('/account/login/',{'contact':'customer@example.test','password':'another-password-1'})
        self.client.get('/account/');self.verify_contact('phone','91234567')
        self.assertEqual(len(seen),3)
    def test_same_code_redeems_once_under_concurrency(self):
        ident=self.register();self.post('/account/logout/')
        self.client.get('/account/code-login/');self.post('/account/code-login/',{'phase':'send','contact':'customer@example.test'})
        twin=self.app.test_client();twin.set_cookie('session',self.client.get_cookie('session').value)
        inner=[];started=[]
        def check(contact,code):
            # The twin request completes while the outer request is between its two transactions.
            if not started:started.append(1);inner.append(self.post('/account/code-login/',{'phase':'confirm','code':'123456'},twin).status_code)
            return code=='123456'
        self.otp.check=check
        outer=self.post('/account/code-login/',{'phase':'confirm','code':'123456'}).status_code
        self.assertEqual(sorted([outer,inner[0]]),[200,302])
        with self.ext['db']() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM account_audit WHERE action='code_login'").fetchone()[0],1)
    def test_contact_check_failure_still_counts_attempt(self):
        self.register();self.post('/account/verify/send/',{'kind':'phone','contact':'91234567'});self.client.get('/account/verify/confirm/')
        with patch.object(self.otp,'check',side_effect=ProviderFailure('unavailable')):
            for _ in range(5):self.assertEqual(self.post('/account/verify/confirm/',{'code':'123456'}).status_code,503)
        self.assertEqual(self.post('/account/verify/confirm/',{'code':'123456'}).status_code,400)
    def test_contact_probe_is_rate_limited_before_lookup(self):
        self.register('phone','91234567');self.post('/account/logout/');self.register('email','prober@example.test')
        codes=[]
        for i in range(6):
            key=hashlib.sha256((self.config['secret_key']+'send-contact:+85291234567').encode()).hexdigest()
            with self.ext['db']() as c:c.execute('DELETE FROM account_attempts WHERE key=?',(key,))
            codes.append(self.post('/account/verify/send/',{'kind':'phone','contact':'91234567'}).status_code)
        self.assertEqual(codes,[409]*5+[429])
    def test_failed_background_delivery_cannot_be_approved(self):
        self.register();self.post('/account/logout/');self.client.get('/account/code-login/')
        release=__import__('threading').Event()
        def slow_fail(contact,kind):release.wait(5);raise ProviderFailure('unavailable')
        self.otp.send=slow_fail
        started=time.monotonic()
        self.assertEqual(self.post('/account/code-login/',{'phase':'send','contact':'customer@example.test'}).status_code,200)
        self.assertLess(time.monotonic()-started,3)
        release.set();self.ext['drain'](5)
        with patch.object(self.otp,'check',return_value=True) as check:
            self.assertEqual(self.post('/account/code-login/',{'phase':'confirm','code':'123456'}).status_code,200)
        check.assert_not_called()

if __name__=='__main__':unittest.main()
