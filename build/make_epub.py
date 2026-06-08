# Build an EPUB3 from the same ordered docs (opens in iPad Books, fully offline).
import re, markdown, zipfile, html, pathlib, datetime, uuid
ROOT=pathlib.Path('.')
import importlib.util
spec=importlib.util.spec_from_file_location("mh", ROOT/'build'/'make_html.py')
# reuse ORDER/base/ghslug/slugify/rewrite_links by importing the module's globals
src=(ROOT/'build'/'make_html.py').read_text()
# we re-declare minimal pieces here to avoid running the html writer
ORDER=[('CLAUDE.md','Project Overview & Definitions'),('docs/invariants.md',None),('docs/state.md',None),
('docs/events.md',None),('docs/implementation.md',None),('docs/smart_contracts/equities.md',None),
('docs/smart_contracts/futures.md',None),('docs/smart_contracts/funding.md',None),
('docs/smart_contracts/equity_options.md',None),('docs/smart_contracts/structured_products.md',None),
('docs/smart_contracts/cash_payments.md',None),('docs/smart_contracts/bonds_wip.md',None),
('docs/smart_contracts/fx_wip.md',None),('docs/smart_contracts/irs_wip.md',None),
('docs/smart_contracts/qis_wip.md',None),('docs/smart_contracts/stock_borrow_loan_wip.md',None)]
def base(p): return pathlib.Path(p).stem
def ghslug(t):
    t=t.strip().lower(); t=re.sub(r'[^a-z0-9 \-]','',t); return t.replace(' ','-')
cur={'v':''}
def slugify(v,s): return f"{cur['v']}--{ghslug(v)}"
mdlink=re.compile(r'\]\(([^)]+?)\.md(#[^)]*)?\)')
def rewrite(text,thisfile):
    text=re.sub(r'\]\(#([a-z0-9\-]+)\)',lambda m:f"](#{thisfile}--{m.group(1)})",text)
    def repl(m):
        tgt=base(m.group(1)); a=m.group(2) or ''
        return f"](#{tgt}--{a[1:]})" if a else f"](#{tgt})"
    return mdlink.sub(repl,text)

CSS="""body{font-family:-apple-system,Helvetica,Arial,sans-serif;line-height:1.6;color:#1b1b1f}
h1,h2,h3{line-height:1.25}h1{border-bottom:2px solid #e2e2e8;padding-bottom:.3em}
code{font-family:Menlo,Consolas,monospace;font-size:.86em;background:#f5f5f7;padding:.1em .3em;border-radius:4px}
pre{background:#f5f5f7;padding:.8em;border-radius:6px;overflow-x:auto;font-size:.8em}
pre code{background:none}table{border-collapse:collapse;font-size:.8em;width:100%;display:block;overflow-x:auto}
th,td{border:1px solid #e2e2e8;padding:.35em .55em;text-align:left;vertical-align:top}th{background:#fafafc}
blockquote{border-left:3px solid #e2e2e8;margin:1em 0;padding:.2em 1em;color:#5b5b66}"""

chapters=[]
for path,title in ORDER:
    f=base(path); cur['v']=f
    raw=rewrite((ROOT/path).read_text(encoding='utf-8'),f)
    md=markdown.Markdown(extensions=['tables','fenced_code','toc','attr_list','sane_lists'],
        extension_configs={'toc':{'slugify':slugify}},output_format='xhtml')
    body=md.convert(raw)
    ctitle=title or (md.toc_tokens[0]['name'] if md.toc_tokens else f)
    chapters.append((f,ctitle,body))

# self-close stray void tags just in case
def xfix(b):
    b=re.sub(r'<(br|hr|img)([^>]*?)>', lambda m:f"<{m.group(1)}{m.group(2)}/>" if not m.group(2).strip().endswith('/') else m.group(0), b)
    return b

uid="urn:uuid:"+str(uuid.uuid4())
today=datetime.date.today().isoformat()
man=[]; spine=[]; navli=[]
files={}
for i,(f,ct,body) in enumerate(chapters,1):
    name=f"ch{i:02d}.xhtml"
    xhtml=(f'<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
           f'<html xmlns="http://www.w3.org/1999/xhtml"><head><meta charset="utf-8"/>'
           f'<title>{html.escape(ct)}</title><link rel="stylesheet" href="style.css"/></head>'
           f'<body id="{f}">{xfix(body)}</body></html>')
    files[f"OEBPS/{name}"]=xhtml
    man.append(f'<item id="ch{i}" href="{name}" media-type="application/xhtml+xml"/>')
    spine.append(f'<itemref idref="ch{i}"/>')
    navli.append(f'<li><a href="{name}">{html.escape(ct)}</a></li>')

files["OEBPS/style.css"]=CSS
files["OEBPS/nav.xhtml"]=('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
 '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head>'
 '<meta charset="utf-8"/><title>Contents</title></head><body>'
 '<nav epub:type="toc" id="toc"><h1>Contents</h1><ol>'+''.join(navli)+'</ol></nav></body></html>')
files["OEBPS/content.opf"]=('<?xml version="1.0" encoding="utf-8"?>\n'
 '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">'
 f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
 f'<dc:identifier id="bookid">{uid}</dc:identifier>'
 '<dc:title>Ledger Documentation</dc:title><dc:language>en</dc:language>'
 f'<meta property="dcterms:modified">{datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}</meta>'
 '</metadata><manifest>'
 '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
 '<item id="css" href="style.css" media-type="text/css"/>'
 +''.join(man)+'</manifest><spine>'+''.join(spine)+'</spine></package>')
files["META-INF/container.xml"]=('<?xml version="1.0"?>\n'
 '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
 '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
 '</rootfiles></container>')

out=ROOT/'build'/'ledger_docs.epub'
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
    z.writestr("mimetype","application/epub+zip",compress_type=zipfile.ZIP_STORED)
    for name,data in files.items():
        z.writestr(name,data)
print("wrote",out,out.stat().st_size,"bytes;",len(chapters),"chapters")
