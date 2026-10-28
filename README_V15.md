# huangren V15 — 原始证据深度登记

V15 不增加 V13 的 74 条历史记录，也不把目录内容自动变成正式 SKU。它把原始画册页码、型号存在性、系列后缀、候选别名、图纸存在性与工程核验状态分开管理。

## 原始来源
- 文件：汇成五金画册(1).pdf（用户文件库原件，不随仓库公开）
- 文件大小：173,132,513 bytes；195页
- SHA-256：`13b025c578ae6d0f164843545d8d6539ed5c36861b5b2b061832ea69f2d360b2`
- 原件校验结果见 `docs/source_integrity_check_v15.json`

## 复现
```bash
python -m unittest discover -s tests -p "test_evidence_registry_v15.py" -v
python src/ecom_images/evidence_registry_v15.py
python src/ecom_images/evidence_registry_v15.py db-init --database data/evidence_v15.sqlite3
python src/ecom_images/evidence_registry_v15.py db-import --database data/evidence_v15.sqlite3 --dry-run
python src/ecom_images/evidence_registry_v15.py db-import --database data/evidence_v15.sqlite3
python src/ecom_images/evidence_registry_v15.py db-check --database data/evidence_v15.sqlite3
```
证据库与正式SKU表隔离，历史快照、来源和断言为append-only。目录页码不等于工程核验；所有技术参数和店铺SKU仍需人工确认。
