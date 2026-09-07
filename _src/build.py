#!/usr/bin/env python3
"""Rebuild the WordPress site ayurvedaforlifeinfo.wordpress.com as a static site for ayurforlife.eu."""
import json, re, html, os, shutil, unicodedata
from html.parser import HTMLParser
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC  = ROOT / "_src"
OUT  = ROOT
SITE = "https://ayurforlife.eu"
TITLE = "Домът на Аюрведа"
TAGLINE = "Класическа Аюрведа в с. Малоградец"
WP = "ayurvedaforlifeinfo.wordpress.com"
DATE_INDEX = {}   # "/YYYY/MM/DD/" -> new url, for old permalinks whose slug later changed
LEGACY = set()    # legacy WP paths we resolved, to emit redirect stubs for

BG_MONTHS = ["януари","февруари","март","април","май","юни","юли","август","септември","октомври","ноември","декември"]
TR = {'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ж':'zh','з':'z','и':'i','й':'y','к':'k','л':'l','м':'m',
      'н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh',
      'щ':'sht','ъ':'a','ь':'y','ю':'yu','я':'ya'}

def translit(s):
    s = s.lower()
    out = ''.join(TR.get(ch, ch) for ch in s)
    out = unicodedata.normalize('NFKD', out).encode('ascii', 'ignore').decode()
    out = re.sub(r'[^a-z0-9]+', '-', out).strip('-')
    out = re.sub(r'-{2,}', '-', out)
    if len(out) > 60:                      # cut on a word boundary, not mid-word
        out = out[:60].rsplit('-', 1)[0]
    return out.strip('-') or 'post'

def slugify(raw_slug, title):
    s = html.unescape(raw_slug or '')
    if '%' in s:
        try: s = bytes(s, 'utf-8').decode('utf-8')
        except Exception: pass
        from urllib.parse import unquote
        s = unquote(s)
    s = translit(s)
    if not s or s.isdigit() or len(s) < 3:
        s = translit(re.sub(r'<[^>]+>', '', html.unescape(title)))
    return s

def strip_tags(h):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h))).strip()

def esc(s):
    return html.escape(s, quote=True)

def bg_date(iso):
    d = datetime.fromisoformat(iso)
    return f"{d.day} {BG_MONTHS[d.month-1]} {d.year}"

# ---------------------------------------------------------------- HTML cleaner
DROP_TREE = {'script', 'style', 'ins', 'form', 'noscript', 'svg', 'select', 'button'}
DROP_PAT = re.compile(r'sharedaddy|jp-relatedposts|jp-post-flair|pd-embed|polldaddy|PDS_Poll|wpcnt|wpa|sd-like|'
                      r'sd-sharing|geo-post|robots-nocontent|jetpack|likes-widget|crayon', re.I)
VOID = {'br', 'img', 'hr', 'wbr', 'source'}
KEEP_ATTR = {
    'a': ('href', 'title'), 'img': ('src', 'alt'), 'iframe': ('src', 'title', 'allow', 'allowfullscreen'),
    'td': ('colspan', 'rowspan'), 'th': ('colspan', 'rowspan'),
}
BLOCK_OK = {'p','br','strong','b','em','i','u','s','ul','ol','li','blockquote','h1','h2','h3','h4','h5','h6',
            'a','img','figure','figcaption','table','thead','tbody','tfoot','tr','td','th','hr','span','div',
            'iframe','sub','sup','pre','code','dl','dt','dd'}

class Cleaner(HTMLParser):
    def __init__(self, linkmap, uploads):
        super().__init__(convert_charrefs=False)
        self.o = []
        self.skip = 0
        self.skip_tag = None
        self.depth = 0
        self.linkmap = linkmap
        self.uploads = uploads
        self.images = []
        self.drop_a = []          # stack: True when <a> was unwrapped

    # -- helpers
    def local_img(self, url):
        u = html.unescape(url).split('?')[0]
        m = re.search(r'/wp-content/uploads/(.+)$', u)
        if m:
            rel = m.group(1)
            if (OUT / 'assets' / 'uploads' / rel).exists():
                return '/assets/uploads/' + rel
        return u if u.startswith('http') else None

    def map_link(self, url):
        u = html.unescape(url)
        if WP in u:
            path = re.sub(r'^https?://[^/]+', '', u)
            if path in self.linkmap:
                return self.linkmap[path]
            m = re.match(r'^(/\d{4}/\d{2}/\d{2}/)', path)
            if m and m.group(1) in DATE_INDEX:
                LEGACY.add(path)
                return DATE_INDEX[m.group(1)]
            img = self.local_img(u)
            if img and img.startswith('/assets'):
                return img
        return u

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.skip:
            if tag == self.skip_tag and tag not in VOID:
                self.depth += 1
            return
        blob = ' '.join(filter(None, (a.get('class'), a.get('id'))))
        if tag in DROP_TREE or (blob and DROP_PAT.search(blob)):
            if tag in VOID: return
            self.skip, self.skip_tag, self.depth = 1, tag, 1
            return
        if tag == 'iframe':
            src = a.get('src', '')
            if 'youtube' not in src and 'youtu.be' not in src and 'vimeo' not in src:
                self.skip, self.skip_tag, self.depth = 1, tag, 1
                return
            self.o.append(f'<div class="embed"><iframe src="{esc(html.unescape(src))}" title="video" '
                          f'loading="lazy" allowfullscreen></iframe></div>')
            self.skip, self.skip_tag, self.depth = 1, tag, 1
            return
        if tag == 'img':
            src = self.local_img(a.get('src', ''))
            if not src: return
            alt = html.unescape(a.get('alt', '') or '')
            self.images.append(src)
            self.o.append(f'<img src="{esc(src)}" alt="{esc(alt)}" loading="lazy">')
            return
        if tag == 'a':
            href = self.map_link(a.get('href', ''))
            if not href or href.startswith('/assets/uploads') or f'{WP}/wp-content' in href:
                self.drop_a.append(True)      # attachment link -> unwrap
                return
            self.drop_a.append(False)
            ext = ' target="_blank" rel="noopener"' if href.startswith('http') and 'ayurforlife.eu' not in href else ''
            self.o.append(f'<a href="{esc(href)}"{ext}>')
            return
        if tag not in BLOCK_OK:
            return
        keep = KEEP_ATTR.get(tag, ())
        at = ''.join(f' {k}="{esc(html.unescape(a[k]))}"' for k in keep if a.get(k))
        cls = ''
        if tag == 'div':
            tag, cls = ('figure', ' class="wp-figure"') if 'wp-caption' in (a.get('class') or '') else ('div', '')
            if tag == 'div': return          # plain wrapper divs are noise
        self.o.append(f'<{tag}{cls}{at}>')

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip_tag:
                self.depth -= 1
                if self.depth <= 0:
                    self.skip, self.skip_tag = 0, None
            return
        if tag in VOID or tag in DROP_TREE or tag == 'iframe':
            return
        if tag == 'a':
            if self.drop_a and self.drop_a.pop():
                return
            self.o.append('</a>')
            return
        if tag not in BLOCK_OK:
            return
        if tag == 'div':
            return
        self.o.append(f'</{tag}>')

    def handle_data(self, d):
        if not self.skip:
            self.o.append(d)

    def handle_entityref(self, n):
        if not self.skip: self.o.append(f'&{n};')

    def handle_charref(self, n):
        if not self.skip: self.o.append(f'&#{n};')

def clean(body, linkmap, uploads):
    c = Cleaner(linkmap, uploads)
    c.feed(body)
    c.close()
    out = ''.join(c.o)
    out = re.sub(r'<p>(\s|&nbsp;|<br\s*/?>)*</p>', '', out)
    out = re.sub(r'(?:<br\s*/?>\s*){3,}', '<br><br>', out)
    out = re.sub(r'\[/?(?:caption|gallery|embed)[^\]]*\]', '', out)
    out = re.sub(r'\n{3,}', '\n\n', out)
    return out.strip(), c.images

# ---------------------------------------------------------------- templates
CSS_HREF = '/assets/css/site.css'

def nav(active=''):
    items = [('/', 'За нас', 'home'), ('/blog/', 'Статии', 'blog'),
             ('/our-mission/', 'Нашата цел', 'mission'), ('/contacts/', 'Контакти', 'contacts')]
    return ''.join(
        f'<a href="{u}"{" class=\"on\"" if k == active else ""}>{t}</a>' for u, t, k in items)

def shell(inner, *, title, desc, canon, active='', og_img=None, extra_head=''):
    og = og_img or '/assets/uploads/2014/07/1432.jpg'
    return f"""<!doctype html>
<html lang="bg">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{SITE}{canon}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{TITLE}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{SITE}{canon}">
<meta property="og:image" content="{SITE}{og}">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,500;0,600;1,400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{CSS_HREF}">
{extra_head}
</head>
<body>
<a class="skip" href="#main">Към съдържанието</a>
<header class="site">
  <div class="wrap bar">
    <a class="brand" href="/"><img src="/assets/uploads/2011/07/logo.png" alt="{TITLE}" width="354" height="120"><span class="brand-sub">с. Малоградец</span></a>
    <input type="checkbox" id="navtoggle" hidden>
    <label for="navtoggle" class="burger" aria-label="Меню"><span></span><span></span><span></span></label>
    <nav>{nav(active)}</nav>
  </div>
</header>
<main id="main">
{inner}
</main>
<footer class="site">
  <div class="wrap foot">
    <div>
      <p class="ft">{TITLE}</p>
      <p>с. Малоградец, общ. Антоново<br>в полите на Стара планина</p>
    </div>
    <div>
      <p class="ft">Контакти</p>
      <p>Ивалин: <a href="tel:+359877717153">0877 717153</a><br>
      <a href="mailto:ayurforlife@gmail.com">ayurforlife@gmail.com</a></p>
    </div>
    <div>
      <p class="ft">Раздели</p>
      <p><a href="/">За нас</a><br><a href="/blog/">Статии</a><br><a href="/our-mission/">Нашата цел</a><br><a href="/contacts/">Контакти</a></p>
    </div>
  </div>
  <div class="wrap copy"><p>© {datetime.now().year} {TITLE}. Всички права запазени.</p></div>
</footer>
</body>
</html>"""

def card(p):
    img = p['card_img']
    thumb = f'<img src="{esc(img)}" alt="" loading="lazy">' if img else '<span class="ph">ॐ</span>'
    return f"""<article class="card">
  <a class="card-img" href="{p['url']}">{thumb}</a>
  <div class="card-body">
    <p class="meta">{bg_date(p['date'])}</p>
    <h3><a href="{p['url']}">{p['title']}</a></h3>
    <p class="ex">{esc(p['excerpt'])}</p>
  </div>
</article>"""

def write(relpath, content):
    p = OUT / relpath.lstrip('/')
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding='utf-8')
    return p

def redirect_stub(path, target):
    if not path.strip('/'): return
    write(path.strip('/') + '/index.html', f"""<!doctype html><html lang="bg"><head><meta charset="utf-8">
<title>Преместено</title><link rel="canonical" href="{SITE}{target}">
<meta http-equiv="refresh" content="0; url={target}">
<meta name="robots" content="noindex"></head>
<body><p>Страницата е преместена. <a href="{target}">Продължете тук</a>.</p>
<script>location.replace("{target}");</script></body></html>""")

# ---------------------------------------------------------------- load
pages = json.loads((SRC / 'pages_full.json').read_text())
posts = json.loads((SRC / 'posts_full.json').read_text())
cats  = {c['id']: c for c in json.loads((SRC / 'cats.json').read_text())}
posts = [p for p in posts if p.get('status', 'publish') == 'publish']
posts.sort(key=lambda p: p['date'], reverse=True)

uploads = {str(p.relative_to(OUT / 'assets' / 'uploads')) for p in (OUT / 'assets' / 'uploads').rglob('*') if p.is_file()}

# slugs + link map (original WP path -> new path)
linkmap, seen = {}, set()
for p in posts:
    s = slugify(p['slug'], p['title']['rendered'])
    while s in seen:
        s += '-2'
    seen.add(s)
    p['_slug'] = s
    p['_url'] = f'/blog/{s}/'
    from urllib.parse import urlparse, unquote
    linkmap[urlparse(p['link']).path] = p['_url']
    d = re.match(r'^(/\d{4}/\d{2}/\d{2}/)', urlparse(p['link']).path)
    if d:
        DATE_INDEX.setdefault(d.group(1), p['_url'])

PAGE_URLS = {1: '/', 92: '/our-mission/', 568: '/contacts/'}
for pg in pages:
    from urllib.parse import urlparse
    linkmap[urlparse(pg['link']).path] = PAGE_URLS.get(pg['id'], '/')
linkmap['/'] = '/'

cat_slug = {}
for cid, c in cats.items():
    from urllib.parse import unquote
    cat_slug[cid] = translit(unquote(c['slug'])) or f'cat-{cid}'

# ---------------------------------------------------------------- transform
for p in posts:
    body, imgs = clean(p['content']['rendered'], linkmap, uploads)
    p['_html'] = body
    p['_imgs'] = imgs
    p['title_t'] = strip_tags(p['title']['rendered'])
    ex = strip_tags(p['excerpt']['rendered'])
    ex = re.sub(r'\s*Continue reading.*$', '', ex, flags=re.I).replace('…', '').strip()
    # WP excerpts are sometimes an SEO keyword dump - fall back to the article text
    if len(ex) < 40 or (ex.count(',') >= 3 and ex.count('.') <= 1):
        ex = strip_tags(body)
    p['_excerpt'] = (ex[:180].rsplit(' ', 1)[0] + '…') if len(ex) > 180 else ex
    p['_cats'] = [c for c in p['categories'] if c in cats and cats[c]['slug'] != 'uncategorized']

def pv(p):
    return {'url': p['_url'], 'title': p['title_t'], 'date': p['date'],
            'excerpt': p['_excerpt'], 'card_img': p['_imgs'][0] if p['_imgs'] else None}

page_by_id = {pg['id']: pg for pg in pages}
about_html, about_imgs = clean(page_by_id[1]['content']['rendered'], linkmap, uploads)
mission_html, _ = clean(page_by_id[92]['content']['rendered'], linkmap, uploads)
contacts_html, _ = clean(page_by_id[568]['content']['rendered'], linkmap, uploads)

# pull the portrait strip out of the About body so the text reads clean
about_body = re.sub(r'<img[^>]*>', '', about_html)
about_body = re.sub(r'<p>\s*</p>', '', about_body)
portraits = [i for i in about_imgs if 'logo-documents' not in i]

# ---------------------------------------------------------------- front page
latest = posts[:6]
front = f"""
<section class="hero">
  <div class="hero-img"><img src="/assets/uploads/2014/07/1432.jpg" alt="Аюрведична терапия в Домът на Аюрведа" fetchpriority="high"></div>
  <div class="hero-in wrap">
    <p class="kicker">Класическа Аюрведа · от 15 години</p>
    <h1>Домът на Аюрведа</h1>
    <p class="lede">Място за прочистване, обучение и връщане към баланс — в китното селце Малоградец, в полите на Стара планина.</p>
    <p class="cta"><a class="btn" href="/contacts/">Свържете се с нас</a><a class="btn ghost" href="/blog/">Прочетете статиите</a></p>
  </div>
</section>

<section class="wrap band">
  <div class="two">
    <div class="prose">
      <h2>За нас</h2>
      {about_body}
    </div>
    <aside class="portraits">
      {''.join(f'<img src="{esc(i)}" alt="" loading="lazy">' for i in portraits[:4])}
    </aside>
  </div>
</section>

<section class="quote-band">
  <div class="wrap">
    <blockquote>Златната среда е основен принцип в Аюрведа — затова при нас всичко е плавно, без екстремни практики, нежно и естествено.</blockquote>
  </div>
</section>

<section class="wrap band">
  <div class="sec-head">
    <h2>Последни статии</h2>
    <a class="more" href="/blog/">Всички статии →</a>
  </div>
  <div class="cards">{''.join(card(pv(p)) for p in latest)}</div>
</section>

<section class="contact-band" id="contact">
  <div class="wrap two">
    <div>
      <h2>Елате при нас</h2>
      <p>Домът на Аюрведа се намира в село Малоградец, на 7 км южно от гр. Антоново и на 10 минути от главния път София – Варна.</p>
      <p class="big"><a href="tel:+359877717153">0877 717153</a><br><a href="mailto:ayurforlife@gmail.com">ayurforlife@gmail.com</a></p>
      <p><a class="btn" href="https://www.google.com/maps?q=43.113678,26.175034" target="_blank" rel="noopener">Вижте на картата</a></p>
    </div>
    <div class="prose small">
      <h3>Нашата цел</h3>
      {mission_html}
    </div>
  </div>
</section>
"""
write('index.html', shell(front, title=f'{TITLE} — класическа Аюрведа в с. Малоградец',
      desc='Домът на Аюрведа — класическа Аюрведа, прочиствания, обучения и консултации в с. Малоградец, в полите на Стара планина.',
      canon='/', active='home'))

# ---------------------------------------------------------------- blog index
by_year = {}
for p in posts:
    by_year.setdefault(p['date'][:4], []).append(p)
chips = ''.join(f'<a class="chip" href="/category/{cat_slug[c]}/">{esc(cats[c]["name"])}</a>'
                for c in sorted({c for p in posts for c in p['_cats']},
                                key=lambda c: -cats[c]['count']))
blog = f"""
<section class="wrap band">
  <p class="crumbs"><a href="/">Начало</a> / Статии</p>
  <h1 class="page-h1">Статии</h1>
  <p class="lede narrow">Практическа Аюрведа на разбираем български език — {len(posts)} статии от практиката ни.</p>
  <div class="chips">{chips}</div>
  <div class="cards">{''.join(card(pv(p)) for p in posts)}</div>
</section>"""
write('blog/index.html', shell(blog, title=f'Статии — {TITLE}',
      desc='Статии за класическа Аюрведа: хранене, прочиствания, начин на живот, бременност и отглеждане на деца.',
      canon='/blog/', active='blog'))

# ---------------------------------------------------------------- posts
for i, p in enumerate(posts):
    prev_p = posts[i+1] if i+1 < len(posts) else None
    next_p = posts[i-1] if i > 0 else None
    tags = ''.join(f'<a class="chip" href="/category/{cat_slug[c]}/">{esc(cats[c]["name"])}</a>' for c in p['_cats'])
    nb = []
    if next_p: nb.append(f'<a class="np next" href="{next_p["_url"]}"><span>По-нова статия</span>{esc(next_p["title_t"])}</a>')
    if prev_p: nb.append(f'<a class="np prev" href="{prev_p["_url"]}"><span>По-стара статия</span>{esc(prev_p["title_t"])}</a>')
    ld = json.dumps({"@context":"https://schema.org","@type":"BlogPosting","headline":p['title_t'],
                     "datePublished":p['date'],"dateModified":p.get('modified',p['date']),
                     "author":{"@type":"Organization","name":TITLE},
                     "publisher":{"@type":"Organization","name":TITLE},
                     "mainEntityOfPage":SITE+p['_url'],
                     "image":(SITE+p['_imgs'][0]) if p['_imgs'] else None}, ensure_ascii=False)
    art = f"""
<article class="wrap article">
  <p class="crumbs"><a href="/">Начало</a> / <a href="/blog/">Статии</a></p>
  <h1>{esc(p['title_t'])}</h1>
  <p class="meta">{bg_date(p['date'])}</p>
  <div class="chips">{tags}</div>
  <div class="prose">{p['_html']}</div>
  <nav class="npnav">{''.join(nb)}</nav>
</article>
<section class="wrap band">
  <div class="sec-head"><h2>Още статии</h2><a class="more" href="/blog/">Всички →</a></div>
  <div class="cards">{''.join(card(pv(x)) for x in posts if x is not p)}</div>
</section>""" if False else f"""
<article class="wrap article">
  <p class="crumbs"><a href="/">Начало</a> / <a href="/blog/">Статии</a></p>
  <h1>{esc(p['title_t'])}</h1>
  <p class="meta">{bg_date(p['date'])}</p>
  <div class="chips">{tags}</div>
  <div class="prose">{p['_html']}</div>
  <nav class="npnav">{''.join(nb)}</nav>
</article>"""
    write(p['_url'].strip('/') + '/index.html',
          shell(art, title=f"{p['title_t']} — {TITLE}", desc=p['_excerpt'], canon=p['_url'], active='blog',
                og_img=p['_imgs'][0] if p['_imgs'] else None,
                extra_head=f'<script type="application/ld+json">{ld}</script>'))
    # keep the old WordPress permalink working if the domain is ever pointed here
    from urllib.parse import urlparse
    old = urlparse(p['link']).path
    if old.strip('/') and old != p['_url']:
        redirect_stub(old, p['_url'])

for path in sorted(LEGACY):
    if path.strip('/') and not (OUT / path.strip('/') / 'index.html').exists():
        redirect_stub(path, DATE_INDEX[re.match(r'^(/\d{4}/\d{2}/\d{2}/)', path).group(1)])

# ---------------------------------------------------------------- categories
for cid in sorted({c for p in posts for c in p['_cats']}):
    cp = [p for p in posts if cid in p['_cats']]
    name = cats[cid]['name']
    body = f"""
<section class="wrap band">
  <p class="crumbs"><a href="/">Начало</a> / <a href="/blog/">Статии</a> / {esc(name)}</p>
  <h1 class="page-h1">{esc(name)}</h1>
  <p class="lede narrow">{len(cp)} статии в тази категория.</p>
  <div class="cards">{''.join(card(pv(p)) for p in cp)}</div>
</section>"""
    write(f'category/{cat_slug[cid]}/index.html',
          shell(body, title=f'{name} — {TITLE}', desc=f'Статии в категория {name}.',
                canon=f'/category/{cat_slug[cid]}/', active='blog'))

# ---------------------------------------------------------------- pages
mission = f"""
<section class="wrap band narrow-page">
  <p class="crumbs"><a href="/">Начало</a> / Нашата цел</p>
  <h1 class="page-h1">Нашата цел</h1>
  <div class="prose">{mission_html}</div>
</section>"""
write('our-mission/index.html', shell(mission, title=f'Нашата цел — {TITLE}',
      desc='Защо създадохме този сайт и как да ползвате информацията в него.', canon='/our-mission/', active='mission'))

contacts = f"""
<section class="wrap band narrow-page">
  <p class="crumbs"><a href="/">Начало</a> / Контакти</p>
  <h1 class="page-h1">Контакти</h1>
  <div class="contact-grid">
    <div class="prose">
      <p><strong>Домът на Аюрведа</strong><br>с. Малоградец, общ. Антоново<br>в полите на Стара планина</p>
      <p>Телефон за връзка<br><span class="big"><a href="tel:+359877717153">0877 717153</a></span> — Ивалин</p>
      <p>Email<br><span class="big"><a href="mailto:ayurforlife@gmail.com">ayurforlife@gmail.com</a></span></p>
      <p><a class="btn" href="https://www.google.com/maps?q=43.113678,26.175034" target="_blank" rel="noopener">Вижте на картата</a></p>
    </div>
    <div class="prose small">
      <h2>Как да стигнете</h2>
      <p>На 7 км южно от гр. Антоново и само на 10 минути от главния път София – Варна.</p>
      <p>София – Малоградец: 279 км, около 4 часа с кола.<br>Варна – Малоградец: 171 км, около 2 часа с кола.</p>
      <p>Има автобусен транспорт от София и Варна до Антоново с Етап/Адрес и Юнион Ивкони.</p>
    </div>
  </div>
</section>"""
write('contacts/index.html', shell(contacts, title=f'Контакти — {TITLE}',
      desc='Телефон, email и как да стигнете до Домът на Аюрведа в с. Малоградец.', canon='/contacts/', active='contacts'))
from urllib.parse import urlparse
redirect_stub(urlparse(page_by_id[568]['link']).path, '/contacts/')

# ---------------------------------------------------------------- 404
write('404.html', shell("""
<section class="wrap band narrow-page center">
  <h1 class="page-h1">Страницата не е намерена</h1>
  <p class="lede">Възможно е връзката да е стара или сгрешена.</p>
  <p class="cta"><a class="btn" href="/">Към началната страница</a><a class="btn ghost" href="/blog/">Всички статии</a></p>
</section>""", title=f'Страницата не е намерена — {TITLE}', desc='404', canon='/404.html'))

# ---------------------------------------------------------------- sitemap / robots / CNAME
urls = ['/', '/blog/', '/our-mission/', '/contacts/'] + [p['_url'] for p in posts] + \
       [f'/category/{cat_slug[c]}/' for c in sorted({c for p in posts for c in p['_cats']})]
lastmod = {p['_url']: p.get('modified', p['date'])[:10] for p in posts}
sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
for u in urls:
    sm.append(f'  <url><loc>{SITE}{u}</loc>' + (f'<lastmod>{lastmod[u]}</lastmod>' if u in lastmod else '') + '</url>')
sm.append('</urlset>')
write('sitemap.xml', '\n'.join(sm))
write('robots.txt', f'User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n')
write('CNAME', 'ayurforlife.eu\n')
write('.nojekyll', '')

print(f'pages=4  posts={len(posts)}  categories={len({c for p in posts for c in p["_cats"]})}  images={len(uploads)}')
