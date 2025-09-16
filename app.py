# app.py
# Streamlit PDF text stamper — simple UX:
# - Preview is always clickable: one click sets X/Y (baseline) and refreshes preview once.
# - No "capture" mode. No extra confirm buttons. Just one "Update Preview" button.
import io, zipfile
import streamlit as st
from PIL import Image, ImageDraw
import fitz  # PyMuPDF
from streamlit_image_coordinates import streamlit_image_coordinates

st.set_page_config(page_title="PDF Text Stamper (Demo)", layout="wide")

# ---------- session defaults ----------
def ss_default(key, val):
    if key not in st.session_state:
        st.session_state[key] = val

ss_default("x", 35)                  # your preferred defaults
ss_default("y", 730)
ss_default("stamp_text", "")
ss_default("font_label", "Helvetica")
ss_default("font_size", 12)
ss_default("color_hex", "#000000")
ss_default("pages_str", "")
ss_default("refresh_preview", True)  # render once at start
ss_default("_last_preview", None)

# ---------- helpers ----------
FONT_MAP = {
    "Helvetica": "helv",
    "Times (Roman)": "tiro",
    "Courier": "cour",
}

def parse_pages(text: str, total: int):
    if not text or not text.strip():
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
                if a > b: a, b = b, a
                a = max(1, a); b = min(total, b)
                out.update(range(a, b + 1))
            except ValueError:
                continue
        else:
            try:
                n = int(part)
                if 1 <= n <= total:
                    out.add(n)
            except ValueError:
                continue
    return sorted([p - 1 for p in out])

def hex_to_rgb01(hex_color: str):
    hex_color = hex_color.lstrip("#")
    return (int(hex_color[0:2],16)/255.0,
            int(hex_color[2:4],16)/255.0,
            int(hex_color[4:6],16)/255.0)

def overlay_copy(src_doc, text: str, coords, pages,
                 font_size=12, fontname="helv", color_hex="#000000") -> bytes:
    x, y = coords
    y = y + font_size  # baseline offset (export + preview match)
    color = hex_to_rgb01(color_hex)

    ndoc = fitz.open()
    try:
        font_alias = ndoc.insert_font(fontname=fontname)
    except Exception:
        try:
            font_alias = ndoc.insert_font(fontname="helv")
        except Exception:
            font_alias = None

    for p in pages:
        ndoc.insert_pdf(src_doc, from_page=p, to_page=p)
        if text.strip():
            page = ndoc[-1]
            kwargs = dict(fontsize=font_size, color=color, overlay=True)
            if font_alias:
                kwargs["fontname"] = font_alias
            page.insert_text((x, y), text, **kwargs)

    out_buf = io.BytesIO()
    ndoc.save(out_buf)
    ndoc.close()
    out_buf.seek(0)
    return out_buf.read()

def overlay_per_page(src_doc, text: str, coords, pages,
                     font_size=12, fontname="helv", color_hex="#000000"):
    files = {}
    for p in pages:
        data = overlay_copy(src_doc, text, coords, [p], font_size, fontname, color_hex)
        files[f"stamped_p{p+1}.pdf"] = data
    return files

def render_stamped_preview(src_doc, page_index: int, text: str, coords,
                           font_size=12, fontname="helv", color_hex="#000000", zoom=1.25) -> Image.Image:
    """Exact preview: stamp via PyMuPDF in-memory, then rasterize."""
    x, y = coords
    y_pdf = y + font_size
    color = hex_to_rgb01(color_hex)

    ndoc = fitz.open()
    ndoc.insert_pdf(src_doc, from_page=page_index, to_page=page_index)

    try:
        font_alias = ndoc.insert_font(fontname=fontname)
    except Exception:
        try:
            font_alias = ndoc.insert_font(fontname="helv")
        except Exception:
            font_alias = None

    page = ndoc[-1]
    if text.strip():
        kwargs = dict(fontsize=font_size, color=color, overlay=True)
        if font_alias:
            kwargs["fontname"] = font_alias
        page.insert_text((x, y_pdf), text, **kwargs)

    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    ndoc.close()
    return img

# ---------- sidebar (no auto preview updates) ----------
with st.sidebar:
    st.header("Stamp Settings")

    st.session_state.stamp_text = st.text_input(
        "Stamp text", value=st.session_state.stamp_text, placeholder="Type anything…"
    )
    st.session_state.font_label = st.selectbox(
        "Font", list(FONT_MAP.keys()), index=list(FONT_MAP.keys()).index(st.session_state.font_label)
    )
    st.session_state.font_size = int(st.number_input(
        "Font size", min_value=6, max_value=96, value=st.session_state.font_size, step=1
    ))
    st.session_state.color_hex = st.color_picker("Text color", st.session_state.color_hex)

    st.session_state.pages_str = st.text_input(
        "Pages (e.g., 1-3,5 — blank = all)", value=st.session_state.pages_str
    )

    # X/Y are editable but do not trigger preview refresh until user clicks Update Preview
    st.session_state.x = int(st.number_input("X", min_value=0, max_value=5000, value=st.session_state.x, step=1))
    st.session_state.y = int(st.number_input("Y", min_value=0, max_value=5000, value=st.session_state.y, step=1))

    if st.button("Update Preview"):
        st.session_state.refresh_preview = True

# ---------- file upload ----------
uploaded = st.file_uploader("Upload a PDF", type=["pdf"])
if not uploaded:
    st.info("Upload a PDF to begin.")
    st.stop()

# Open PDF
pdf_bytes = uploaded.read()
try:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
except Exception as e:
    st.error(f"Could not read PDF: {e}")
    st.stop()

total_pages = len(doc)
pages = parse_pages(st.session_state.pages_str, total_pages)
if not pages:
    pages = list(range(total_pages))

# ---------- preview + click-to-set (single rerun per click) ----------
col1, col2 = st.columns([3, 2])

with col1:
    st.subheader("Preview (click to set coords)")
    try:
        zoom = 1.25
        font_alias = FONT_MAP[st.session_state.font_label]

        # Render (or reuse) preview
        if st.session_state.refresh_preview or st.session_state._last_preview is None:
            base_img = render_stamped_preview(
                doc, pages[0], st.session_state.stamp_text, (st.session_state.x, st.session_state.y),
                font_size=st.session_state.font_size, fontname=font_alias,
                color_hex=st.session_state.color_hex, zoom=zoom
            )
            st.session_state._last_preview = base_img
            st.session_state.refresh_preview = False

        # Draw a small crosshair at current coords (purely visual)
        img_to_show = st.session_state._last_preview.copy()
        draw = ImageDraw.Draw(img_to_show)
        cx = int(st.session_state.x * zoom)
        cy = int((st.session_state.y + st.session_state.font_size) * zoom)
        L = 30
        draw.line((cx - L, cy, cx + L, cy), fill="#FF0000", width=1)
        draw.line((cx, cy - L, cx, cy + L), fill="#FF0000", width=1)

        st.caption("Click where you want the **baseline** of the text to start (one click = one update).")
        result = streamlit_image_coordinates(img_to_show, key="coord_clicker_simple")

        # If a new click arrives, update coords and refresh preview once
        if result and "x" in result and "y" in result:
            new_x = max(0, int(round(result["x"] / zoom)))
            new_y = max(0, int(round(result["y"] / zoom) - st.session_state.font_size))  # inverse baseline shift
            # Only change if it's a real move, to avoid tiny jitters
            if new_x != st.session_state.x or new_y != st.session_state.y:
                st.session_state.x = new_x
                st.session_state.y = new_y
                st.session_state.refresh_preview = True
                st.rerun()  # single rerun to show the new preview

    except Exception as e:
        st.warning(f"Preview failed: {e}")

with col2:
    st.subheader("Details")
    st.write(f"**Pages selected:** {', '.join(str(p+1) for p in pages)}")
    st.write(f"**Text:** `{st.session_state.stamp_text or '(none)'}`")
    st.write(f"**Font:** {st.session_state.font_label}  •  **Size:** {st.session_state.font_size}")
    st.write(f"**Color:** {st.session_state.color_hex}")
    st.write(f"**Coords:** ({st.session_state.x}, {st.session_state.y})  (baseline anchor)")
    st.caption("Preview only updates on **click** or when you press **Update Preview**.")

    # Export mode selector lives here to avoid extra reruns while editing settings
    export_mode = st.radio("Export mode", ["Group (one PDF)", "Per-page (ZIP)"], index=0)
    if st.button("Export"):
        if not st.session_state.stamp_text.strip():
            st.error("Please enter stamp text.")
        else:
            try:
                font_alias = FONT_MAP[st.session_state.font_label]
                coords = (st.session_state.x, st.session_state.y)
                if export_mode.startswith("Group"):
                    stamped = overlay_copy(doc, st.session_state.stamp_text, coords, pages,
                                           st.session_state.font_size, font_alias, st.session_state.color_hex)
                    st.download_button("Download stamped PDF", data=stamped,
                                       file_name="stamped_group.pdf", mime="application/pdf")
                else:
                    files = overlay_per_page(doc, st.session_state.stamp_text, coords, pages,
                                             st.session_state.font_size, font_alias, st.session_state.color_hex)
                    zip_buf = io.BytesIO()
                    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                        for name, data in files.items():
                            zf.writestr(name, data)
                    zip_buf.seek(0)
                    st.download_button("Download ZIP (per-page PDFs)", data=zip_buf,
                                       file_name="stamped_per_page.zip", mime="application/zip")
                st.success("Export ready below 👇")
            except Exception as e:
                st.error(f"Export failed: {e}")

doc.close()
