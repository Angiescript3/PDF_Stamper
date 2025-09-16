# app.py
# Streamlit PDF overlay demo (PyMuPDF + Pillow)
# pip: streamlit, pymupdf, pillow
import io, re, zipfile
import streamlit as st
from PIL import Image
import fitz  # PyMuPDF

st.set_page_config(page_title="PDF Event Export Demo", layout="wide")

# ---------- helpers ----------
def parse_pages(text: str, total: int):
    """Return a sorted list of 0-based page indices from a string like '1-3,5'."""
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
    return sorted([p - 1 for p in out])  # to 0-based

def render_page(doc, page_idx: int, zoom=1.25) -> Image.Image:
    page = doc[page_idx]
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

def overlay_copy(src_doc, text: str, coords, pages, font_size=12) -> bytes:
    """Return bytes of a new multi-page PDF with overlay text on selected pages."""
    x, y = coords
    y = y + font_size  # match your original small offset
    ndoc = fitz.open()
    for p in pages:
        ndoc.insert_pdf(src_doc, from_page=p, to_page=p)
        if text.strip():
            ndoc[-1].insert_text((x, y), text, fontsize=font_size, color=(0, 0, 0), overlay=True)
    out_buf = io.BytesIO()
    ndoc.save(out_buf)
    ndoc.close()
    out_buf.seek(0)
    return out_buf.read()

def overlay_per_page(src_doc, text: str, coords, pages, font_size=12):
    """Return dict {filename: bytes} for one PDF per selected page."""
    files = {}
    for p in pages:
        data = overlay_copy(src_doc, text, coords, [p], font_size)
        files[f"stamped_p{p+1}.pdf"] = data
    return files

# ---------- UI ----------
st.title("PDF Event Export (Portfolio Demo)")

with st.sidebar:
    st.header("Stamp Settings")
    event_id = st.text_input("Event ID", value="")
    banner_id = st.text_input("Banner ID", value="1000")
    label_text = f"{event_id}_{banner_id}" if event_id else ""
    pages_str = st.text_input("Pages (e.g., 1-3,5)", value="")
    x = st.number_input("X", min_value=0, max_value=5000, value=105, step=1)
    y = st.number_input("Y", min_value=0, max_value=5000, value=72, step=1)
    font_size = st.number_input("Font size", min_value=6, max_value=72, value=12, step=1)
    mode = st.radio("Export mode", ["Group (one PDF)", "Per-page (ZIP)"])
    st.caption("Tip: leave Pages blank to stamp **all** pages.")

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
        preview_img = render_page(doc, pages[0], zoom=1.25)
        # Draw a simple preview overlay using Pillow (visual only)
        if label_text.strip():
            img = preview_img.copy()
            # Light annotation to show approximate position (no fonts loaded; this is just a marker)
            import PIL.ImageDraw as ImageDraw
            draw = ImageDraw.Draw(img)
            draw.text((x * 1.25, (y + font_size) * 1.25), label_text, fill="red")
            st.image(img, caption=f"Page {pages[0]+1} / {total_pages}", use_column_width=True)
        else:
            st.image(preview_img, caption=f"Page {pages[0]+1} / {total_pages}", use_column_width=True)
    except Exception as e:
        st.warning(f"Preview failed: {e}")

with col2:
    st.subheader("Details")
    st.write(f"**Pages selected:** {', '.join(str(p+1) for p in pages)}")
    st.write(f"**Label:** `{label_text or '(none)'}` at **({x},{y})** size **{font_size}**")

    do_export = st.button("Export")
    if do_export:
        if not label_text.strip():
            st.error("Please enter an Event ID (label cannot be empty).")
        else:
            try:
                if mode.startswith("Group"):
                    stamped = overlay_copy(doc, label_text, (x, y), pages, font_size)
                    st.download_button(
                        "Download stamped PDF",
                        data=stamped,
                        file_name="stamped_group.pdf",
                        mime="application/pdf",
                    )
                else:
                    files = overlay_per_page(doc, label_text, (x, y), pages, font_size)
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

# Clean up
doc.close()
