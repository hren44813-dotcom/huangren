"""Chinese Streamlit workspace for source-grounded V13 parameter review."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from .database_v9 import DEFAULT_DB
from .knowledge_schema_v13 import initialize_knowledge
from .knowledge_ingest_v13 import MAX_SOURCE_BYTES, import_document, initialize_ingestion, knowledge_document_summary, search_knowledge, search_models
from .knowledge_v13 import add_model
from .knowledge_claims_v13 import transition_conflict
from .knowledge_review_v13 import (
    create_claim_from_segment, get_claim_review_detail, list_open_conflicts,
    list_review_claims, list_review_sources, record_claim_review, render_segment_preview,
)

_SOURCE_KINDS = {
    "manufacturer_document": "制造商资料",
    "supplier_document": "供应商资料",
    "purchase_record": "采购记录",
    "physical_photo": "实物照片",
    "lab_report": "实验室报告",
    "platform_export": "平台导出",
    "internal_note": "内部备注",
    "other": "其他",
}
_AUTHORITY = {
    "unverified": "未验证", "user_supplied": "用户提供",
    "manufacturer_controlled": "制造商受控资料", "independent_test": "独立测试",
    "system_export": "系统导出",
}
_CLAIM_KINDS = {
    "catalog_transcription": "目录原文转录",
    "supplier_assertion": "供应商声明",
    "physical_measurement": "实物测量",
    "independent_test": "独立测试",
    "manual_observation": "人工观察",
    "system_inference": "系统推断（需特别谨慎）",
}
_REVIEWER_ROLES = {
    "author": "录入人/作者", "second_reviewer": "第二复核人",
    "manufacturer": "制造商", "independent_lab": "独立实验室",
    "warehouse": "仓库", "other": "其他",
}
_VERDICTS = {"支持": "supports", "反对": "contradicts", "暂不能判断": "inconclusive"}


def _location_label(item: dict[str, Any]) -> str:
    location = item.get("location") or {}
    parts = []
    if location.get("pdf_page"):
        parts.append(f"PDF物理页 {location['pdf_page']}")
    if location.get("printed_page"):
        parts.append(f"印刷页 {location['printed_page']}")
    if location.get("sheet_name"):
        parts.append(f"工作表 {location['sheet_name']}")
    if location.get("cell_range"):
        parts.append(f"单元格 {location['cell_range']}")
    if location.get("line_start"):
        end = location.get("line_end") or location["line_start"]
        parts.append(f"行 {location['line_start']}" if end == location["line_start"] else f"行 {location['line_start']}-{end}")
    if location.get("heading_path"):
        parts.append(f"标题 {location['heading_path']}")
    return " · ".join(parts) or "未提供精确位置"


def _model_options(model_code: str) -> tuple[list[str], dict[str, dict[str, Any]]]:
    if not model_code.strip():
        return [], {}
    models = search_models(DEFAULT_DB, query=model_code.strip(), limit=200)
    exact = [m for m in models if m["model_code"].casefold() == model_code.strip().casefold()]
    exact.sort(key=lambda m: (m["manufacturer"].casefold(), m["category"].casefold()))
    options = [m["model_id"] for m in exact]
    details = {m["model_id"]: m for m in exact}
    return options, details


def _safe_uploaded_filename(value: str) -> str:
    if not isinstance(value, str) or len(value) > 1024:
        raise ValueError("上传文件名无效")
    basename = value.replace("\\", "/").split("/")[-1].strip()
    if not basename or basename in {".", ".."}:
        raise ValueError("上传文件名无效")
    suffix = Path(basename).suffix.lower()
    if suffix not in {".pdf", ".docx", ".md", ".markdown", ".txt", ".xlsx", ".xlsm", ".xls", ".html", ".htm"}:
        raise ValueError("文件格式不支持；请上传 PDF、DOCX、Markdown、TXT、XLSX、XLSM、XLS 或 HTML")
    stem = basename[:-len(Path(basename).suffix)] if Path(basename).suffix else basename
    stem = "".join(char if ord(char) >= 32 and char not in {"/", "\\"} else "_" for char in stem).strip()
    if not stem:
        stem = "imported-document"
    stem = stem[:255 - len(suffix)]
    return stem + suffix


def _flash(st, level: str, message: str) -> None:
    st.session_state["review_flash"] = (level, message)
    st.rerun()


def _render_document_import(st) -> None:
    with st.expander("导入原始资料", expanded=False):
        with st.form("review_document_import_form"):
            uploaded = st.file_uploader(
                "选择原始资料（单文件，最大 100 MiB）",
                type=["pdf", "docx", "md", "markdown", "txt", "xlsx", "xlsm", "xls", "html", "htm"],
                key="review_import_file",
            )
            kind_label = st.selectbox("资料类型", [value for key, value in _SOURCE_KINDS.items() if key != "physical_photo"], key="review_import_kind")
            authority_label = st.selectbox(
                "来源等级", list(_AUTHORITY.values()), index=1, key="review_import_authority"
            )
            family = st.text_input("文档系列（可选）", max_chars=200, key="review_import_family")
            document_number = st.text_input("文件编号（可选）", max_chars=200, key="review_import_number")
            revision = st.text_input("修订版（可选）", max_chars=100, key="review_import_revision")
            issue_date = st.text_input("发布日期 YYYY-MM-DD（可选）", max_chars=40, key="review_import_date")
            submitted = st.form_submit_button("导入并建立检索索引")
        if not submitted:
            return
        if uploaded is None:
            st.error("请先选择要导入的原始资料。")
            return
        raw = uploaded.getvalue()
        if not raw:
            st.error("上传文件为空。")
            return
        if len(raw) > MAX_SOURCE_BYTES:
            st.error(f"文件超过大小限制（{MAX_SOURCE_BYTES} 字节）。")
            return
        try:
            safe_name = _safe_uploaded_filename(uploaded.name)
            kind = next(key for key, value in _SOURCE_KINDS.items() if value == kind_label)
            authority = next(key for key, value in _AUTHORITY.items() if value == authority_label)
            with tempfile.TemporaryDirectory(prefix="huangren-review-", dir=DEFAULT_DB.parent) as temporary_directory:
                temporary_path = Path(temporary_directory) / safe_name
                temporary_path.write_bytes(raw)
                result = import_document(
                    DEFAULT_DB, file_path=temporary_path, source_kind=kind, authority_level=authority,
                    document_family=family, document_number=document_number,
                    revision_label=revision, issue_date=issue_date,
                )
            st.session_state.pop("review_search_result", None)
            _flash(st, "success",
                   f"已导入 {result['filename']}，索引片段 {result['segment_count']} 条。"
                   "原始资料已保存在本机；导入不会自动生成或接受参数主张。")
        except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
            st.error(f"原始资料导入失败：{exc}")


def _render_model_registration(st, model_code: str) -> None:
    if not model_code.strip():
        return
    st.info("当前没有精确匹配的制造商型号档案。先显式登记型号身份；这不会创建或确认任何店铺 SKU 映射。")
    with st.form("review_register_model_form"):
        code = st.text_input("制造商型号（精确值）", value=model_code.strip(), max_chars=100)
        manufacturer = st.text_input("制造商名称（未知可留空）", max_chars=200)
        category = st.text_input("商品类别", value="工业五金", max_chars=100)
        series = st.text_input("系列（可选）", max_chars=100)
        submitted = st.form_submit_button("登记制造商型号")
    if submitted:
        try:
            ident = add_model(DEFAULT_DB, model_code=code, manufacturer_name=manufacturer,
                              category=category, series=series)
            st.session_state["review_registered_model_id"] = ident
            _flash(st, "success", f"制造商型号档案已登记：{code}。未自动关联任何 SKU。")
        except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
            st.error(f"型号登记失败：{exc}")


def _render_document_result(st, item: dict[str, Any], model_options: list[str],
                            model_details: dict[str, dict[str, Any]], attribute: str) -> None:
    segment_id = item["segment_id"]
    location = item.get("location") or {}
    title = f"{item['filename']} · {_location_label(item)}"
    with st.expander(title, expanded=False):
        st.caption(
            f"来源类型：{_SOURCE_KINDS.get(item.get('source_kind', ''), item.get('source_kind', '未知'))} · "
            f"来源等级：{_AUTHORITY.get(item.get('authority_level', ''), item.get('authority_level', '未知'))}"
        )
        st.caption(f"来源 ID：{item['source_id']} · SHA-256：{item['source_sha256']}")
        source_metadata = item.get("source_metadata") or {}
        if source_metadata.get("source_url"):
            st.markdown(f"**原始网页：** [{source_metadata['source_url']}]({source_metadata['source_url']})")
        if source_metadata.get("page_kind"):
            st.caption(f"网页类型：{source_metadata['page_kind']} · 采集方式：{source_metadata.get('capture_method', '文件导入')}")
        st.caption(f"片段类型：{item['segment_type']} · 片段 ID：{segment_id}")
        st.code(item.get("text", ""), language=None)
        st.write("**原始位置**")
        st.json(location)
        if location.get("pdf_page") and item.get("segment_type") in {"pdf_page", "pdf_line"}:
            preview_key = f"review_pdf_preview_{segment_id}"
            if st.button("校验原文件并显示 PDF 页图", key=f"review_pdf_button_{segment_id}"):
                try:
                    st.session_state[preview_key] = render_segment_preview(DEFAULT_DB, segment_id=segment_id)
                except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
                    st.session_state.pop(preview_key, None)
                    st.error(f"PDF 预览失败：{exc}")
            preview = st.session_state.get(preview_key)
            if preview and preview.get("available"):
                st.image(preview["png"], caption=(
                    f"{preview['filename']} · 物理页 {preview['pdf_page']} · "
                    f"已高亮定位区域：{'是' if preview['highlighted'] else '否'}"
                ), use_container_width=True)
                st.caption(f"预览源 SHA-256：{preview['source_sha256']}")
        else:
            st.caption("此结果不是 PDF 页片段；使用上方原文和结构化位置核对，不生成虚构页码。")
        if not model_options:
            st.warning("需要先在本页显式登记精确制造商型号，才能把这条资料作为候选证据挂接到型号主张。")
            return
        with st.form(f"review_candidate_claim_{segment_id}"):
            model_id = st.selectbox(
                "制造商型号身份（显式选择）", model_options,
                format_func=lambda value: (
                    f"{model_details[value]['manufacturer'] or '制造商未注明'} · "
                    f"{model_details[value]['model_code']} · {model_details[value]['category']}"
                ),
                key=f"review_candidate_model_{segment_id}",
            )
            claim_attribute = st.text_input("参数名称", value=attribute.strip(), max_chars=150,
                                            key=f"review_candidate_attribute_{segment_id}")
            literal_value = st.text_input("候选原始值（按资料原文填写）", max_chars=1000,
                                          key=f"review_candidate_value_{segment_id}")
            unit = st.text_input("单位（无单位可留空）", max_chars=50,
                                 key=f"review_candidate_unit_{segment_id}")
            kind_label = st.selectbox("主张类型", list(_CLAIM_KINDS.values()),
                                      key=f"review_candidate_kind_{segment_id}")
            author = st.text_input("录入人", max_chars=100, key=f"review_candidate_author_{segment_id}")
            checked = st.checkbox("我已查看原文片段与位置，并确认候选值是人工填写而非自动推断",
                                  key=f"review_candidate_checked_{segment_id}")
            submitted = st.form_submit_button("创建待复核主张并挂接来源证据")
        if submitted:
            if not checked:
                st.error("请先确认已人工核对原文片段与位置。")
                return
            kind = next(key for key, value in _CLAIM_KINDS.items() if value == kind_label)
            try:
                result = create_claim_from_segment(
                    DEFAULT_DB, segment_id=segment_id, model_id=model_id,
                    attribute=claim_attribute, literal_value=literal_value, unit=unit,
                    claim_kind=kind, created_by=author, evidence_role="supports",
                )
                _flash(st, "success",
                       f"已创建待复核主张 {result['claim_id']}，并原子挂接来源证据。当前状态：待复核。")
            except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
                st.error(f"候选主张创建失败：{exc}")


def _render_claim_review(st, claim: dict[str, Any]) -> None:
    claim_id = claim["claim_id"]
    state = claim["state"]
    identity = claim["model_code"]
    if not identity and claim.get("sku_model_text"):
        identity = f"SKU 自由文本 {claim['sku_model_text']}（未确认制造商型号）"
    elif not identity:
        identity = claim["subject_type"]
    binding_labels = {
        "manufacturer_model": "制造商型号档案",
        "confirmed_sku_model_mapping": "已确认 SKU 映射",
        "sku_free_text_unverified": "SKU 自由文本，型号未确认",
        "no_model_text": "SKU 未填写型号",
        "not_applicable": "非型号对象",
    }
    binding = binding_labels.get(claim.get("model_binding_status", "not_applicable"), "型号身份待核对")
    st.markdown(f"**{identity} · {claim['attribute']}：{claim['literal_value']} {claim['unit']}**")
    st.caption(
        f"状态：{state} · 型号身份：{binding} · 证据 {claim['evidence_count']} 条 · "
        f"复核 {claim['review_count']} 条 · 主张 ID：{claim_id}"
    )
    detail = get_claim_review_detail(DEFAULT_DB, claim_id=claim_id)
    with st.expander("查看证据、复核和状态历史", expanded=False):
        if not detail["evidence"]:
            st.warning("该主张尚无来源证据，不可接受。")
        for evidence in detail["evidence"]:
            st.markdown(
                f"**{evidence['filename']}** · {_AUTHORITY.get(evidence['authority_level'], evidence['authority_level'])} · "
                f"{evidence['role']} · PDF物理页：{evidence['pdf_page'] or '不适用'}"
            )
            st.caption(f"SHA-256：{evidence['source_sha256']}")
            st.code(evidence["literal_excerpt"] or "未保存原文摘录", language=None)
            st.json(evidence["region"])
        if detail["reviews"]:
            st.write("**复核历史**")
            st.dataframe(detail["reviews"], use_container_width=True, hide_index=True)
        if detail["events"]:
            st.write("**状态历史**")
            st.dataframe(detail["events"], use_container_width=True, hide_index=True)
    if state == "superseded":
        st.caption("该主张已被替代，当前只读。")
        return
    with st.form(f"review_existing_claim_{claim_id}"):
        verdict_label = st.selectbox("复核结论", list(_VERDICTS.keys()), key=f"review_verdict_{claim_id}")
        role_label = st.selectbox("审核人角色", list(_REVIEWER_ROLES.values()), key=f"review_role_{claim_id}")
        reviewer = st.text_input("审核人", max_chars=100, key=f"review_name_{claim_id}")
        method = st.text_input("复核方法（例如：对照原厂图纸原文）", max_chars=300,
                               key=f"review_method_{claim_id}")
        notes = st.text_area("复核说明", max_chars=1000, key=f"review_notes_{claim_id}")
        decision_options = ["仅记录复核"]
        if state in {"proposed", "reopened"}:
            if verdict_label != "反对":
                decision_options.append("接受主张")
            decision_options.append("拒绝主张")
        elif state == "accepted":
            decision_options.append("拒绝主张")
            if verdict_label != "反对":
                decision_options.append("重新打开")
        elif state == "rejected":
            decision_options.append("重新打开")
        decision_label = st.selectbox("状态动作", decision_options, key=f"review_decision_{claim_id}")
        decision_note = st.text_input("状态变更说明（拒绝/重新打开时必填）", max_chars=500,
                                      key=f"review_decision_note_{claim_id}")
        submitted = st.form_submit_button("追加复核记录")
    if submitted:
        decision_map = {"仅记录复核": "", "接受主张": "accepted", "拒绝主张": "rejected", "重新打开": "reopened"}
        verdict = _VERDICTS[verdict_label]
        role = next(key for key, value in _REVIEWER_ROLES.items() if value == role_label)
        try:
            result = record_claim_review(
                DEFAULT_DB, claim_id=claim_id, verdict=verdict, reviewer_role=role,
                reviewer_name=reviewer, method=method, notes=notes,
                decision_state=decision_map[decision_label], actor=reviewer,
                decision_note=decision_note,
            )
            _flash(st, "success", f"复核已追加；主张当前状态：{result['state']}。")
        except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
            st.error(f"复核未提交：{exc}")
            st.caption("如果接受门槛未通过，复核和状态事件会一并回滚，不会留下半提交记录。")


def _render_conflicts(st, model_code: str, attribute: str) -> None:
    st.subheader("未解决参数冲突")
    try:
        conflicts = list_open_conflicts(DEFAULT_DB, model_code=model_code, attribute=attribute, limit=100)
        sources = list_review_sources(DEFAULT_DB, limit=200)
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        st.error(f"冲突队列读取失败：{exc}")
        return
    if not conflicts:
        st.success("当前筛选条件下没有未解决冲突。")
        return
    if not sources:
        st.warning("尚无已登记来源，不能将冲突标记为解决。")
        return
    source_ids = [item["source_id"] for item in sources]
    source_labels = {
        item["source_id"]: (
            f"{item['filename']} · {_AUTHORITY.get(item['authority_level'], item['authority_level'])} · "
            f"{item['sha256'][:12]}…"
        ) for item in sources
    }
    for conflict in conflicts:
        a, b = conflict["claim_a"], conflict["claim_b"]
        with st.expander(
            f"{a['model_code'] or a['subject_type']} · {a['attribute']}："
            f"{a['literal_value']} ↔ {b['literal_value']} · {conflict['state']}",
            expanded=False,
        ):
            st.warning(conflict["description"])
            left, right = st.columns(2)
            with left:
                st.markdown("**主张 A**")
                st.write(f"{a['literal_value']} {a['unit']}")
                st.caption(f"ID：{a['claim_id']} · 状态：{a['state']}")
            with right:
                st.markdown("**主张 B**")
                st.write(f"{b['literal_value']} {b['unit']}")
                st.caption(f"ID：{b['claim_id']} · 状态：{b['state']}")
            with st.form(f"resolve_conflict_{conflict['conflict_id']}"):
                source_id = st.selectbox("解决依据（必须是已登记来源）", source_ids,
                                         format_func=lambda value: source_labels[value],
                                         key=f"conflict_source_{conflict['conflict_id']}")
                actor = st.text_input("处理人", max_chars=100, key=f"conflict_actor_{conflict['conflict_id']}")
                note = st.text_area("处理说明（说明采用哪份资料及理由）", max_chars=1000,
                                    key=f"conflict_note_{conflict['conflict_id']}")
                checked = st.checkbox("我已对照所选来源，并记录了处理理由",
                                      key=f"conflict_checked_{conflict['conflict_id']}")
                submitted = st.form_submit_button("记录冲突处理")
            if submitted:
                if not checked:
                    st.error("请先确认已核对来源并记录处理理由。")
                    continue
                try:
                    transition_conflict(DEFAULT_DB, conflict_id=conflict["conflict_id"], state="resolved",
                                        actor=actor, resolution_note=note, source_id=source_id)
                    _flash(st, "success", "冲突处理已追加；原冲突及历史状态不会被覆盖。")
                except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
                    st.error(f"冲突处理未提交：{exc}")


def render(st) -> None:
    """Render the local-only V13 evidence review workspace."""
    st.subheader("参数证据审核 · V13")
    st.caption(
        "先看原始资料和定位，再人工录入候选值并复核。原文检索不等于参数认证；"
        "本页不会自动接受参数或建立 SKU 型号映射。"
    )
    if not DEFAULT_DB.is_file():
        st.info("当前没有本机数据库。请先在“商品 / SKU 档案”页初始化商品档案，再初始化 V13 知识库。")
        return
    if st.button("初始化 / 检查 V13 文档索引", key="review_initialize_v13"):
        try:
            initialize_knowledge(DEFAULT_DB)
            initialize_ingestion(DEFAULT_DB)
            st.success("V13 知识库与文档索引结构检查完成；既有数据不会被清空。")
        except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
            st.error(f"初始化未完成：{exc}")
    flash = st.session_state.pop("review_flash", None)
    if flash:
        getattr(st, flash[0])(flash[1])
    try:
        summary = knowledge_document_summary(DEFAULT_DB)
        a, b, c, d = st.columns(4)
        a.metric("已登记来源", summary["counts"]["sources"])
        b.metric("已索引来源", summary["counts"]["indexed_sources"])
        c.metric("检索片段", summary["counts"]["segments"])
        d.metric("待处理主张", len(list_review_claims(DEFAULT_DB, state="proposed", limit=200)))
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        st.warning(f"文档索引尚不可用：{exc}")
        st.info("如果 V13 已初始化，请点击上方按钮检查/初始化文档索引；如果商品档案尚未初始化，请先前往“商品 / SKU 档案”页。")
        return

    _render_document_import(st)

    with st.form("review_search_form"):
        model_col, attribute_col = st.columns(2)
        with model_col:
            model_code = st.text_input("制造商型号（精确匹配）", max_chars=100, key="review_search_model")
        with attribute_col:
            attribute = st.text_input("参数名称 / 关键词", max_chars=150, key="review_search_attribute")
        query = st.text_input("补充关键词（可选）", max_chars=300, key="review_search_query")
        limit = st.selectbox("最多显示结果", [20, 50, 100], index=1, key="review_search_limit")
        submitted = st.form_submit_button("检索型号、原始资料与已有主张")
    if submitted:
        try:
            result = search_knowledge(DEFAULT_DB, query=query, model_code=model_code,
                                      attribute=attribute, limit=int(limit))
            st.session_state["review_search_result"] = {
                "model_code": model_code.strip(), "attribute": attribute.strip(),
                "query": query.strip(), "result": result,
            }
        except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
            st.session_state.pop("review_search_result", None)
            st.error(f"检索失败：{exc}")

    cached = st.session_state.get("review_search_result")
    if not cached:
        st.info("输入型号或关键词后开始检索。建议先用精确制造商型号，再加“扭矩、材质、孔距”等参数关键词。")
        _render_conflicts(st, "", "")
        return

    model_code = cached["model_code"]
    attribute = cached["attribute"]
    result = cached["result"]
    st.write(f"**检索结果：{result['result_count']} 条**")
    st.caption(result["search_note"])
    try:
        model_options, model_details = _model_options(model_code)
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        st.error(f"制造商型号档案读取失败：{exc}")
        model_options, model_details = [], {}
    if model_code and not model_options:
        _render_model_registration(st, model_code)

    model_hits = [item for item in result["results"] if item["type"] == "model"]
    if model_hits:
        st.markdown("**制造商型号身份**")
        st.dataframe([{
            "制造商": item["manufacturer"], "型号": item["model_code"], "类别": item["category"],
            "系列": item["series"], "SKU映射数": item["sku_mapping_count"],
            "最近映射状态": item["latest_mapping_state"] or "无映射",
        } for item in model_hits], use_container_width=True, hide_index=True)
    sku_hits = [item for item in result["results"] if item["type"] == "sku_model_text"]
    if sku_hits:
        st.markdown("**SKU 中的型号文本（不等于已确认映射）**")
        st.dataframe([{
            "店铺": item["store_name"], "商品": item["product_name"], "SKU": item["sku_code"],
            "型号文本": item["model_text"], "映射状态": item["model_binding_status"],
        } for item in sku_hits], use_container_width=True, hide_index=True)
    docs = [item for item in result["results"] if item["type"] == "document"]
    if docs:
        st.markdown("**原始资料候选片段**")
        for item in docs:
            _render_document_result(st, item, model_options, model_details, attribute)
    else:
        st.info("当前条件没有命中已索引原始资料片段。可先在文档导入命令中导入资料，再重新检索。")

    claim_hits = [item for item in result["results"] if item["type"] == "claim"]
    if claim_hits:
        st.markdown("**检索命中的已有参数主张**")
        st.dataframe([{
            "型号": item["model_code"], "参数": item["attribute"], "原始值": item["literal_value"],
            "单位": item["unit"], "状态": item["state"], "证据数": len(item["evidence"]),
            "SKU映射状态": item["model_binding_status"],
        } for item in claim_hits], use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("参数主张复核队列")
    try:
        claims = list_review_claims(DEFAULT_DB, model_code=model_code, attribute=attribute, limit=100)
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        st.error(f"主张队列读取失败：{exc}")
        claims = []
    if not claims:
        st.info("当前筛选条件下没有已登记的参数主张。可从上方原始资料片段创建待复核主张。")
    for claim in claims:
        with st.expander(
            f"{claim['model_code'] or claim['subject_type']} · {claim['attribute']}："
            f"{claim['literal_value']} {claim['unit']} · {claim['state']}",
            expanded=False,
        ):
            _render_claim_review(st, claim)
    _render_conflicts(st, model_code, attribute)
