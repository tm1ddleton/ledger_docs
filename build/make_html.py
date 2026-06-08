import re, markdown, datetime, html, pathlib

ROOT = pathlib.Path('.')
ORDER = [
    ('CLAUDE.md',                              'Project Overview & Definitions'),
    ('docs/invariants.md',                     None),
    ('docs/state.md',                          None),
    ('docs/events.md',                         None),
    ('docs/implementation.md',                 None),
    ('docs/smart_contracts/equities.md',       None),
    ('docs/smart_contracts/futures.md',        None),
    ('docs/smart_contracts/funding.md',        None),
    ('docs/smart_contracts/equity_options.md', None),
    ('docs/smart_contracts/structured_products.md', None),
    ('docs/smart_contracts/cash_payments.md',  None),
    ('docs/smart_contracts/bonds_wip.md',      None),
    ('docs/smart_contracts/fx_wip.md',         None),
    ('docs/smart_contracts/irs_wip.md',        None),
    ('docs/smart_contracts/qis_wip.md',        None),
    ('docs/smart_contracts/stock_borrow_loan_wip.md', None),
]
def base(p): return pathlib.Path(p).stem            # 'state', 'equity_options', 'CLAUDE'

def ghslug(text):
    t = text.strip().lower()
    t = re.sub(r'[^a-z0-9 \-]', '', t)              # drop punctuation incl backticks, periods, em-dash
    t = t.replace(' ', '-')
    return t

curfile = {'v': ''}
def slugify(value, sep):
    return f"{curfile['v']}--{ghslug(value)}"

mdlink = re.compile(r'\]\(([^)]+?)\.md(#[^)]*)?\)')
def rewrite_links(text, thisfile):
    # 1) bare same-file anchors  ](#foo)  ->  ](#thisfile--foo)  (FIRST, on original)
    text = re.sub(r'\]\(#([a-z0-9\-]+)\)',
                  lambda m: f"](#{thisfile}--{m.group(1)})", text)
    # 2) cross/relative .md links -> in-page anchors
    def repl(m):
        target = base(m.group(1))
        anchor = m.group(2) or ''
        if anchor:
            return f"](#{target}--{anchor[1:]})"
        return f"](#{target})"
    text = mdlink.sub(repl, text)
    return text

chapters, toc = [], []
for path, title in ORDER:
    f = base(path); curfile['v'] = f
    raw = (ROOT/path).read_text(encoding='utf-8')
    raw = rewrite_links(raw, f)
    md = markdown.Markdown(extensions=['tables','fenced_code','toc','attr_list','sane_lists'],
                           extension_configs={'toc':{'slugify': slugify}})
    body = md.convert(raw)
    toks = md.toc_tokens
    ctitle = title or (toks[0]['name'] if toks else f)
    chapters.append((f, ctitle, body))
    # global TOC: chapter + its level-2 headings
    subs = []
    for t in toks:
        if t['level'] == 1:
            subs += t['children']
        elif t['level'] == 2:
            subs.append(t)
    toc.append((f, ctitle, subs))

CSS = """
:root{--fg:#1b1b1f;--muted:#5b5b66;--accent:#0b66c3;--line:#e2e2e8;--code:#f5f5f7;}
*{box-sizing:border-box}
body{font:17px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--fg);margin:0;background:#fff;-webkit-text-size-adjust:100%}
.wrap{max-width:46rem;margin:0 auto;padding:2rem 1.1rem 5rem}
h1,h2,h3,h4{line-height:1.25;font-weight:680;margin:1.8em 0 .6em}
h1{font-size:1.7rem;border-bottom:2px solid var(--line);padding-bottom:.3em}
h2{font-size:1.32rem;margin-top:1.9em}
h3{font-size:1.1rem}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.86em;background:var(--code);padding:.12em .35em;border-radius:4px}
pre{background:var(--code);padding:.9rem 1rem;border-radius:8px;overflow-x:auto;font-size:.82rem;line-height:1.45}
pre code{background:none;padding:0}
blockquote{margin:1em 0;padding:.2em 1em;border-left:3px solid var(--line);color:var(--muted)}
.tablewrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:1.1em 0}
table{border-collapse:collapse;font-size:.82rem;min-width:100%}
th,td{border:1px solid var(--line);padding:.4em .6em;text-align:left;vertical-align:top}
th{background:#fafafc;font-weight:660}
tr:nth-child(even) td{background:#fcfcfd}
hr{border:none;border-top:1px solid var(--line);margin:2.2em 0}
.chapter{padding-top:.5em}
.chapter+.chapter{border-top:1px solid var(--line);margin-top:2.5em}
.title{text-align:center;padding:3rem 0 1rem;border-bottom:2px solid var(--line);margin-bottom:1.5rem}
.title h1{border:none;font-size:2.1rem}
.title .sub{color:var(--muted)}
nav.toc{background:#fafafc;border:1px solid var(--line);border-radius:10px;padding:1rem 1.3rem;margin:1.5rem 0}
nav.toc ol{margin:.3em 0;padding-left:1.2em}
nav.toc>ol{padding-left:1.1em}
nav.toc li{margin:.18em 0}
nav.toc .ch>a{font-weight:660}
.backtop{display:block;margin-top:1.2em;font-size:.8rem;color:var(--muted)}
@media print{.chapter{page-break-before:always}a{color:inherit}}
@media (max-width:540px){body{font-size:16px}.wrap{padding:1.2rem .7rem 4rem}}
"""

def toc_html():
    out=['<nav class="toc"><strong>Contents</strong><ol>']
    for f,ct,subs in toc:
        out.append(f'<li class="ch"><a href="#{f}">{html.escape(ct)}</a>')
        if subs:
            out.append('<ol>')
            for s in subs:
                out.append(f'<li><a href="#{s["id"]}">{html.escape(s["name"])}</a></li>')
            out.append('</ol>')
        out.append('</li>')
    out.append('</ol></nav>')
    return ''.join(out)

def wrap_tables(b):  # make tables horizontally scrollable on iPad
    return b.replace('<table>', '<div class="tablewrap"><table>').replace('</table>','</table></div>')

parts=[f'<!doctype html><html lang="en"><head><meta charset="utf-8">',
       '<meta name="viewport" content="width=device-width,initial-scale=1">',
       '<title>Ledger Docs</title><style>',CSS,'</style></head><body><div class="wrap">',
       '<div class="title" id="top"><h1>Ledger Documentation</h1>',
       f'<div class="sub">Business-logic model for the product &amp; hedge ledger<br>Generated {datetime.date.today().isoformat()}</div></div>',
       toc_html()]
for f,ct,body in chapters:
    parts.append(f'<section class="chapter" id="{f}">')
    parts.append(wrap_tables(body))
    parts.append('<a class="backtop" href="#top">↑ Back to contents</a></section>')
parts.append('</div></body></html>')

out = ROOT/'build'/'ledger_docs.html'
out.write_text(''.join(parts), encoding='utf-8')
print("wrote", out, out.stat().st_size, "bytes;", len(chapters), "chapters")
