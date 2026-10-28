# V16: GL1-336 single-model deep audit

V16 deliberately deepens one record rather than expanding model coverage. It separates the original file fingerprint, catalog text, drawing-callout transcription, unresolved conflicts, physical identity, and store-SKU mapping.

## Source fingerprint
- File: 汇成五金画册(1).pdf (private user-library original; not in this repository)
- SHA-256: 13b025c578ae6d0f164843545d8d6539ed5c36861b5b2b061832ea69f2d360b2
- Size: 173,132,513 bytes; 195 pages
- Target: PDF page 37, printed page 24
- No title/author/creation/modification date or revision was found in PDF metadata; revision currency remains unknown.

## Run
```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p "test_gl1_336_deep_audit_v16.py" -v
python src/ecom_images/gl1_336_deep_audit_v16.py "/path/to/汇成五金画册(1).pdf" --output-dir build/gl1_336_v16
```

## Key open issues
1. V13 historical torque unit note says kgf·cm, while the page-37 table header says N.m.
2. The PDF text layer alternates HC01 and HCO1 in several part codes; image transcription suggests HC01, but manufacturer BOM/second-person review is required.
3. Drawing labels are transcribed, not independently measured; hole-pattern semantics require native CAD/engineering review.
4. Twelve manufacturer-code rows are not store SKUs; no physical item, manufacturer confirmation, or SKU crosswalk was available.

The PDF and page crops are not committed to this public repository. The source hash identifies the reviewed bytes; it does not authenticate the publisher or establish that the file is the current controlled revision.
