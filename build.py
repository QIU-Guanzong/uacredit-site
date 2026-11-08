"""Build an owner-private design preview. No customer records or credentials."""
from pathlib import Path
from html import escape
import json, os, re

ROOT = Path(__file__).parent
DIST = Path(os.environ.get('UACREDIT_BUILD_DIR', str(ROOT / 'dist')))
DIST.mkdir(parents=True, exist_ok=True)
ORIGIN = os.environ.get('UACREDIT_ORIGIN', 'https://uacredit.hk').rstrip('/')
# Launch switch shipped with the code: public pages are indexable only after launch.json says so.
LAUNCH_PATH = Path(os.environ.get('UACREDIT_LAUNCH', str(ROOT / 'content/launch.json')))
INDEXABLE = json.loads(LAUNCH_PATH.read_text()).get('indexable') is True if LAUNCH_PATH.exists() else False
APPLICATIONS_ENABLED = os.environ.get('UACREDIT_APPLICATIONS_ENABLED') == '1'
ROBOTS = 'index,follow' if INDEXABLE else 'noindex,nofollow'
def launched(text):
    if not INDEXABLE:return text
    if APPLICATIONS_ENABLED:text=text.replace('<div class="preview">網站預覽 · 暫不接受網上貸款申請</div>','')
    for old,new in [('網站預覽 · 暫不接受網上貸款申請','網上貸款申請暫未開通 · 請致電或 WhatsApp 查詢'),('本預覽不提供貸款報價或批核。','本網站不提供網上貸款報價或批核。'),(' · 網站重建預覽','')]:text=text.replace(old,new)
    return text
pages = {}
links = [('car-loan','汽車貸款'),('property-loan','物業貸款'),('updates','消息與優惠'),('about-us','關於環聯'),('faq','常見問題'),('account/login','客戶登入')]

def header(slug):
    nav=''.join(f'<a href="/{p}/"'+(' aria-current="page"' if p==slug else '')+f'>{label}</a>' for p,label in links)
    return f'''<div class="preview">網站預覽 · 暫不接受網上貸款申請</div>
    <a class="skip" href="#main">跳至主要內容</a><header><div class="wrap header-inner">
    <a class="brand" href="/" aria-label="環聯亞洲信貸首頁"><img src="/assets/brand-mark.png" width="38" height="38" alt=""><span class="brand-wordmark">UACREDIT<small>環聯信貸</small></span></a>
    <button class="menu" aria-expanded="false" aria-controls="navigation">選單 +</button>
    <nav id="navigation" aria-label="主要導覽">{nav}<a href="/contact/"{(' aria-current="page"' if slug=='contact' else '')}>聯絡我們</a></nav>
    <a class="phone" href="tel:+85228868345">2886 8345 ↗</a></div></header>'''

def footer():
    return '''<section class="contact-band"><div class="wrap"><div><h2>聯絡環聯</h2><p>電話、WhatsApp 或電郵查詢。</p></div><a class="button" href="/contact/">睇聯絡方法 <span aria-hidden="true">↗</span></a></div></section>
    <footer><div class="wrap"><div class="footer-grid"><div><h3>環聯(亞洲)信貸有限公司</h3><p>Universal (Asia) Credit Limited<br>九龍馬頭圍道39號<br>紅磡商業中心A座3樓306A室</p></div><div><h3>與我們聯絡</h3><p><a href="tel:+85228868345">2886 8345</a> · 車會查詢<br><a href="tel:+85228868144">2886 8144</a> · 查詢及投訴<br><a href="mailto:cs@uacredit.com.hk">cs@uacredit.com.hk</a><br><a href="https://wa.me/85260855201" target="_blank" rel="noopener noreferrer">6085 5201</a> · WhatsApp<br>營業時間：星期一至五 09:30–18:30，星期六 09:30–13:00</p></div><div><h3>網站資訊</h3><div class="footer-links"><a href="/about-us/">關於環聯</a><a href="/faq/">常見問題</a><a href="/all-pages/">所有網站內容</a><a href="/car-loan-application/">汽車貸款申請</a><a href="/property-loan-application/">物業貸款申請</a><a href="/free-car-valuation/">免費汽車估價</a><a href="/cooperative-merchant/">成為合作商戶</a><a href="/privacy-policy/">私隱政策</a><a href="/money-lenders-ordinance/">放債人條例撮要</a><a href="/privacy/">網站使用說明</a><a href="/contact/">營業時間及地址</a></div></div></div>
    <div class="warning">忠告：借錢梗要還，咪俾錢中介</div><p class="small">放債人牌照號碼：1866/2025。本預覽不提供貸款報價或批核。</p>
    <div class="legal-line"><span>© 2026 Universal (Asia) Credit Limited</span><span>UACREDIT.HK · 網站重建預覽</span></div></div></footer>
    <div class="mobile-contact" aria-label="快捷聯絡"><a href="tel:+85228868345">致電查詢 ↗</a><a href="https://wa.me/85260855201" target="_blank" rel="noopener noreferrer">WhatsApp ↗</a></div>'''

def faq(items, open_first=False):
    return ''.join(f'<details id="faq-{i+1}"'+(' open' if open_first and i==0 else '')+f'><summary>{escape(q)}</summary><p>{escape(a)}</p></details>' for i,(q,a) in enumerate(items))

FAQ = [
('買車上會與汽車翻按有甚麼分別？','買車上會係幫你買新車或者二手車；汽車翻按係用你而家部車去借。部車咩狀況、要交乜文件、批唔批，要打去問環聯先準。'),
('可以先查詢，之後才決定申請嗎？','可以。先問清流程、文件、利率、費用同還款安排，睇啱先申請。'),
('可以即時報價或批核嗎？','網上暫時報唔到價、批唔到核。打電話或者 WhatsApp 問。'),
('如何了解總還款額及相關費用？','申請前，問環聯攞實際年利率、每月供幾多、總共還幾多，仲有手續費、逾期同提早還款點計。'),
('現時可以在網站上載身份證或牌簿嗎？','唔可以。呢度無得上載文件。交文件之前，先同環聯核實正式申請渠道同個人資料收集聲明。')]

# Regenerate the optional WebP using: cwebp -q 85 -m 4 -exact dist/assets/finance-illustration-cutout.png -o dist/assets/finance-illustration-cutout.webp
# Keep the PNG as the fallback; content publishing does not require cwebp.
home = '''<div class="home-surface"><section class="home-intro wrap"><div class="hero-copy"><div class="eyebrow"><span class="brand-dot"></span> 環聯信貸 · 香港</div><h1>汽車上會・物業融資<br><span>先了解，再安排。</span></h1><p>打電話問清條件、文件同點還，先至決定。</p><div class="actions"><a class="button" href="#services">查看貸款服務 <span aria-hidden="true">↓</span></a><a class="button secondary" href="/contact/">聯絡環聯 →</a></div></div><div class="hero-art"><picture><source srcset="/assets/finance-illustration-cutout.webp" type="image/webp"><img src="/assets/finance-illustration-cutout.png" width="1536" height="1024" alt="汽車及物業貸款示意圖" fetchpriority="high"></picture></div></section></div>
<div class="wrap"><nav class="service-shortcuts" aria-label="快速查看服務"><a href="/car-loan/"><span class="shortcut-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 10 2-5h10l2 5M3 11h18v7H3zM6 18v3M18 18v3M6 14h2M16 14h2"/></svg></span><span>汽車貸款<small>買車上會・翻按</small></span><b aria-hidden="true">↗</b></a><a href="/property-loan/"><span class="shortcut-icon mint"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m3 10 9-7 9 7M5 9v12h14V9M9 21v-8h6v8"/></svg></span><span>物業貸款<small>一按・二按・轉按</small></span><b aria-hidden="true">↗</b></a><a href="/faq/"><span class="shortcut-icon peach"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h16v13H9l-5 4zM9 9a3 3 0 0 1 6 0c0 2-3 2-3 4M12 15h.01"/></svg></span><span>常見問題<small>貸款查詢與申請</small></span><b aria-hidden="true">↗</b></a><a href="/contact/"><span class="shortcut-icon silver"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h5l2 5-3 2a15 15 0 0 0 5 5l2-3 5 2v4C12 23 0 11 4 4Z"/></svg></span><span>聯絡環聯<small>電話・WhatsApp</small></span><b aria-hidden="true">↗</b></a></nav></div>
<section class="section wrap" id="services"><div class="section-head"><div><div class="eyebrow">貸款服務</div><h2>汽車及物業貸款</h2></div><a class="text-link" href="/all-pages/">查看所有資料 <span aria-hidden="true">↗</span></a></div><div class="service-grid"><article class="service-item motor-service"><div class="service-content"><span class="service-label">汽車貸款</span><h3>汽車上會<br>及汽車翻按</h3><ul class="service-points"><li>新車、二手車上會</li><li>現有車輛翻按</li><li>問車款、車齡同車價</li></ul><a class="text-link" href="/car-loan/">汽車貸款詳情 <span aria-hidden="true">↗</span></a></div><img class="service-image" src="/assets/hero.jpg" alt="汽車貸款服務" loading="lazy" width="1800" height="853"></article><article class="service-item property-service"><div class="service-content"><span class="service-label">物業貸款</span><h3>一按、二按<br>及轉按</h3><ul class="service-points"><li>一按、二按、轉按</li><li>現契貸款</li><li>問物業類型、業權同現有按揭</li></ul><a class="text-link" href="/property-loan/">物業貸款詳情 <span aria-hidden="true">↗</span></a></div><img class="service-image property-image" src="/assets/property.jpg" alt="物業貸款服務" loading="lazy" width="1920" height="480"></article></div><p class="service-note">放債人牌照號碼：1866/2025 · 忠告：借錢梗要還，咪俾錢中介</p></section>
<section class="process"><div class="wrap"><div class="section-head"><div><div class="eyebrow">貸款申請</div><h2>申請前需知</h2></div><a class="text-link" href="/contact/">向環聯查詢 ↗</a></div><ol><li><span class="step-number">01</span><div><h3>講低你想借邊樣</h3><p>打電話或者 WhatsApp，講低汽車定物業。</p></div></li><li><span class="step-number">02</span><div><h3>問清條件同費用</h3><p>問清實際年利率、總共還幾多、要交乜文件、有無其他費用。</p></div></li><li><span class="step-number">03</span><div><h3>睇清楚條款先決定</h3><p>攞到正式書面條款，睇啱先申請。</p></div></li></ol></div></section>
<section class="section wrap faq-grid"><div><div class="eyebrow">貸款查詢</div><h2>常見問題</h2><p>買車上會、翻按、報價同文件，呢度答咗。</p><a class="text-link" href="/faq/">查看所有問題 ↗</a></div><div>'''+faq(FAQ[:3])+'''</div></section>'''
pages[''] = ('汽車貸款・物業貸款｜環聯(亞洲)信貸有限公司', '環聯(亞洲)信貸的汽車貸款、買車上會、汽車翻按同物業貸款服務，聯絡方式同申請前常見問題。', home)

def intro(kicker,title,desc):
    return f'<div class="wrap"><div class="breadcrumb"><a href="/">主頁</a> / {title}</div><section class="page-intro"><div class="eyebrow">{kicker}</div><h1>{title}</h1><p>{desc}</p></section>'

pages['car-loan'] = ('汽車貸款・買車上會・汽車翻按｜環聯亞洲信貸','環聯汽車貸款：新車、二手車上會、現有車輛翻按，申請前要問清嘅條款同查詢方法。',intro('MOTOR FINANCE','汽車貸款','新車、二手車上會、汽車翻按查詢。')+'''<div class="split"><div class="prose"><img class="service-image" src="/assets/hero.jpg" alt="環聯汽車貸款" width="1800" height="853"><h2>準備買車</h2><p>新車、二手車上會，環聯都做。打去問之前，準備定車款、車齡同車價。</p><h2>已經有車，想做翻按</h2><p>翻按同買車上會用途唔同，要睇返部車同你嘅情況先評估到。先問車輛估價、要交乜文件、點還同有無其他費用。</p><h2 id="application-notes" tabindex="-1">申請前，先問清楚</h2><ul><li>可申請的車輛類型、車齡及貸款金額</li><li>實際年利率、每月供款及總還款額</li><li>手續費、逾期及提早還款安排</li><li>牌簿、住址及其他證明文件的正式遞交渠道</li></ul><p class="note">實際貸款成數、年期、利率同要交乜文件，打去問環聯先準；呢頁唔係報價。</p></div><aside class="aside"><div class="eyebrow">貸款查詢</div><h2>查詢汽車貸款</h2><p>邊樣方便用邊樣。</p><a class="button" href="/contact/?service=car">查詢汽車貸款 ↗</a><a class="button secondary" href="https://wa.me/85260855201?text=%E4%BD%A0%E5%A5%BD%EF%BC%8C%E6%88%91%E6%83%B3%E6%9F%A5%E8%A9%A2%E6%B1%BD%E8%BB%8A%E8%B2%B8%E6%AC%BE%E3%80%82" target="_blank" rel="noopener noreferrer">WhatsApp 查詢 ↗</a><p class="small" style="margin-top:20px">車會熱線<br><a class="phone" href="tel:+85228868345">2886 8345</a></p></aside></div></div>''')
pages['property-loan'] = ('物業貸款・一按二按・轉按｜環聯亞洲信貸','環聯物業貸款：一按、二按、轉按、現契貸款，申請前要確認嘅資料。',intro('PROPERTY FINANCE','物業貸款','一按、二按、轉按、現契貸款。')+'''<div class="split"><div class="prose"><img class="service-image property-image" src="/assets/property.jpg" alt="物業貸款服務" width="1920" height="480"><h2>物業貸款有邊幾種</h2><p>一按、二按、轉按、現契翻按，環聯都有。物業類型、業權、而家有無按揭，都會影響借唔借到同點借。</p><h2 id="application-notes" tabindex="-1">打去問之前，準備定呢啲</h2><ul><li>物業類型、地區及業權情況</li><li>現有按揭或其他相關貸款概況</li><li>你想借嚟做乜、點還</li></ul><h2>比較方案，睇邊幾樣？</h2><p>除咗利率，仲要問總共還幾多、估價同法律費用、提早還款點計、逾期點計。攞到正式書面條款，睇啱先申請。</p><p class="note">呢頁唔係報價；邊啲物業啱、批唔批，打去問環聯。</p></div><aside class="aside"><div class="eyebrow">PROPERTY ENQUIRY</div><h2>查詢物業貸款</h2><p>邊樣方便用邊樣。</p><a class="button" href="/contact/?service=property">查詢物業貸款 ↗</a><a class="button secondary" href="https://wa.me/85260855201?text=%E4%BD%A0%E5%A5%BD%EF%BC%8C%E6%88%91%E6%83%B3%E6%9F%A5%E8%A9%A2%E7%89%A9%E6%A5%AD%E8%B2%B8%E6%AC%BE%E3%80%82" target="_blank" rel="noopener noreferrer">WhatsApp 查詢 ↗</a></aside></div></div>''')
pages['about-us'] = ('關於環聯｜環聯(亞洲)信貸有限公司','環聯(亞洲)信貸有限公司 Universal (Asia) Credit Limited 簡介、汽車同物業貸款服務。',intro('環聯信貸','關於環聯','Universal (Asia) Credit Limited\u2002環聯(亞洲)信貸有限公司')+'''<div class="split"><div class="prose"><h2>公司簡介</h2><p>環聯(亞洲)信貸有限公司2012年成立，做私人、物業、汽車、業主私人同商業貸款。</p><h2>直接聯絡環聯</h2><p>服務詳情同現行產品條款，打去問環聯先準。地址、電話、營業時間喺聯絡頁。</p><p class="note">放債人牌照號碼：1866/2025。<a href="https://www.cr.gov.hk/en/statistics/docs/ml_licensees1.pdf" target="_blank" rel="noopener noreferrer">公司註冊處名單</a>截至2026年9月30日標示該牌照的續期申請進行中。</p></div><aside class="aside"><div class="eyebrow">地址</div><h2>紅磡</h2><p>九龍馬頭圍道39號<br>紅磡商業中心A座3樓306A室</p><a class="button secondary" href="/contact/">營業時間及聯絡方法 ↗</a></aside></div></div>''')
pages['faq'] = ('常見問題｜汽車及物業貸款查詢｜環聯亞洲信貸','汽車上會同翻按有乜分別，申請前要確認嘅文件、費用、還款安排同查詢渠道。',intro('貸款查詢','常見問題','申請前，問清服務、文件同還款安排。')+'<nav class="faq-jump" aria-label="問題列表">'+''.join(f'<a href="#faq-{i+1}">{escape(q)}</a>' for i,(q,a) in enumerate(FAQ))+'</nav><div class="split"><div>'+faq(FAQ, open_first=True)+'</div><aside class="aside"><h2>仲有問題？</h2><a class="button" href="/contact/">聯絡我們 ↗</a></aside></div></div>')
pages['contact'] = ('聯絡我們・電話・地址・營業時間｜環聯亞洲信貸','環聯亞洲信貸車會電話2886 8345、查詢及投訴電話2886 8144、WhatsApp 6085 5201，以及紅磡地址和營業時間。',intro('聯絡資料','聯絡環聯','電話、WhatsApp 或者電郵，邊樣方便用邊樣。')+'''<div class="contact-layout"><div><dl class="contact-list"><div><dt>車會查詢</dt><dd><a href="tel:+85228868345">2886 8345 ↗</a> / <a href="tel:+85228868044">2886 8044 ↗</a></dd></div><div><dt>查詢及投訴</dt><dd><a href="tel:+85228868144">2886 8144 ↗</a></dd></div><div><dt>WhatsApp</dt><dd><a href="https://wa.me/85260855201" target="_blank" rel="noopener noreferrer">6085 5201 ↗</a></dd></div><div><dt>電郵</dt><dd><a href="mailto:cs@uacredit.com.hk">cs@uacredit.com.hk ↗</a></dd></div><div><dt>地址</dt><dd>九龍馬頭圍道39號<br>紅磡商業中心A座3樓306A室<br><a href="https://www.google.com/maps/search/?api=1&amp;query=%E4%B9%9D%E9%BE%8D%E9%A6%AC%E9%A0%AD%E5%9C%8D%E9%81%9339%E8%99%9F%E7%B4%85%E7%A3%A1%E5%95%86%E6%A5%AD%E4%B8%AD%E5%BF%83A%E5%BA%A73%E6%A8%93306A%E5%AE%A4" target="_blank" rel="noopener noreferrer">在 Google 地圖查看 ↗</a></dd></div><div><dt>營業時間</dt><dd>星期一至五 09:30–18:30<br>星期六 09:30–13:00</dd></div></dl><p class="note">收到自稱環聯嘅訊息，先核實來電號碼同 WhatsApp 號碼再回覆。</p></div><div><form id="enquiry"><div class="eyebrow">查詢內容</div><h2>先寫低你想問乜</h2><p class="small">只係喺呢頁幫你寫低問題，唔會提交申請、唔會寄出，唔使填個人資料。</p><label>想問嘅服務<select name="service"><option>汽車貸款</option><option>汽車翻按</option><option>物業貸款</option></select></label><label>想問乜？<select name="topic"><option>申請流程及所需文件</option><option>利率、費用及還款安排</option><option>預約查詢及到訪安排</option></select></label><button class="button" type="submit">整理查詢內容 <span aria-hidden="true">→</span></button><noscript><p class="note">寫低問題呢個功能要開 JavaScript。就算唔開，你都可以用呢頁嘅電話、WhatsApp 同電郵聯絡環聯。</p></noscript><button class="text-link reset-enquiry" type="reset">重設選項</button><div class="output" id="enquiry-output" hidden><label for="message">已整理的查詢內容</label><textarea id="message" rows="4" readonly></textarea><div class="actions"><button class="button secondary" type="button" id="copy">複製文字</button><a class="button" id="open-enquiry" target="_blank" rel="noopener noreferrer" href="https://wa.me/85260855201">帶到 WhatsApp ↗</a></div><p class="small">只會開返對話，內容由你確認之後先發送。</p></div><div role="status" id="copy-status" aria-live="polite"></div></form></div></div></div>''')
pages['privacy'] = ('網站使用說明｜環聯網站重建預覽','環聯網站重建預覽點處理資料、外部聯絡連結，同正式申請渠道要確認嘅事項。',intro('PRIVACY & WEBSITE USE','網站使用說明','呢頁講呢個設計預覽嘅使用範圍。')+'''<div class="split"><div class="prose"><h2>呢個預覽會用到你啲乜資料？</h2><p>公開資料唔使註冊都睇到。呢個預覽無得收貸款申請、無得上載文件、無得付款。客戶中心的帳戶資料處理另見<a href="/account/privacy/">客戶中心私隱說明</a>。「整理查詢內容」只在目前頁面產生文字；不會把查詢內容送到環聯或保存至本網站伺服器，選項只在目前瀏覽器分頁暫存，方便返回繼續；可在聯絡頁按「重設選項」清除。</p><h2>App 本機收藏</h2><p>App 的公開資料隨安裝包提供，可離線閱讀。收藏只保存在這部裝置，不會建立訪客帳戶或跨裝置同步；可在「我的」清除收藏。解除安裝或清除 App 資料亦會移除收藏。</p><h2>外部聯絡服務</h2><p>撳 WhatsApp、電話或者電郵連結，會開返嗰個服務。發唔發內容由你決定；嗰啲服務點處理資料，跟返佢哋自己嘅條款。呢個預覽無第三方廣告、無分析追蹤、無嵌入式社交外掛。託管服務可能為咗登入、保安同服務運作，處理必要嘅紀錄。</p><h2>正式申請前</h2><p>交個人資料之前，先同環聯核實現行牌照、申請渠道同個人資料收集聲明。呢頁說明唔會取代環聯正式私隱政策或者貸款合約。</p></div></div></div>''')

from original_content import add_originals
source = add_originals(pages,ROOT,intro)
if APPLICATIONS_ENABLED:
    def loan_application(kind, title):
        description='填寫基本資料，環聯會聯絡你跟進申請。'
        content=intro('貸款申請',title,description)+f'''<div class="application-layout"><div>
<form class="loan-application" id="loan-application" data-service="{kind}">
<p class="application-required">* 必填</p>
<div class="application-fields"><label for="loan-name">姓名 <span aria-hidden="true">*</span><input id="loan-name" name="name" type="text" autocomplete="name" maxlength="80" required></label>
<label for="loan-phone">聯絡電話 <span aria-hidden="true">*</span><input id="loan-phone" name="phone" type="tel" inputmode="tel" autocomplete="tel" maxlength="20" aria-describedby="loan-phone-help" required><small id="loan-phone-help">請填寫香港電話號碼。</small></label>
<label for="loan-amount">希望貸款金額（港元）<span class="optional">選填</span><input id="loan-amount" name="amount" type="number" inputmode="decimal" min="0" max="100000000" step="any"></label>
<label for="loan-details">申請需要<span class="optional">選填</span><textarea id="loan-details" name="details" maxlength="1000" rows="4" aria-describedby="loan-details-help"></textarea><small id="loan-details-help">可簡述貸款需要；請勿填寫身份證號碼或銀行資料。</small></label></div>
<div class="application-privacy"><h2>個人資料</h2><p>環聯(亞洲)信貸有限公司會使用你的資料處理及跟進貸款申請。姓名及電話為必填；未提供這些資料，我們無法聯絡你跟進申請。貸款金額及申請需要為選填。資料由環聯授權人員及提供系統託管或維護的服務供應商處理。如要查閱或更正資料，請<a href="/contact/">聯絡環聯</a>。詳情請參閱<a href="/privacy-policy/">私隱政策</a>。</p>
<label class="application-consent"><input type="checkbox" name="consent" required><span>本人同意環聯使用以上資料處理及聯絡我跟進貸款申請，並已閱讀私隱政策。 <span aria-hidden="true">*</span></span></label></div>
<p id="loan-status" class="loan-status" role="status" aria-live="polite"></p><button class="button" id="loan-submit" type="submit" disabled>提交申請 <span aria-hidden="true">→</span></button>
<noscript><p class="loan-status">網上申請需要啟用 JavaScript。你亦可<a href="/contact/">聯絡環聯</a>。</p></noscript></form>
<section class="application-result" id="loan-result" hidden tabindex="-1"><h2>申請已提交</h2><p>我們已收到你的申請，會按所提供的電話聯絡你。</p><p>申請編號：<strong id="loan-reference"></strong></p><a href="/" class="button secondary">返回主頁</a></section></div>
<aside class="application-aside"><h2>需要協助？</h2><p>如有查詢，可致電與我們聯絡。</p><a href="tel:+85228868345">2886 8345 ↗</a></aside></div></div>'''
        return title+'｜環聯亞洲信貸',description,content
    pages['car-loan-application']=loan_application('car','汽車貸款申請')
    pages['property-loan-application']=loan_application('property','物業貸款申請')
    privacy_body=intro('PRIVACY & WEBSITE USE','私隱與網站使用','網站點處理你的資料。')+'''<div class="split"><div class="prose"><h2>網上申請</h2><p>提交貸款申請時，環聯會使用你提供的資料處理及跟進申請。網站不提供文件上載或付款功能。資料查閱、更正及其他詳情，請參閱<a href="/privacy-policy/">私隱政策</a>或<a href="/contact/">聯絡環聯</a>。</p><h2>查詢與客戶帳戶</h2><p>聯絡頁的「整理查詢內容」只在目前頁面產生文字，不會把內容送到環聯或保存至網站伺服器。客戶帳戶的資料處理另見<a href="/account/privacy/">客戶中心私隱說明</a>。</p><h2>App 本機收藏</h2><p>App 的公開資料隨安裝包提供，可離線閱讀。收藏只保存在這部裝置，不會建立訪客帳戶或跨裝置同步；可在「我的」清除收藏。解除安裝或清除 App 資料亦會移除收藏。</p><h2>外部聯絡服務</h2><p>點選 WhatsApp、電話或電郵連結，會開啟相應服務。你可自行決定是否發送內容；外部服務的資料處理受各自條款規管。</p></div></div></div>'''
    pages['privacy']=('私隱與網站使用｜環聯亞洲信貸','網上貸款申請同網站資料處理方式。',privacy_body)
for route,label,kind in [('car-loan','查詢汽車貸款','car'),('property-loan','查詢物業貸款','property')]:
    title,description,body=pages[route]
    jump='<a class="text-link" href="#application-notes">申請前需知 ↓</a>' if 'id="application-notes"' in body else ''
    action_href=f'/{route}-application/' if APPLICATIONS_ENABLED else f'/contact/?service={kind}#enquiry'
    action_label=('申請汽車貸款' if kind=='car' else '申請物業貸款') if APPLICATIONS_ENABLED else label
    actions=f'<div class="service-intro-actions"><a class="button" href="{action_href}">{action_label} ↗</a>{jump}</div>'
    switch='<nav class="loan-switch" aria-label="貸款服務">'+''.join(f'<a href="/{target}/"'+(' aria-current="page"' if target==route else '')+f'>{text}</a>' for target,text in [('car-loan','汽車貸款'),('property-loan','物業貸款')])+'</nav>'
    body=re.sub(r'<div class="eyebrow">[^<]*</div>',lambda match:switch,body,count=1)
    pages[route]=(title,description,body.replace('</section>','</section>'+actions,1))
settings_path = Path(os.environ.get('UACREDIT_SETTINGS',str(ROOT/'content/settings.json')))
settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
home_display=next((r.get('display',{}) for r in source['records'] if r['id']==2),{})
# Migrate only the original unedited headline, without changing stored settings or overriding CMS edits.
if not home_display and (settings.get('hero_line_1'),settings.get('hero_line_2'))==('下一程，','由你作主。'):
    settings.update({'hero_line_1':'汽車上會・汽車翻按','hero_line_2':'物業貸款'})
settings.update(home_display)
contact_settings=next((r.get('display',{}) for r in source['records'] if r['id']==110),{})
for slug,(title,description,body) in pages.items():
    path='/' + (slug+'/' if slug else '')
    schema={'@context':'https://schema.org','@type':'FinancialService','name':'環聯(亞洲)信貸有限公司','alternateName':'Universal (Asia) Credit Limited','url':ORIGIN,'logo':ORIGIN+'/assets/logo.png','telephone':'+85228868345','email':'cs@uacredit.com.hk','address':{'@type':'PostalAddress','streetAddress':'九龍馬頭圍道39號紅磡商業中心A座3樓306A室','addressRegion':'九龍','addressCountry':'HK'},'openingHours':['Mo-Fr 09:30-18:30','Sa 09:30-13:00']}
    loan_script='<script src="/assets/loan-application.js" defer></script>' if APPLICATIONS_ENABLED and slug in {'car-loan-application','property-loan-application'} else ''
    page_footer=launched(footer()).replace('網站使用說明','私隱與網站使用') if APPLICATIONS_ENABLED else launched(footer())
    faq_schema=''
    if slug=='faq':
        faq_schema='<script type="application/ld+json">'+json.dumps({'@context':'https://schema.org','@type':'FAQPage','mainEntity':[{'@type':'Question','name':q,'acceptedAnswer':{'@type':'Answer','text':a}} for q,a in FAQ]},ensure_ascii=False)+'</script>'
    hero_preload='<link rel="preload" as="image" href="/assets/finance-illustration-cutout.webp">' if slug=='' else ''
    html=f'''<!doctype html><html lang="zh-HK"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)}</title><meta name="description" content="{escape(description)}"><meta name="robots" content="{ROBOTS}"><link rel="canonical" href="{ORIGIN}{path}"><meta property="og:title" content="{escape(title)}"><meta property="og:description" content="{escape(description)}"><meta property="og:type" content="website"><meta property="og:locale" content="zh_HK"><meta property="og:url" content="{ORIGIN}{path}"><meta property="og:image" content="{ORIGIN}/assets/hero.jpg"><link rel="icon" href="/assets/favicon.png"><link rel="stylesheet" href="/assets/site.css">{hero_preload}<script type="application/ld+json">{json.dumps(schema,ensure_ascii=False)}</script>{faq_schema}<script src="/assets/site.js" defer></script>{loan_script}</head><body>{launched(header(slug))}<main id="main">{body}</main>{page_footer}</body></html>'''
    replacements = {'汽車上會・物業融資':settings.get('hero_line_1','汽車上會・汽車翻按'),'先了解，再安排。':settings.get('hero_line_2','物業貸款')}
    for old,new in replacements.items():html=html.replace(old,escape(new))
    contact_defaults={'phone_main':'2886 8345','phone_secondary':'2886 8044','phone_complaints':'2886 8144','whatsapp':'6085 5201','email':'cs@uacredit.com.hk','address_line_1':'九龍馬頭圍道39號','address_line_2':'紅磡商業中心A座3樓306A室'}
    contact_replacements={}
    for key,old in contact_defaults.items():
        new=contact_settings.get(key,old)
        contact_replacements[old]=escape(new)
        if key.startswith('phone_') or key=='whatsapp':contact_replacements[old.replace(' ','')]=new.replace(' ','')
    html=re.sub('|'.join(re.escape(k) for k in sorted(contact_replacements,key=len,reverse=True)),lambda m:contact_replacements[m[0]],html)
    dest=DIST/slug/'index.html' if slug else DIST/'index.html'
    dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(html)
if INDEXABLE:
    (DIST/'robots.txt').write_text(f'User-agent: *\nDisallow: /admin/\nSitemap: {ORIGIN}/sitemap.xml\n')
    urls=''.join(f'<url><loc>{ORIGIN}/{slug + "/" if slug else ""}</loc></url>' for slug in sorted(pages) if not slug.startswith(('account','admin')))
    (DIST/'sitemap.xml').write_text(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
else:
    (DIST/'robots.txt').write_text('User-agent: *\nDisallow: /\n')
    (DIST/'sitemap.xml').unlink(missing_ok=True)
notfound_footer=launched(footer()).replace('網站使用說明','私隱與網站使用') if APPLICATIONS_ENABLED else launched(footer())
notfound_html=f'''<!doctype html><html lang="zh-HK"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex"><title>找不到頁面｜環聯亞洲信貸</title><link rel="icon" href="/assets/favicon.png"><link rel="stylesheet" href="/assets/site.css"><script src="/assets/site.js" defer></script></head><body>{launched(header(''))}<main class="wrap error-page"><p>404 / UACREDIT</p><h1>找不到這個頁面。</h1><p>網址可能已更新。你可以返回首頁，或直接查看聯絡方式。</p><div class="actions"><a class="button" href="/">返回首頁</a><a href="/contact/">聯絡我們 →</a></div></main>{notfound_footer}</body></html>'''
(DIST/'404.html').write_text(notfound_html)
print(f'Built {len(pages)} static pages. '+('Public indexing enabled.' if INDEXABLE else 'Preview indexing disabled.'))
