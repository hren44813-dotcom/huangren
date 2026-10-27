"""Streamlit catalog console. Initialization and CSV writes require explicit clicks."""
from __future__ import annotations

import sqlite3
from .catalog_v12 import catalog_summary,csv_template,import_catalog_csv,initialize_catalog,list_skus
from .database_v9 import DEFAULT_DB


def render(st) -> None:
    st.subheader("商品 / SKU 数据库档案（V12）")
    st.caption("一套数据库关联店铺、商品、SKU、素材摘要和原有制图任务。不会自动上传、同步或保存商品图片。")
    st.warning("正式导入前先在数据库管理页面备份现有 SQLite 文件。本页不删除历史任务和审核事件。")
    if st.button("初始化商品档案数据表", key="catalog_init"):
        try:
            initialize_catalog(DEFAULT_DB)
            st.success("已完成结构检查与初始化；不会清空原数据库")
        except (OSError,ValueError,RuntimeError,sqlite3.Error) as exc:
            st.error(f"初始化未完成：{exc}")
    try:
        report=catalog_summary(DEFAULT_DB)
        st.write("**当前档案统计**")
        st.json(report)
        st.json(catalog_audit(DEFAULT_DB))
    except (OSError,ValueError,RuntimeError,sqlite3.Error) as exc:
        st.info(f"尚不能读取商品档案：{exc}")
    st.download_button("下载 CSV 商品 SKU 空白模板",data=csv_template(),
                       file_name="工业五金_店铺商品SKU档案模板.csv",mime="text/csv",key="catalog_csv_template")
    file=st.file_uploader("上传已核实商品资料 CSV（UTF-8，最多500行）",type=["csv"],key="catalog_import_csv")
    raw=file.getvalue() if file else b""
    if st.button("第一步：预演导入（不修改数据库）",disabled=not bool(raw),key="catalog_preview"):
        try:
            st.session_state["catalog_preview"]=(__import__("hashlib").sha256(raw).hexdigest(),
                   import_catalog_csv(DEFAULT_DB,raw,dry_run=True))
            st.success("预演通过，可以查看预计新增数量")
        except (ValueError,OSError,RuntimeError,sqlite3.Error) as exc:
            st.session_state.pop("catalog_preview",None)
            st.error(f"预演失败：{exc}")
    cached=st.session_state.get("catalog_preview")
    if cached and raw and cached[0]==__import__("hashlib").sha256(raw).hexdigest():
        st.json(cached[1])
        agree=st.checkbox("我已备份并确认资料真实；正式导入采取整批事务，冲突会回滚整批",key="catalog_confirm")
        if st.button("第二步：正式导入数据库",disabled=not agree,key="catalog_apply"):
            try:
                st.json(import_catalog_csv(DEFAULT_DB,raw,dry_run=False))
                st.success("正式导入成功")
                st.session_state.pop("catalog_preview",None)
            except (ValueError,OSError,RuntimeError,sqlite3.Error) as exc:
                st.error(f"导入未完成（失败批次已回滚）：{exc}")
    col1,col2=st.columns(2)
    with col1:
        store=st.text_input("按店铺编码筛选",key="catalog_store_filter")
    with col2:
        query=st.text_input("SKU、型号或商品名称搜索",key="catalog_search_filter")
    if st.button("查询 SKU 档案",key="catalog_search"):
        try:
            st.dataframe(list_skus(DEFAULT_DB,store_code=store,search=query,limit=100),
                         use_container_width=True,hide_index=True)
        except (ValueError,RuntimeError,OSError,sqlite3.Error) as exc:
            st.error(f"查询失败：{exc}")
    st.caption("本机 SQLite 没有账号隔离及云端同步；审核通过还需核对真实产品图、尺寸标注与参数来源。")
