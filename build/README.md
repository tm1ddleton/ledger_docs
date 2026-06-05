# Documentation bundle build

Generates a single offline-readable bundle of all docs (for iPad etc.).

```
pip install markdown pygments weasyprint   # weasyprint only needed for PDF
python3 build/make_html.py    # -> build/ledger_docs.html  (self-contained, also source for PDF)
python3 build/make_epub.py    # -> build/ledger_docs.epub  (EPUB3, opens in Books)
python3 -c "from weasyprint import HTML; HTML('build/ledger_docs.html').write_pdf('build/ledger_docs.pdf')"
```

The chapter order is defined by `ORDER` in `make_html.py`. Cross-document
`*.md` links are rewritten to in-page anchors. Generated outputs are
gitignored.
