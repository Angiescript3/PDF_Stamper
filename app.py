# app.py
# Streamlit PDF text stamper (single-line text, font picker, color picker, exact preview, CLICK-TO-SET COORDS)
import io, zipfile
import streamlit as st
from PIL import Image, ImageDraw
import fitz  # PyMuPDF
from streamlit_image_coordinates import streamlit_image_coordinates

st.set_page_config(page_title="PDF Text Stamper (Demo)", layout="wide")

# ---- defaults via session_state ----
if "x" not in st.session_state: st.session_state.x = 35
if "y" not in st.session_state: st.session_state.y = 730

# ---- helpers ----
FONT_MAP = {
    "Helvetica": "helv",       # sans
    "Times (Roman)": "tiro",   # serif
    "Courier": "cour",         # mono
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
                if a > b:
                    a, b = b, a
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
    return sorted([p - 1 for p in out])  # convert to 0-based

def hex_to_rgb01(hex_color: str):
    hex_color = hex_color.lstrip("#")
    return (int(hex_color[0:2],16)/255.0,
            int(hex_color[2:4],16)/255.0,
            int(hex_color[4:6],16)/255.0)

def overlay_copy(src_doc, text: str, coords, pages,
                 font_size=12, fontname="helv", color_hex="#000000") -> bytes:
    x, y = coords
    y = y + font_size  # baseline offset (matches preview)
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

# ---- UI ----
st.title("PDF Text Stamper (Portfolio Demo)")
st.caption("Upload a PDF → choose pages → enter any text → choose font & color → click the preview to set coords → download.")

with st.sidebar:
    st.header("Stamp Settings")
    stamp_text = st.text_input("Stamp text", value="", placeholder="Type anything…")

    font_label = st.selectbox("Font", list(FONT_MAP.keys()), index=0)
    font_size = st.number_input("Font size", min_value=6, max_value=96, value=12, step=1)
    color_hex = st.color_picker("Text color", "#000000")

    pages_str = st.text_input("Pages (e.g., 1-3,5 — blank = all)", value="")

    # Bind to session_state so clicks update these values
    x = st.number_input("X", min_value=0, max_value=5000, value=st.session_state.x, step=1, key="x_num")
    y = st.number_input("Y", min_value=0, max_value=5000, value=st.session_state.y, step=1, key="y_num")

    # Keep session_state.x/y in sync with manual edits
    st.session_state.x = int(x)
    st.session_state.y = int(y)

    click_to_set = st.checkbox("Click to set coords on preview", value=True)
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
        font_alias = FONT_MAP[font_label]

        # Exact stamped preview image
        preview_img = render_stamped_preview(
            doc, pages[0], stamp_text, (st.session_state.x, st.session_state.y),
            font_size=font_size, fontname=font_alias, color_hex=color_hex, zoom=zoom
        )

        # Optional crosshair overlay for placement guidance
        img_to_show = preview_img
        if show_crosshair:
            img_to_show = preview_img.copy()
            draw = ImageDraw.Draw(img_to_show)
            cx = int(st.session_state.x * zoom)
            cy = int((st.session_state.y + font_size) * zoom)
            L = crosshair_len
            draw.line((cx - L, cy, cx + L, cy), fill="#FF0000", width=1)
            draw.line((cx, cy - L, cx, cy + L), fill="#FF0000", width=1)

        if click_to_set:
            st.caption("Tip: Click where you want the **baseline** of the text to start.")
            result = streamlit_image_coordinates(img_to_show, key="coord_clicker")
            if result is not None and "x" in result and "y" in result:
                # Convert from preview pixels -> PDF coords (baseline)
                click_x_px, click_y_px = result["x"], result["y"]
                new_x = int(round(click_x_px / zoom))
                new_y = int(round(click_y_px / zoom) - font_size)  # inverse of +font_size baseline shift

                # Clamp to non-negative
                new_x = max(0, new_x)
                new_y = max(0, new_y)

                # Update session + widgets
                st.session_state.x = new_x
                st.session_state.y = new_y
                st.session_state.x_num = new_x
                st.session_state.y_num = new_y

                st.success(f"Set coords from click → X={new_x}, Y={new_y}")
        else:
            st.image(img_to_show, caption=f"Page {pages[0]+1} / {total_pages}", use_container_width=True)

    except Exception as e:
        st.warning(f"Preview failed: {e}")

with col2:
    st.subheader("Details")
    st.write(f"**Pages selected:** {', '.join(str(p+1) for p in pages)}")
    st.write(f"**Text:** `{stamp_text or '(none)'}`")
    st.write(f"**Font:** {font_label}  •  **Size:** {font_size}")
    st.write(f"**Color:** {color_hex}")
    st.write(f"**Coords:** ({st.session_state.x}, {st.session_state.y})  (baseline anchor)")

    if st.button("Export"):
        if not stamp_text.strip():
            st.error("Please enter stamp text.")
        else:
            try:
                font_alias = FONT_MAP[font_label]
                coords = (st.session_state.x, st.session_state.y)
                if mode.startswith("Group"):
                    stamped = overlay_copy(doc, stamp_text, coords, pages, font_size, font_alias, color_hex)
                    st.download_button(
                        "Download stamped PDF",
                        data=stamped,
                        file_name="stamped_group.pdf",
                        mime="application/pdf",
                    )
                else:
                    files = overlay_per_page(doc, stamp_text, coords, pages, font_size, font_alias, color_hex)
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
