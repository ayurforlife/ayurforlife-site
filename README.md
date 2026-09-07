# ayurforlife.eu — Домът на Аюрведа

Static site for **ayurforlife.eu**, rebuilt from the WordPress blog
`ayurvedaforlifeinfo.wordpress.com` (3 pages, 22 posts, all uploads localised).

## Layout

| Path | What |
|------|------|
| `index.html` | Front page (the "За нас" content) |
| `blog/` | Article index + one directory per article |
| `category/` | One page per category |
| `our-mission/`, `contacts/` | Standalone pages |
| `assets/uploads/` | Images pulled from WordPress, resized to max 1600px |
| `assets/css/site.css` | All styles |
| `_src/` | WordPress API dumps + `build.py`, the generator |
| `YYYY/MM/DD/…` | Redirect stubs at the old WordPress permalinks |

## Rebuilding

```bash
python3 _src/build.py     # regenerates every HTML page from _src/*.json
```

To pull fresh content from WordPress first:

```bash
B="https://public-api.wordpress.com/wp/v2/sites/ayurvedaforlifeinfo.wordpress.com"
curl -s "$B/pages?per_page=100&context=view" -o _src/pages_full.json
curl -s "$B/posts?per_page=100&context=view" -o _src/posts_full.json
curl -s "$B/categories?per_page=100"         -o _src/cats.json
```

## Local preview

```bash
python3 -m http.server 8899   # then open http://localhost:8899/
```

## Deployment

GitHub Pages from `main` / root. `CNAME` holds the custom domain; DNS lives in
Cloudflare (apex A records → GitHub Pages, proxied; SSL/TLS mode must be **Full**).
