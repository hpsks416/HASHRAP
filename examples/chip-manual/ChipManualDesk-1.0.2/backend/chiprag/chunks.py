from __future__ import annotations
import hashlib
import re
from bs4 import BeautifulSoup

IGNORE = {"header", "footer", "page_header", "page_footer", "page_number", "index"}

def plain(value):
    if isinstance(value, list):
        return "\n".join(plain(v) for v in value)
    if not isinstance(value, str):
        return ""
    value = BeautifulSoup(value, "html.parser").get_text(" ", strip=True) if "<" in value else value.strip()
    # Content List text can contain Markdown escapes. Preserve register symbols for exact search.
    return re.sub(r"\\([_*`~\[\]#])", r"\1", value)

def block_text(b):
    keys = ("text", "table_caption", "table_body", "table_footnote", "image_caption",
            "image_footnote", "chart_caption", "content", "chart_footnote", "code_body", "list_items")
    return "\n".join(plain(b[k]) for k in keys if b.get(k))

def split_text(text, limit):
    while len(text) > limit:
        cut = max(text.rfind("\n", 0, limit), text.rfind(". ", 0, limit), text.rfind("; ", 0, limit))
        if cut < limit // 2:
            cut = limit
        yield text[:cut].strip()
        text = text[max(1,cut-100):].strip()
    if text.strip():
        yield text.strip()

def table_parts(b, limit):
    soup = BeautifulSoup(b.get("table_body", ""), "html.parser")
    rows = soup.find_all("tr")
    if not rows:
        return list(split_text(block_text(b), limit))
    header = plain(rows[0].get_text(" | ", strip=True))
    context = plain(b.get("table_caption", [])) + "\n" + header
    footnote = plain(b.get("table_footnote", []))
    pieces, current = [], []
    for row in rows[1:]:
        value = row.get_text(" | ", strip=True)
        if current and len(context) + sum(map(len,current)) + len(value) > limit:
            pieces.append(context + "\n" + "\n".join(current) + "\n" + footnote)
            current = []
        current.append(value)
    if current or not pieces:
        pieces.append(context + "\n" + "\n".join(current) + "\n" + footnote)
    return pieces

def make_chunks(blocks, manifest, limit=1400):
    ordered = sorted(enumerate(blocks), key=lambda t: (t[1]["page_idx"], t[0]))
    chunks, section, notes, printed = [], [], {}, {}
    for _, b in ordered:
        if b["type"] in ("page_footnote", "footnote"):
            notes.setdefault(b["page_idx"], []).append(block_text(b))
        if b["type"] == "page_number":
            printed[b["page_idx"]] = block_text(b)
    last_page = -1
    for ordinal, b in ordered:
        page = b["page_idx"]
        if page != last_page:
            # Bookmark changes act as a fallback; do not erase deeper parsed headings every page.
            marks = [x for x in manifest.get("bookmarks", []) if x["page"] == page]
            if marks:
                section = list(marks[-1]["path"])
            last_page = page
        if b["type"] in IGNORE:
            continue
        text = block_text(b)
        level = b.get("text_level", 0)
        if level and text:
            match = re.match(r"^(\d+(?:\.\d+)+)\b", text)
            if match:
                level = match.group(1).count(".") + 1
            level = max(1, min(int(level), 8))
            section = section[:level-1] + [text]
        if not text:
            if b["type"] in ("image", "chart", "equation"):
                text = f"[{b['type']} on PDF page {page+1}; inspect original page]"
            else:
                continue
        pieces = table_parts(b, limit) if b["type"] == "table" else list(split_text(text, limit))
        parent = hashlib.sha256((manifest["id"] + "|" + "/".join(section)).encode()).hexdigest()[:16]
        for part, body in enumerate(pieces):
            labels = manifest.get("page_labels", [])
            chunks.append({"id": f"{manifest['id']}-{ordinal}-{part}", "doc_id": manifest["id"],
                           "parent_id": parent, "section": list(section), "type": b["type"],
                           "text": body, "page": page+1,
                           "page_label": printed.get(page) or (labels[page] if page < len(labels) else None),
                           "bbox": b.get("bbox"), "block_ordinal": ordinal,
                           "page_notes": notes.get(page, []),
                           "source_pdf": manifest["source_pdf"], "asset_root": b.get("asset_root"),
                           "image_path": b.get("img_path"),
                           "chip": manifest["chip"], "revision": manifest["revision"],
                           "title": manifest["title"], "tier": manifest["tier"]})
    # Link likely continuation fragments; leave uncertain tables separate and keep original evidence.
    tables = [c for c in chunks if c["type"] == "table"]
    previous = None
    for c in tables:
        if previous and c["page"] - previous["page"] in (0,1) and c["parent_id"] == previous["parent_id"]:
            prev_number = re.search(r"\bTable\s+(\d+)\b", previous["text"], re.I)
            number = re.search(r"\bTable\s+(\d+)\b", c["text"], re.I)
            if c["block_ordinal"] == previous["block_ordinal"] or (prev_number and number and prev_number[1] == number[1]):
                c["related_previous"] = previous["id"]
                previous["related_next"] = c["id"]
        previous = c
    return chunks
