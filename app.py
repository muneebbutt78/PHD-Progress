import streamlit as st
import pandas as pd
import os
import re
import json
import base64
from io import BytesIO
from datetime import date

from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.platypus import PageBreak


# =====================================================
# PAGE CONFIG
# =====================================================
st.set_page_config(page_title="Thesis Progress Tracker", layout="wide")

st.title("📘 Thesis Progress Tracker")
st.caption("Supervisor-Friendly Research Monitoring System")

# =====================================================
# PATHS
# =====================================================
FILE_PATH = "Thesis_Progress_Complete.xlsx"
FALLBACK_FILE_PATH = "/mnt/data/Thesis_Progress_Complete.xlsx"  # helpful in some environments

DOC_BASE = "Research_Documents"
COMMENTS_FILE = os.path.join(DOC_BASE, "_comments.json")

# =====================================================
# HELPERS — COMMENTS
# =====================================================
def load_comments():
    os.makedirs(DOC_BASE, exist_ok=True)
    if not os.path.exists(COMMENTS_FILE):
        return {}
    try:
        with open(COMMENTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_comments(comments: dict):
    os.makedirs(DOC_BASE, exist_ok=True)
    with open(COMMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(comments, f, indent=2, ensure_ascii=False)

def resolve_category_path(base_dir, expected_folder):
    """
    Resolves folder path even if case / spaces differ
    """
    if not os.path.exists(base_dir):
        return None

    expected = expected_folder.replace("_", " ").lower()

    for f in os.listdir(base_dir):
        if os.path.isdir(os.path.join(base_dir, f)):
            if f.lower() == expected or f.lower().replace(" ", "_") == expected_folder.lower():
                return os.path.join(base_dir, f)

    # fallback (original)
    return os.path.join(base_dir, expected_folder)


# =====================================================
# HELPERS — FILE LISTING
# =====================================================
def list_files_recursive(root_dir: str):
    out = []
    if not os.path.exists(root_dir):
        return out
    for base, _, files in os.walk(root_dir):
        for fn in files:
            # ignore comments file
            if fn.lower() == os.path.basename(COMMENTS_FILE).lower():
                continue
            out.append(os.path.join(base, fn))
    # stable ordering
    out.sort(key=lambda p: (os.path.dirname(p), os.path.basename(p)))
    return out

def list_zip_files_for_category(base_dir, category_key):
    """
    Lists ZIP files in base_dir whose names match category_key
    """
    if not os.path.exists(base_dir):
        return []

    files = []
    for f in os.listdir(base_dir):
        if f.lower().endswith(".zip") and category_key in f.lower():
            files.append(os.path.join(base_dir, f))

    return sorted(files)


# =====================================================
# HELPERS — PDF PREVIEW
# =====================================================
def render_pdf_inline(pdf_path: str, height: int = 550):
    """Inline PDF preview using base64 iframe (works on Streamlit Cloud too)."""
    try:
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        b64 = base64.b64encode(pdf_bytes).decode("utf-8")
        pdf_display = f"""
        <iframe
            src="data:application/pdf;base64,{b64}"
            width="100%"
            height="{height}"
            style="border: 1px solid #ddd; border-radius: 8px;"
            type="application/pdf">
        </iframe>
        """
        st.components.v1.html(pdf_display, height=height + 20, scrolling=True)
    except Exception as e:
        st.error(f"Could not preview PDF: {e}")

# =====================================================
# SUPERVISOR LOGIN
# =====================================================
# If secrets not set, keep app usable (supervisor-only features disabled)
SUPERVISOR_PASSWORD = st.secrets.get("SUPERVISOR_PASSWORD", None)

with st.sidebar:
    st.subheader("🔐 Supervisor Login")

    if "is_supervisor" not in st.session_state:
        st.session_state.is_supervisor = False

    if SUPERVISOR_PASSWORD is None:
        st.info("Supervisor password not set in Secrets. Supervisor-only features are disabled.")
        st.session_state.is_supervisor = False
    else:
        if not st.session_state.is_supervisor:
            pw = st.text_input("Password", type="password")
            if st.button("Login"):
                if pw == SUPERVISOR_PASSWORD:
                    st.session_state.is_supervisor = True
                    st.success("Logged in")
                else:
                    st.error("Invalid password")
        else:
            st.success("Supervisor Mode")
            if st.button("Logout"):
                st.session_state.is_supervisor = False

is_supervisor = st.session_state.is_supervisor

# =====================================================
# LOAD EXCEL (HEADER AUTO DETECT)
# =====================================================
excel_path = FILE_PATH if os.path.exists(FILE_PATH) else FALLBACK_FILE_PATH
if not os.path.exists(excel_path):
    st.error(f"❌ Excel file not found: {FILE_PATH}")
    st.stop()

raw = pd.read_excel(excel_path, header=None)

EXPECTED_HEADERS = ["s.no", "step", "weightage", "actual", "progress", "weighted"]
header_row = None

for i in range(len(raw)):
    row = raw.iloc[i].astype(str).str.lower().tolist()
    hits = sum(any(h in cell for cell in row) for h in EXPECTED_HEADERS)
    if hits >= 3:
        header_row = i
        break

if header_row is None:
    st.error("❌ Could not detect header row in Excel.")
    st.stop()

df = raw.iloc[header_row + 1:].copy()
df.columns = raw.iloc[header_row].astype(str).str.strip()

# =====================================================
# NORMALIZE COLUMN NAMES
# =====================================================
COL_MAP = {
    "s.no": "S.No",
    "sr no": "S.No",
    "step": "Step",
    "weightage (%)": "Weightage",
    "weightage": "Weightage",
    "actual progress (%)": "Actual",
    "actual progress": "Actual",
    "progress (%)": "Actual",
    "weighted progress (%)": "Weighted",
    "weighted progress": "Weighted",
    "supervisor comments": "Supervisor Comments",
    "rationale": "Rationale",
}

df.columns = [COL_MAP.get(str(c).lower().strip(), str(c).strip()) for c in df.columns]

def resolve(names):
    for c in df.columns:
        if str(c).lower().strip() in names:
            return c
    return None

SERIAL_COL = resolve(["s.no"])
STEP_COL = resolve(["step"])
WEIGHT_COL = resolve(["weightage"])
ACTUAL_COL = resolve(["actual"])
WEIGHTED_COL = resolve(["weighted"])

if not STEP_COL or not WEIGHT_COL or not ACTUAL_COL:
    st.error(f"❌ Required columns missing.\nDetected: {list(df.columns)}")
    st.stop()

# Remove repeated header rows
if SERIAL_COL:
    df = df[df[SERIAL_COL].astype(str).str.lower() != str(SERIAL_COL).lower()]

# Force numeric (CRITICAL for styling + calculations)
for c in [WEIGHT_COL, ACTUAL_COL, WEIGHTED_COL]:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")

# =====================================================
# CLASSIFY ROWS
# =====================================================
def classify_row(row):
    step = str(row[STEP_COL]).strip()
    step_l = step.lower()
    sno = str(row[SERIAL_COL]).strip() if SERIAL_COL else ""

    if "subtotal" in step_l:
        return "subtotal"
    # keep your old detection for "1a", "2b" style serials (optional)
    if sno and re.match(r"^[0-9]+[a-z]$", sno.lower()):
        return "item"
    if "–" in step or step_l.endswith("%"):
        return "heading"
    return "item"

df["row_type"] = df.apply(classify_row, axis=1)

# =====================================================
# SECTION MAPPING
# =====================================================
current = None
sections = []

for _, r in df.iterrows():
    if r["row_type"] == "heading":
        current = r[STEP_COL]
    sections.append(current)

df["section"] = sections

# =====================================================
# CALCULATIONS (LEAF ITEMS ONLY)
# =====================================================
leaf_mask = df[SERIAL_COL].astype(str).str.match(r"^\d+[a-z]$", case=False, na=False)

items = df[
    leaf_mask &
    (df[WEIGHT_COL].notna()) &
    (df[WEIGHT_COL] > 0)
].copy()

items[ACTUAL_COL] = items[ACTUAL_COL].fillna(0)

total_weight = items[WEIGHT_COL].sum()

if not 99 <= total_weight <= 101:
    st.warning(f"⚠ Total effective weightage = {total_weight:.1f}% (expected ~100%).")


overall_progress = (
    (items[WEIGHT_COL] * items[ACTUAL_COL] / 100).sum()
    / total_weight * 100
)

sec_df = (
    items.groupby("section")
    .apply(lambda x:
        (x[WEIGHT_COL] * x[ACTUAL_COL] / 100).sum()
        / x[WEIGHT_COL].sum() * 100
    )
    .reset_index(name="Progress %")
)

# =====================================================
# TABLE DISPLAY (STYLED)
# =====================================================
df_display = df.drop(columns=["row_type"])

def style_table(df_in):
    def row_style(row):
        step = str(row.get(STEP_COL, "")).strip()
        step_l = step.lower()
        val = row.get(ACTUAL_COL)

        if "subtotal" in step_l:
            return ["background-color:#FFF3CD;font-weight:bold"] * len(row)

        if "–" in step or step_l.endswith("%"):
            return ["background-color:#E8F0FE;font-weight:bold"] * len(row)

        if pd.notna(val):
            try:
                v = float(val)
            except Exception:
                v = None

            if v is not None:
                if v < 50:
                    return ["background-color:#F8D7DA"] * len(row)
                elif v < 80:
                    return ["background-color:#FFF3CD"] * len(row)
                else:
                    return ["background-color:#D4EDDA"] * len(row)

        return [""] * len(row)

    styler = df_in.style.apply(row_style, axis=1)

    fmt_map = {}
    for c in [WEIGHT_COL, ACTUAL_COL, WEIGHTED_COL]:
        if c in df_in.columns:
            fmt_map[c] = "{:.1f}"
    if fmt_map:
        styler = styler.format(fmt_map)

    styler = styler.set_table_styles([
        {"selector": "th", "props": [
            ("background-color", "#0F3D5E"),
            ("color", "white"),
            ("font-weight", "bold"),
            ("text-align", "center")
        ]}
    ])

    return styler

# =====================================================
# WEEKLY SUMMARY TEXT
# =====================================================
def weekly_summary_text():
    lines = [
        f"**Date:** {date.today().strftime('%d-%b-%Y')}",
        f"**Overall Weighted Progress:** {overall_progress:.1f}%",
        "",
        "**Section-wise Progress:**"
    ]

    for _, r in sec_df.iterrows():
        lines.append(
            f"- **{r['section']}** : {r['Progress %']:.1f}%"
        )

    return "\n".join(lines)

# =====================================================
# PDF GENERATORS
# =====================================================
def generate_pdf_weekly_summary(summary_text: str) -> bytes:
    """Returns PDF bytes for weekly summary."""
    styles = getSampleStyleSheet()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    story = [
        Paragraph("<b>Weekly Research Progress Summary</b>", styles["Title"]),
        Spacer(1, 12)
    ]
    for line in summary_text.split("\n"):
        # keep empty lines as spacing
        if line.strip() == "":
            story.append(Spacer(1, 8))
        else:
            story.append(Paragraph(line, styles["Normal"]))
    doc.build(story)
    return buf.getvalue()

def generate_supervisor_review_pdf(df_table: pd.DataFrame, summary_text: str) -> bytes:
    """Returns PDF bytes for supervisor review (table + summary)."""
    styles = getSampleStyleSheet()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)

    story = [
        Paragraph("<b>Supervisor Review – Thesis Progress</b>", styles["Title"]),
        Spacer(1, 10),
        Paragraph(f"Date: {date.today().strftime('%d-%b-%Y')}", styles["Normal"]),
        Spacer(1, 12),
    ]

    # Make a compact table for PDF (convert NaNs to empty)
    df_pdf = df_table.copy()

    # ❌ REMOVE SECTION COLUMN FROM PDF ONLY
    if "section" in df_pdf.columns:
        df_pdf = df_pdf.drop(columns=["section"])

    df_pdf = df_pdf.fillna("")

    # Convert floats to string with 1 decimal for key columns
    for c in [WEIGHT_COL, ACTUAL_COL, WEIGHTED_COL]:
        if c in df_pdf.columns:
            df_pdf[c] = df_pdf[c].apply(lambda x: f"{x:.1f}" if isinstance(x, (int, float)) and x != "" else x)

    data = [df_pdf.columns.tolist()] + df_pdf.values.tolist()
    tbl = Table(data, repeatRows=1)

    tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F3D5E")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F7F7")]),
    ]))

    story.append(tbl)

    # ================= PAGE BREAK =================
    story.append(PageBreak())

    # ================= WEEKLY SUMMARY (PAGE 2) =================
    story.append(Paragraph("<b>Weekly Summary</b>", styles["Title"]))
    story.append(Spacer(1, 12))


    for line in summary_text.split("\n"):
        if line.strip().startswith("-"):
            story.append(Paragraph(line.replace("- ", "• "), styles["Normal"]))
        elif line.strip() == "":
            story.append(Spacer(1, 8))
        else:
            story.append(Paragraph(line, styles["Normal"]))


    doc.build(story)
    return buf.getvalue()

# =====================================================
# MAIN TABS
# =====================================================
tab1, tab2 = st.tabs(["📊 Thesis Progress", "📂 Research Documents"])

# =====================================================
# TAB 1 — ORDER FIXED
# =====================================================
with tab1:
    st.subheader("📊 Thesis Overview")
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Weightage", f"{total_weight:.1f}%")
    c2.metric("Overall Progress", f"{overall_progress:.1f}%")
    c3.metric("Review Date", date.today().strftime("%d-%b-%Y"))

    st.divider()

    # 1️⃣ TABLE FIRST
    st.subheader("📄 Thesis Progress Structure (Complete View)")
    st.dataframe(
        style_table(df_display),
        use_container_width=True,
        hide_index=True
    )

    st.divider()

    # 2️⃣ CHARTS SECOND
    st.subheader("📊 Progress Charts")
    st.progress(min(overall_progress, 100) / 100)
    st.bar_chart(sec_df.set_index("section"))

    st.divider()

    # 3️⃣ WEEKLY SUMMARY LAST
    st.subheader("🧠 Weekly Summary")
    summary = weekly_summary_text()
    st.markdown(summary)

    st.download_button(
        "⬇ Download Weekly Summary (MD)",
        data=summary,
        file_name="weekly_summary.md",
        mime="text/markdown"
    )

    # PDFs
    weekly_pdf = generate_pdf_weekly_summary(summary)
    st.download_button(
        "⬇ Download Weekly Summary (PDF)",
        data=weekly_pdf,
        file_name="Weekly_Summary.pdf",
        mime="application/pdf"
    )

    supervisor_pdf = generate_supervisor_review_pdf(df_display, summary)
    st.download_button(
        "📄 Download Supervisor Review (PDF)",
        data=supervisor_pdf,
        file_name="Supervisor_Review.pdf",
        mime="application/pdf"
    )

# =====================================================
# TAB 2 — DOCUMENTS
# =====================================================
with tab2:
    st.subheader("📂 Research Documents Repository")

    categories = {
        "📁 Data": "Data",
        "📁 Literature Review": "Literature_Review",
        "📁 Model Results": "Model_Results",
        "📁 Publications": "Publications",
        "📁 Reports": "Reports",
        "📁 Thesis Report": "Thesis_Report"
    }

    ICONS = {
        ".pdf": "📄",
        ".xlsx": "📊",
        ".xls": "📊",
        ".csv": "📈",
        ".docx": "📝",
        ".zip": "📦"
    }



    doc_tabs = st.tabs(list(categories.keys()))
    comments = load_comments()

    for tab, (label, folder) in zip(doc_tabs, categories.items()):
        with tab:
            path = resolve_category_path(DOC_BASE, folder)

            if not path or not os.path.exists(path):
                files = []
            else:
                files = list_files_recursive(path)


            os.makedirs(path, exist_ok=True)

            # 1️⃣ Files inside category folder (if any)
            folder_files = list_files_recursive(path)

            # 2️⃣ ZIPs in root matching this category
            zip_key = folder.replace("_", "").lower()
            zip_files = list_zip_files_for_category(DOC_BASE, zip_key)

            files = folder_files + zip_files

            if not files:
                st.info("No files found in this category yet.")
                continue


            cols = st.columns(4)
            for i, fpath in enumerate(files):
                col = cols[i % 4]
                fname = os.path.basename(fpath)
                ext = os.path.splitext(fname)[1].lower()

                with col:
                    st.markdown(f"### {ICONS.get(ext,'📁')}")
                    st.caption(fname)

                    # Download
                    try:
                        with open(fpath, "rb") as f:
                            st.download_button(
                                "⬇ Download",
                                f,
                                fname,
                                key=f"dl_{folder}_{i}"
                            )
                    except Exception as e:
                        st.warning(f"Cannot read file: {e}")

                    # PDF Preview (inline)
                    if ext == ".pdf":
                        preview_key = f"preview_{folder}_{i}"
                        if preview_key not in st.session_state:
                            st.session_state[preview_key] = False

                        if st.button("👁 Preview", key=f"pv_{folder}_{i}"):
                            st.session_state[preview_key] = not st.session_state[preview_key]

                        if st.session_state[preview_key]:
                            render_pdf_inline(fpath, height=450)

                    # Supervisor comments
                    if is_supervisor:
                        comment_key = f"c_{folder}_{i}"
                        text = st.text_area(
                            "📝 Comment",
                            value=comments.get(fpath, ""),
                            key=comment_key,
                            height=100
                        )
                        if st.button("💾 Save", key=f"s_{folder}_{i}"):
                            comments[fpath] = text
                            save_comments(comments)
                            st.success("Saved")

# =====================================================
# FOOTER
# =====================================================
st.markdown("---")
st.caption("Prepared by: Muneeb Shehzad Butt | PhD Thesis Progress & Documentation System")
