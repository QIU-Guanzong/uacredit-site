"""Optional verification adapters. No mock success exists in the runtime path."""
import base64,hashlib,hmac,json,re,time
from urllib.request import Request,urlopen
from urllib.parse import urlencode,urlparse

class ProviderUnavailable(Exception):pass
class ProviderFailure(Exception):pass

def request_json(url,body,headers):
    try:
        with urlopen(Request(url,data=body,headers=headers,method='POST'),timeout=12) as response:
            return json.load(response)
    except Exception as exc:raise ProviderFailure('驗證服務暫時未能回應，請稍後再試。') from exc

class TwilioVerify:
    def __init__(self,config):self.config=config
    @property
    def credentials_ready(self):
        account=self.config.get('account_sid');service=self.config.get('service_sid');token=self.config.get('auth_token')
        return (self.config.get('enabled') is True and isinstance(account,str) and re.fullmatch(r'AC[0-9a-fA-F]{32}',account) is not None
                and isinstance(service,str) and re.fullmatch(r'VA[0-9a-fA-F]{32}',service) is not None and isinstance(token,str) and bool(token.strip()))
    def supports(self,kind):
        flags={'email':'email_enabled','phone':'whatsapp_enabled'}
        return (self.credentials_ready and kind in flags and self.config.get(flags[kind]) is True
                and (kind!='phone' or self.config.get('whatsapp_no_sms_fallback_confirmed') is True))
    @property
    def ready(self):return self.supports('email') or self.supports('phone')
    def call(self,path,data):
        if not self.credentials_ready:raise ProviderUnavailable('驗證服務尚未開通。')
        sid=self.config['service_sid']
        if not sid.startswith('VA') or not sid.isalnum():raise ProviderUnavailable('驗證服務設定未完成。')
        auth=base64.b64encode((self.config['account_sid']+':'+self.config['auth_token']).encode()).decode()
        return request_json('https://verify.twilio.com/v2/Services/'+sid+'/'+path,urlencode(data).encode(),{'Authorization':'Basic '+auth,'Content-Type':'application/x-www-form-urlencoded'})
    def send(self,contact,kind):
        if not self.supports(kind):raise ProviderUnavailable('所選驗證方式尚未開通。')
        result=self.call('Verifications',{'To':contact,'Channel':'whatsapp' if kind=='phone' else 'email'})
        if result.get('status')!='pending':raise ProviderFailure('驗證碼未能發送，請稍後再試。')
    def check(self,contact,code):
        kind='email' if '@' in contact else 'phone'
        if not self.supports(kind):raise ProviderUnavailable('所選驗證方式尚未開通。')
        return self.call('VerificationCheck',{'To':contact,'Code':code}).get('status')=='approved'

class SumsubIdentity:
    def __init__(self,config):self.config=config
    @property
    def ready(self):
        return (self.config.get('enabled') is True and self.config.get('hkid_level_confirmed') is True
                and self.config.get('environment') in {'sandbox','production'}
                and all(isinstance(self.config.get(k),str) and self.config[k].strip() for k in ['app_token','secret_key','webhook_secret','level_name']))
    @property
    def sandbox(self):return self.config.get('environment','sandbox')!='production'
    def create_link(self,user_id):
        if not self.ready:raise ProviderUnavailable('香港身份證驗證服務尚未開通。')
        path='/resources/sdkIntegrations/levels/-/websdkLink'
        body=json.dumps({'levelName':self.config['level_name'],'userId':user_id,'ttlInSecs':1800},separators=(',',':')).encode()
        ts=str(int(time.time()))
        signature=hmac.new(self.config['secret_key'].encode(),ts.encode()+b'POST'+path.encode()+body,hashlib.sha256).hexdigest()
        response=request_json('https://api.sumsub.com'+path,body,{'Content-Type':'application/json','X-App-Token':self.config['app_token'],'X-App-Access-Ts':ts,'X-App-Access-Sig':signature})
        link=response.get('url','');p=urlparse(link)
        if p.scheme!='https' or not (p.hostname=='sumsub.com' or (p.hostname or '').endswith('.sumsub.com')):raise ProviderFailure('身份驗證連結未能建立，請稍後再試。')
        return link
    def validate_webhook(self,raw,headers):
        if not self.ready:return False
        if headers.get('X-Payload-Digest-Alg')!='HMAC_SHA256_HEX':return False
        expected=hmac.new(self.config['webhook_secret'].encode(),raw,hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected,headers.get('X-Payload-Digest',''))
