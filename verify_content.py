"""Independent migration checks against the captured public source."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlparse,unquote
import hashlib,json,re
ROOT=Path(__file__).parent
class TextAndLinks(HTMLParser):
    def __init__(self):super().__init__();self.text=[];self.links=[];self.skip=0
    def handle_starttag(self,t,a):
        if t in {'script','style','svg','noscript'}:self.skip+=1
        for k,v in a:
            if k in {'href','src'} and v:self.links.append(v)
    def handle_endtag(self,t):
        if t in {'script','style','svg','noscript'}:self.skip=max(0,self.skip-1)
    def handle_data(self,s):
        if not self.skip and s.strip():self.text.append(re.sub(r'\s+','',s))
def parse(s):p=TextAndLinks();p.feed(s);return p
source=json.loads((ROOT/'content/site.json').read_text());errors=[]
contact_routes={'car-loan-application','property-loan-application','free-car-valuation','cooperative-merchant'}
replaced_source_routes=contact_routes | {'car-loan'}
for r in source['records']:
    page=ROOT/'dist'/r['route']/'index.html'
    if not page.exists():errors.append('missing route '+r['route']);continue
    if r['route'] in replaced_source_routes:
        html=page.read_text()
        if '資料取自2026年10月26日的原網站' in html or '申請表預覽：正式收件渠道尚未接通' in html:errors.append('obsolete notice: '+r['route'])
        if r['route'] in contact_routes and ('href="/contact/' not in html or '<fieldset disabled=' in html):errors.append('contact route invalid: '+r['route'])
        continue
    expected=parse(r['content']['rendered']).text;actual=''.join(parse(page.read_text()).text);cursor=0
    for chunk in expected:
        found=actual.find(chunk,cursor)
        if found<0:errors.append('missing source text: '+str(r['id'])+' '+chunk[:90]);break
        cursor=found+len(chunk)
for url,a in source['assets'].items():
    p=ROOT/'dist'/a['path'].lstrip('/')
    if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=a['sha256']:errors.append('asset hash mismatch '+url)
broken=set()
for p in (ROOT/'dist').rglob('*.html'):
    html=p.read_text()
    if any(notice in html for notice in ('資料取自2026年10月26日的原網站','歷史內容及優惠請留意原有日期','歷史內容請留意發佈日期')):
        errors.append('obsolete historical notice: '+str(p.relative_to(ROOT/'dist')))
    for link in parse(html).links:
        if not link.startswith('/') or link.startswith('//'):continue
        path=unquote(urlparse(link).path)
        dest=ROOT/'dist'/path.lstrip('/')
        if path.startswith(('/admin','/account')):continue
        if not dest.is_file() and not (dest/'index.html').is_file():broken.add(path)
errors.extend('broken local link '+x for x in sorted(broken))
report={'source_pages':source['pages_total'],'source_posts':source['posts_total'],'categories':len(source['categories']),'verified_assets':len(source['assets']),'built_pages':len(list((ROOT/'dist').rglob('index.html'))),'errors':errors}
(ROOT/'work/evidence/migration-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(bool(errors))
