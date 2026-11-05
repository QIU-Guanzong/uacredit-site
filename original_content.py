"""Re-layout imported public content while keeping its text and original URLs."""
from html.parser import HTMLParser
from html import escape, unescape
from urllib.parse import urlparse, unquote
import json, re, os

class SafeOriginal(HTMLParser):
    def __init__(self, assets, form_contact=None):
        super().__init__(convert_charrefs=True)
        self.parts=[];self.stack=[];self.suppressed=0;self.assets=assets;self.form_contact=form_contact
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag == 'form' and self.form_contact and not self.suppressed:
            self.parts.append(f'<p><a class="button" href="{escape(self.form_contact,quote=True)}">聯絡我們查詢 ↗</a></p>')
            self.suppressed+=1;self.stack.append((tag,None,True));return
        if tag in {'script','style','noscript','svg'} or self.suppressed:
            if tag not in {'img','input','br','hr','meta','link','source'}:
                self.suppressed+=1;self.stack.append((tag,None,True))
            return
        if tag=='input' and a.get('type')=='hidden':return
        if tag=='iframe':
            src=a.get('src',''); label='查看原站影片' if 'youtube' in src else '查看原站外部內容'
            if src.startswith('https://'):self.parts.append(f'<p><a href="{escape(src,quote=True)}" rel="noopener noreferrer" target="_blank">{label} ↗</a></p>')
            self.stack.append((tag,None,False));return
        allowed={'div','section','span','p','h1','h2','h3','h4','h5','h6','ul','ol','li','strong','b','em','i','u','s','br','hr','a','img','blockquote','table','thead','tbody','tr','td','th','label','form','input','select','option','textarea','button','fieldset','legend'}
        if tag not in allowed:
            self.stack.append((tag,None,False));return
        out={'h1':'h2','section':'div','form':'fieldset'}.get(tag,tag)
        attributes=[]
        if tag=='a':
            href=a.get('href','')
            if href in {'#','/#',''}:href='/contact/'
            if href.startswith(('https://www.uacredit.hk','https://uacredit.hk','http://www.uacredit.hk','http://uacredit.hk')):
                href=urlparse(href).path
                if href and not href.endswith('/') and not href.split('/')[-1].count('.'):href+='/'
            if href.startswith(('https://','http://','/','tel:','mailto:','#')) and not href.startswith(('//','/\\')):attributes.append(('href',href))
            if href.startswith(('http://','https://')):attributes.extend([('target','_blank'),('rel','noopener noreferrer')])
        if tag=='img':
            src=a.get('src','');asset=self.assets.get(src)
            if not asset and src.startswith('/assets/') and '..' not in src:asset={'path':src}
            if not asset:return
            attributes=[('src',asset['path']),('alt',a.get('alt') or '原站圖片'),('loading','lazy')]
        if tag in {'form','fieldset'}:attributes.append(('disabled','disabled'))
        if tag in {'input','button','select','textarea'}:attributes.append(('disabled','disabled'))
        if tag=='input':
            attributes.extend([(k,v) for k,v in a.items() if k in {'type','placeholder','value','checked'} and v is not None])
        if tag=='button':attributes.append(('type','button'))
        if tag in {'input','select','textarea'} and 'id' in a:attributes.append(('id','original-'+a['id']))
        if tag=='label' and 'for' in a:attributes.append(('for','original-'+a['for']))
        if tag in {'td','th'}:attributes.extend([(k,v) for k,v in a.items() if k in {'colspan','rowspan'}])
        cls=a.get('class','')
        if 'wpforms-field ' in cls:attributes.append(('class','original-field'))
        elif 'elementor-widget-container' in cls:attributes.append(('class','source-block'))
        elif 'swiper-slide-contents' in cls:attributes.append(('class','source-slide'))
        text=''.join(' '+k+'="'+escape(str(v),quote=True)+'"' for k,v in attributes)
        self.parts.append('<'+out+text+'>')
        if tag not in {'img','input','br','hr'}:self.stack.append((tag,out,False))
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in {'img','input','br','hr','meta','link','source'}:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:
                entries=self.stack[i:];self.stack=self.stack[:i]
                for _,out,suppressed in reversed(entries):
                    if suppressed:self.suppressed=max(0,self.suppressed-1)
                    elif out:self.parts.append('</'+out+'>')
                return
    def handle_data(self,data):
        if not self.suppressed:self.parts.append(escape(data))
    def render(self,body):
        self.feed(body)
        while self.stack:
            _,out,skip=self.stack.pop()
            if out:self.parts.append('</'+out+'>')
        return ''.join(self.parts)

def add_originals(pages,root,intro):
    source=json.loads(open(os.environ.get('UACREDIT_CONTENT',str(root/'content/site.json'))).read())
    records=source['records'];assets=source['assets']
    baseline={r['id']:r for r in json.loads((root/'content/site.json').read_text())['records']}
    edited_ids={r['id'] for r in records if r['id'] not in baseline or any(r.get(k)!=baseline[r['id']].get(k) for k in ['modified','title','content'])}
    for c in source['categories']:c['count']=sum(c['id'] in r['categories'] for r in records)
    field_notice='<p class="source-notice">申請表預覽：正式收件渠道尚未接通，此頁不會收集或提交資料；請透過聯絡頁查詢。</p>'
    form_contacts={'car-loan-application':'/contact/?service=car','property-loan-application':'/contact/?service=property','free-car-valuation':'/contact/?service=car','cooperative-merchant':'/contact/'}
    def original(r):
        form_contact=form_contacts.get(r['route'])
        if form_contact and r.get('source_sha256') and r['id'] not in edited_ids:
            return f'<p>請聯絡環聯查詢詳情。</p><p><a class="button" href="{escape(form_contact,quote=True)}">聯絡我們 ↗</a></p>'
        rendered=SafeOriginal(assets,form_contact=form_contact).render(r['content']['rendered'])
        feature=r.get('featured_image')
        if feature in assets and feature not in r['content']['rendered']:
            rendered=f'<img class="article-feature" src="{assets[feature]["path"]}" alt="{escape(unescape(r["title"]["rendered"]),quote=True)}" loading="lazy">'+rendered
        # Elementor embeds slide imagery in settings rather than img elements.
        backgrounds=r.get('background_images',[])
        if backgrounds:
            rendered+='<div class="original-gallery">'+''.join(f'<img src="{assets[u]["path"]}" alt="原站橫幅圖片" loading="lazy">' for u in backgrounds if u in assets)+'</div>'
        return (field_notice if not form_contact and '<form' in r['content']['rendered'] else '')+'<div class="original-content">'+rendered+'</div>'
    for r in records:
        slug=r['route'];title=unescape(r['title']['rendered'])
        if slug in pages and slug not in {'','contact'} and r['id'] in edited_ids:
            body=intro('環聯信貸',escape(title),'')+'<article class="prose">'+original(r)+'</article></div>'
            pages[slug]=(title+'｜環聯信貸',title,body)
        elif slug in pages:
            if slug == 'car-loan' and r.get('source_sha256') and r['id'] not in edited_ids:
                continue
            oldtitle,description,body=pages[slug]
            label='查看原站主頁完整資料' if slug=='' else '查看原站完整資料'
            archive='<section class="section wrap archive-section"><details><summary>'+label+'</summary>'+original(r)+'</details></section>'
            pages[slug]=(oldtitle,description,body+archive)
        else:
            content=intro('UACREDIT / '+('INFORMATION' if r['type']=='pages' else 'JOURNAL'),escape(title),'')
            cats=[c['name'] for c in source['categories'] if c['id'] in r['categories']]
            metadata=f'<p class="article-meta">發佈日期：'+r['date'][:10]+(' · '+' / '.join(cats) if cats else '')+'</p>' if r['type']=='posts' else ''
            side='<aside class="aside"><h2>需要查詢？</h2><p>服務詳情及現行條款，請向環聯確認。</p><a class="button" href="/contact/">聯絡環聯 ↗</a><div class="aside-links"><a href="/car-loan/">汽車貸款 →</a><a href="/property-loan/">物業貸款 →</a><a href="/all-pages/">所有網站內容 →</a></div></aside>'
            pages[slug]=(title+'｜環聯亞洲信貸',title+'。環聯（亞洲）信貸有限公司原站資料完整遷移。',content+'<div class="split"><article>'+metadata+original(r)+'</article>'+side+'</div></div>')
    def record_href(record):
        route=record['route'].strip('/')
        return '/' + (route+'/' if route else '')
    search='<div class="content-filter" hidden><label for="content-query">找資料<input type="search" id="content-query" placeholder="輸入服務、商戶或消息名稱" autocomplete="off"></label><button type="button" class="filter-clear" hidden>清除</button><p class="filter-status" role="status" aria-live="polite"></p></div><p class="filter-empty" hidden>未找到相符資料。試試其他名稱，或清除搜尋。</p>'
    def list_items(items):
        return '<div class="editorial-list">'+''.join(f'<a href="{record_href(r)}"><span class="list-date">{r["date"][:10]}</span><span>{escape(unescape(r["title"]["rendered"]))}</span><span aria-hidden="true">↗</span></a>' for r in items)+'</div>'
    for c in source['categories']:
        slug='category/'+c['slug'];items=[r for r in records if c['id'] in r['categories']]
        pages[slug]=(c['name']+'｜環聯亞洲信貸',c['name']+'：環聯內容。',intro('分類',c['name'],'')+list_items(items)+'</div>')
    category_links='<div class="category-tabs">'+''.join(f'<a href="/category/{c["slug"]}/">{c["name"]} <span>{c["count"]}</span></a>' for c in source['categories'])+'</div>'
    pages['updates']=('消息與優惠｜環聯亞洲信貸','公司動態、醒目貼士、公司優惠、商戶優惠及合作商戶。',intro('消息與優惠','消息、優惠與合作商戶','查看消息、優惠及合作商戶資料。')+search+category_links+list_items([r for r in records if r['type']=='posts'])+'</div>')
    pages['all-pages']=('網站內容一覽｜環聯亞洲信貸','環聯網站全部頁面、服務、申請資料、合作商戶及消息分類。',intro('網站資料','網站內容一覽','查看服務、公司資料、消息及合作商戶。')+search+'<h2>服務與公司資料</h2>'+list_items([r for r in records if r['type']=='pages'])+'<h2 class="directory-heading">消息與商戶</h2>'+category_links+list_items([r for r in records if r['type']=='posts'])+'</div>')
    return source
