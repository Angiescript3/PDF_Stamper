# app.py
# Streamlit PDF text stamper (single-line text, font picker, color picker, crosshair preview)
# pip: streamlit, pymupdf, pillow
import io, zipfile
import streamlit as st
from PIL import Image, ImageDraw
import fitz  # PyMuPDF

st.set_page_config(page_title="PDF Text Stamper (Demo)", layout="wide")

# ---- helpers ----
FONT_MAP = {
    "Helvetica": "helv",      # sans
    "Times": "times",         # serif
    "Courier": "cour",        # mono
}

def parse_pages(text: str, total: int):
    if not text.strip():
        return list(range(total))
    out = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            try:
                a, b = int(a), int(b)
                out.update(range(max(1, a), min(total, b) + 1))
            except ValueError:
                pass
        else:
            try:
                n = int(part)
                if 1 <= n <= total:
                    out.add(n)
            except ValueError:
                pass
    return sorted([p - 1 for p in out])

def render_page(doc, page_idx: int, zoom=1.25) -> Image.Image:
    page = doc[page_idx]
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

def hex_to_rgb01(hex_color: str):
    """#RRGGBB -> (r,g,b) floats in 0..1 for PyMuPDF"""
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    return (r, g, b)

def overlay_copy(src_doc, text: str, coords, pages, font_size=12, fontname="helv", color_hex="#000000") -> bytes:
    x, y = coords
    y = y + font_size  # small offset to match desktop behavior
    color = hex_to_rgb01(color_hex)
    ndoc = fitz.open()
    for p in pages:
        ndoc.insert_pdf(src_doc, from_page=p, to_page=p)
        if text.strip():
            ndoc[-1].insert_text(
                (x, y),
                text,
                fontsize=font_size,
                fontname=fontname,
                color=color,     # floats (0..1)
                overlay=True
            )
    out_buf = io.BytesIO()
    ndoc.save(out_buf)
    ndoc.close()
    out_buf.seek(0)
    return out_buf.read()

def overlay_per_page(src_doc, text: str, coords, pages, font_size=12, fontname="helv", color_hex="#000000"):
    files = {}
    for p in pages:
        data = overlay_copy(src_doc, text, coords, [p], font_size, fontname, color_hex)
        files[f"stamped_p{p+1}.pdf"] = data
    return files

# ---- UI ----
st.title("PDF Text Stamper (Portfolio Demo)")
st.caption("Upload a PDF → choose pages → enter any text → choose font & color → download stamped copy.")

with st.sidebar:
    st.header("Stamp Settings")
    stamp_text = st.text_input("Stamp text", value="", placeholder="Type anything…")
    font_label = st.selectbox("Font", list(FONT_MAP.keys()), index=0)
    font_size = st.number_input("Font size", min_value=6, max_value=96, value=12, step=1)
    color_hex = st.color_picker("Text color", "#000000")
    pages_str = st.text_input("Pages (e.g., 1-3,5 — blank = all)", value="")
    x = st.number_input("X", min_value=0, max_value=5000, value=105, step=1)
    y = st.number_input("Y", min_value=0, max_value=5000, value=72, step=1)
    show_crosshair = st.checkbox("Show crosshair marker on preview", value=True)
    crosshair_len = st.slider("Crosshair length (px, preview only)", 10, 200, 40)
    mode = st.radio("Export mode", ["Group (one PDF)", "Per-page (ZIP)"])

uploaded = st.file_uploader("Upload a PDF", type=["pdf"])
if not uploaded:
    st.info("Upload a PDF to begin.")
    st.stop()

# Open PDF from memory
pdf_bytes = uploaded.read()
try:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
except Exception as e:
    st.error(f"Could not read PDF: {e}")
    st.stop()

total_pages = len(doc)
pages = parse_pages(pages_str, total_pages)
if not pages:
    pages = list(range(total_pages))

col1, col2 = st.columns([3, 2])

with col1:
    st.subheader("Preview (first selected page)")
    try:
        zoom = 1.25
        preview_img = render_page(doc, pages[0], zoom=zoom)
        img = preview_img.copy()
        draw = ImageDraw.Draw(img)

        # approximate preview text at scaled coords
        if stamp_text.strip():
            # Pillow accepts hex for fill
            draw.text((x * zoom, (y + font_size) * zoom), stamp_text, fill=color_hex)

        # crosshair to show (x, y + font_size) anchor approx
        if show_crosshair:
            cx = int(x * zoom)
            cy = int((y + font_size) * zoom)
            L = crosshair_len
            draw.line((cx - L, cy, cx + L, cy), fill="#FF0000", width=1)
            draw.line((cx, cy - L, cx, cy + L), fill="#FF0000", width=1)

        st.image(img, caption=f"Page {pages[0]+1} / {total_pages}", use_container_width=True)
    except Exception as e:
        st.warning(f"Preview failed: {e}")

with col2:
    st.subheader("Details")
    st.write(f"**Pages selected:** {', '.join(str(p+1) for p in pages)}")
    st.write(f"**Text:** `{stamp_text or '(none)'}`")
    st.write(f"**Font:** {font_label}  •  **Size:** {font_size}")
    st.write(f"**Color:** {color_hex}")
    st.write(f"**Coords:** ({x}, {y})  (anchor ≈ at crosshair)")

    if st.button("Export"):
        if not stamp_text.strip():
            st.error("Please enter stamp text.")
        else:
            try:
                fontname = FONT_MAP[font_label]
                if mode.startswith("Group"):
                    stamped = overlay_copy(doc, stamp_text, (x, y), pages, font_size, fontname, color_hex)
                    st.download_button(
                        "Download stamped PDF",
                        data=stamped,
                        file_name="stamped_group.pdf",
                        mime="application/pdf",
                    )
                else:
                    files = overlay_per_page(doc, stamp_text, (x, y), pages, font_size, fontname, color_hex)
                    zip_buf = io.BytesIO()
                    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                        for name, data in files.items():
                            zf.writestr(name, data)
                    zip_buf.seek(0)
                    st.download_button(
                        "Download ZIP (per-page PDFs)",
                        data=zip_buf,
                        file_name="stamped_per_page.zip",
                        mime="application/zip",
                    )
                st.success("Export ready below 👇")
            except Exception as e:
                st.error(f"Export failed: {e}")

doc.close()
