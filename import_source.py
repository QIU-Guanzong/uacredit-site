"""Import public WordPress content and referenced media without login access."""
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlparse, unquote
from html import unescape
from concurrent.futures import ThreadPoolExecutor
import json, re, hashlib

ROOT=Path(__file__).parent
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
def fetch(url):
    with urlopen(Request(url,headers={'User-Agent':UA,'Accept':'text/html'}),timeout=30) as r:return r.read()
raw={k:json.loads((ROOT/'work/evidence'/('wp-'+k+'.json')).read_text()) for k in ['pages','posts','categories','media']}
raw['media']+=json.loads(fetch('https://www.uacredit.hk/wp-json/wp/v2/media?per_page=100&page=2'))
media={m['id']:m for m in raw['media']}
records=[]
urls=set()
for kind in ['pages','posts']:
    for x in raw[kind]:
        body=x['content']['rendered']
        # Keep original editorial content and dates; exclude plugin settings and unrelated metadata.
        record={k:x[k] for k in ['id','link','date','modified','slug','title','content','featured_media']}
        record['type']=kind;record['categories']=x.get('categories',[])
        record['route']=unquote(urlparse(x['link']).path).strip('/')
        record['source_sha256']=hashlib.sha256(body.encode()).hexdigest()
        normalized=unescape(body).replace('\\/','/')
        images=list(dict.fromkeys(re.findall(r'https://www\.uacredit\.hk/wp-content/uploads/[^\s"<>\\]+?\.(?:png|jpg|jpeg|webp|gif)',normalized)))
        if x['featured_media'] in media:
            m=media[x['featured_media']]
            feature=m.get('media_details',{}).get('sizes',{}).get('large',{}).get('source_url') or m['source_url']
            record['featured_image']=feature;images.append(feature)
        record['source_images']=list(dict.fromkeys(images))
        urls.update(images);records.append(record)

for route,css in [('', 'post-2.css'),('car-loan','post-606.css'),('property-loan','post-611.css')]:
    style=fetch('https://www.uacredit.hk/wp-content/uploads/elementor/css/'+css).decode()
    backgrounds=re.findall(r'url\((https://www\.uacredit\.hk/wp-content/uploads/[^)]+)\)',style)
    record=next(r for r in records if r['route']==route)
    record['background_images']=backgrounds
    record['source_images']=list(dict.fromkeys(record['source_images']+backgrounds));urls.update(backgrounds)

assets=ROOT/'dist/assets/original';assets.mkdir(parents=True,exist_ok=True)
def download(url):
    suffix=Path(urlparse(url).path).suffix.lower()
    name=hashlib.sha256(url.encode()).hexdigest()[:16]+suffix
    p=assets/name
    try:
        if not p.exists():p.write_bytes(fetch(url))
        b=p.read_bytes()
        return url,{'path':'/assets/original/'+name,'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
    except Exception as e:return url,{'error':str(e)}
with ThreadPoolExecutor(max_workers=3) as pool:downloaded=dict(pool.map(download,sorted(urls)))
# Retain one authoritative file for byte-identical images, including existing source assets.
by_hash={}
for p in sorted((ROOT/'dist/assets').glob('*')):
    if p.is_file() and p.suffix.lower() in {'.jpg','.png','.jpeg','.webp','.gif'}:by_hash[hashlib.sha256(p.read_bytes()).hexdigest()]='/assets/'+p.name
for url,a in downloaded.items():
    if 'path' not in a:continue
    if a['sha256'] in by_hash and a['path']!=by_hash[a['sha256']]:
        (ROOT/'dist'/a['path'].lstrip('/')).unlink();a['path']=by_hash[a['sha256']]
    else:by_hash[a['sha256']]=a['path']
out={'captured_at':'2026-10-26','source_origin':'https://www.uacredit.hk','pages_total':len(raw['pages']),'posts_total':len(raw['posts']),'media_total':len(raw['media']),'categories':raw['categories'],'records':records,'assets':downloaded}
(ROOT/'content').mkdir(exist_ok=True)
(ROOT/'content/site.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({'pages':out['pages_total'],'posts':out['posts_total'],'categories':len(out['categories']),'referenced_images':len(urls),'downloaded':sum('path' in v for v in downloaded.values()),'failures':{u:v for u,v in downloaded.items() if 'error'in v}},ensure_ascii=False))
