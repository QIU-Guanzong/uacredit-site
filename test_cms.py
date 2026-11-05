import json, secrets, tempfile, unittest
from pathlib import Path
from werkzeug.security import generate_password_hash
from cms import create_app, ROOT, CODE_VERSION

class ContentDeskTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'work')
        self.password=secrets.token_urlsafe(24)
        self.app=create_app(self.temp.name,{'username':'test-editor','password_hash':generate_password_hash(self.password),'secret_key':secrets.token_hex(32),'secure_cookie':False})
        self.app.testing=True;self.client=self.app.test_client()
    def tearDown(self):self.temp.cleanup()
    def csrf(self):
        with self.client.session_transaction() as sess:return sess['csrf']
    def login(self):
        self.client.get('/admin/login')
        r=self.client.post('/admin/login',data={'csrf':self.csrf(),'username':'test-editor','password':self.password});self.assertEqual(r.status_code,302)
        self.client.get('/admin/')
    def get_page(self,path):
        response=self.client.get(path)
        text=response.get_data(as_text=True);response.close();return text
    def test_admin_login_checks_password_even_for_wrong_username(self):
        from unittest.mock import patch
        self.client.get('/admin/login')
        with patch('cms.check_password_hash',return_value=False) as check:
            self.client.post('/admin/login',data={'csrf':self.csrf(),'username':'someone-else','password':'x'})
        check.assert_called_once()
    def test_protocol_relative_links_are_dropped(self):
        from original_content import SafeOriginal
        html=SafeOriginal({}).render('<a href="//evil.example/x">a</a><a href="/\\evil.example">b</a><a href="/contact/">c</a>')
        self.assertNotIn('evil.example',html);self.assertIn('href="/contact/"',html)
    def publish_about(self):
        self.login()
        data={'csrf':self.csrf(),'revision':'0','title':'測試標題','content':'<p>測試正文</p>'}
        self.client.post('/admin/edit/88',data=data)
        self.assertEqual(self.client.post('/admin/publish/88',data={'csrf':self.csrf(),'revision':'1'}).status_code,302)
    def test_published_copy_is_rebuilt_after_code_upgrade_and_keeps_edits(self):
        self.publish_about();root=Path(self.temp.name);before=(root/'current').resolve()
        self.assertEqual((before.parent/'code_version').read_text(),CODE_VERSION)
        (before.parent/'code_version').write_text('older')
        config={'username':'test-editor','password_hash':generate_password_hash(self.password),'secret_key':secrets.token_hex(32),'secure_cookie':False}
        app=create_app(self.temp.name,config);app.testing=True
        after=(root/'current').resolve();self.assertNotEqual(before,after)
        self.assertEqual((after.parent/'code_version').read_text(),CODE_VERSION)
        response=app.test_client().get('/about-us/');page=response.get_data(as_text=True);response.close();self.assertIn('測試標題',page)
        create_app(self.temp.name,config);self.assertEqual((root/'current').resolve(),after)
    def test_failed_refresh_keeps_existing_published_copy(self):
        from unittest.mock import patch
        self.publish_about();root=Path(self.temp.name);before=(root/'current').resolve()
        (before.parent/'code_version').write_text('older')
        config={'username':'test-editor','password_hash':generate_password_hash(self.password),'secret_key':secrets.token_hex(32),'secure_cookie':False}
        with patch('cms.subprocess.run',side_effect=RuntimeError('boom')):app=create_app(self.temp.name,config)
        self.assertEqual((root/'current').resolve(),before)
        response=app.test_client().get('/about-us/');page=response.get_data(as_text=True);response.close();self.assertIn('測試標題',page)
        self.assertEqual(sorted(p.name for p in (root/'releases').iterdir()),[before.parent.name])
    def test_launch_switch_controls_indexing_for_public_pages_only(self):
        import os,subprocess,sys
        from unittest.mock import patch
        root=Path(self.temp.name);flag=root/'launch.json'
        def build(value):
            flag.write_text(json.dumps({'indexable':value}));out=root/('www-%s'%value)
            env={**os.environ,'UACREDIT_LAUNCH':str(flag),'UACREDIT_BUILD_DIR':str(out)}
            subprocess.run([sys.executable,str(ROOT/'build.py')],env=env,check=True,capture_output=True);return out
        off=build(False);self.assertIn('noindex',(off/'index.html').read_text());self.assertIn('Disallow: /\n',(off/'robots.txt').read_text());self.assertFalse((off/'sitemap.xml').exists())
        on=build(True);home=(on/'index.html').read_text()
        self.assertIn('content="index,follow"',home);self.assertNotIn('noindex',home);self.assertNotIn('網站預覽',home);self.assertNotIn('重建預覽',home)
        self.assertIn('Sitemap: https://uacredit.hk/sitemap.xml',(on/'robots.txt').read_text())
        sitemap=(on/'sitemap.xml').read_text();self.assertIn('<loc>https://uacredit.hk/car-loan/</loc>',sitemap);self.assertNotIn('/account',sitemap);self.assertNotIn('/admin',sitemap)
        with patch.dict(os.environ,{'UACREDIT_LAUNCH':str(flag)}):
            live=create_app(root/'data',{'username':'u','password_hash':generate_password_hash('x'),'secret_key':secrets.token_hex(16),'secure_cookie':False}).test_client()
        for path,expect in [('/car-loan/',False),('/admin/login',True),('/account/login/',True),('/healthz',True)]:
            response=live.get(path);self.assertEqual('X-Robots-Tag' in response.headers,expect,path);response.close()
    def test_access_csrf_and_rate_limit(self):
        self.assertEqual(self.client.get('/admin/').status_code,302)
        self.assertEqual(self.client.post('/admin/new',data={'slug':'oops'}).status_code,400)
        self.client.get('/admin/login')
        for _ in range(5):self.client.post('/admin/login',data={'csrf':self.csrf(),'username':'test-editor','password':'incorrect'})
        self.assertEqual(self.client.post('/admin/login',data={'csrf':self.csrf(),'username':'test-editor','password':self.password}).status_code,429)
    def test_draft_conflict_publish_and_preserve_source(self):
        initial=(ROOT/'content/site.json').read_bytes();self.login()
        data={'csrf':self.csrf(),'revision':'0','title':'測試標題','content':'<p>測試正文</p><script>alert(1)</script><img src=x onerror=alert(1)><a href="javascript:alert(1)">連結</a>'}
        r=self.client.post('/admin/edit/88',data=data);self.assertEqual(r.status_code,302)
        self.assertEqual(self.client.post('/admin/edit/88',data=data).status_code,409)
        self.assertNotIn('測試標題',self.get_page('/about-us/'))
        self.assertEqual(self.client.post('/admin/publish/88',data={'csrf':self.csrf(),'revision':'1'}).status_code,302)
        page=self.get_page('/about-us/')
        self.assertIn('測試標題',page);self.assertIn('測試正文',page);self.assertNotIn('alert(1)',page);self.assertNotIn('onerror=',page)
        self.assertEqual(initial,(ROOT/'content/site.json').read_bytes())
        live=json.loads((Path(self.temp.name)/'live.json').read_text());self.assertEqual(len(live['records']),43)
        response=self.client.get('/assets/logo.png');self.assertEqual(response.status_code,200);response.close()
    def test_new_post_route_collision_and_sandbox(self):
        self.login()
        for slug in ['car-loan','admin','../evil','updates']:
            self.assertIn(self.client.post('/admin/new',data={'csrf':self.csrf(),'slug':slug}).status_code,[400,409])
        r=self.client.post('/admin/new',data={'csrf':self.csrf(),'slug':'new-company-offer'});self.assertEqual(r.status_code,302)
        self.assertEqual(self.client.get('/content/site.json').status_code,404)
        response=self.client.get('/unknown-page/');self.assertEqual(response.status_code,404);response.close()
        self.assertEqual(self.client.get('/healthz').json['site'],'uacredit')
    def test_homepage_heading_remains_editable_after_visual_refresh(self):
        self.login();record=next(r for r in json.loads((ROOT/'content/site.json').read_text())['records'] if r['id']==2)
        response=self.client.post('/admin/edit/2',data={'csrf':self.csrf(),'revision':'0','title':'主頁','content':record['content']['rendered'],'hero_line_1':'測試汽車服務','hero_line_2':'測試物業服務'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.client.post('/admin/publish/2',data={'csrf':self.csrf(),'revision':'1'}).status_code,302)
        page=self.get_page('/')
        self.assertIn('<h1>測試汽車服務<br><span>測試物業服務</span></h1>',page)

    def test_old_default_headline_is_updated_but_custom_settings_are_preserved(self):
        self.login()
        settings=Path(self.temp.name)/'settings.json'
        for headline,expected in [
            ({'hero_line_1':'下一程，','hero_line_2':'由你作主。'},'汽車上會・汽車翻按'),
            ({'hero_line_1':'自訂主標題','hero_line_2':'自訂副標題'},'自訂主標題'),
        ]:
            settings.write_text(json.dumps(headline,ensure_ascii=False))
            self.assertEqual(self.client.post('/admin/edit/88',data={'csrf':self.csrf(),'revision':'0','title':'測試公司資料','content':'<p>測試</p>'}).status_code,302)
            self.assertEqual(self.client.post('/admin/publish/88',data={'csrf':self.csrf(),'revision':'1'}).status_code,302)
            self.assertIn(expected,self.get_page('/'))
            self.assertEqual(json.loads(settings.read_text()),headline)

    def test_contact_numbers_update_across_pages_without_swap_collision(self):
        self.login();record=next(r for r in json.loads((ROOT/'content/site.json').read_text())['records'] if r['id']==110)
        self.assertEqual(self.client.post('/admin/edit/110',data={'csrf':self.csrf(),'revision':'0','title':'聯絡我們','content':record['content']['rendered'],'phone_main':'2886 8044','phone_secondary':'2886 8345'}).status_code,302)
        self.assertEqual(self.client.post('/admin/publish/110',data={'csrf':self.csrf(),'revision':'1'}).status_code,302)
        page=self.get_page('/')
        self.assertIn('href="tel:+85228868044">2886 8044',page)

if __name__=='__main__':unittest.main()
