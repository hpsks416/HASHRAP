"""One isolated local MinerU parse. No remote client or API key is used."""
import sys
from pathlib import Path
from .runtime import prepare, write_json

def main():
    prepare()
    from mineru.parser import parse
    from mineru.parser.writer import FileBasedDataWriter
    from mineru.render import render, RenderFormat
    pdf, target, tier, pages = sys.argv[1:]
    out = Path(target)
    out.mkdir(parents=True, exist_ok=True)
    options = {"tier": tier, "page_range": pages}
    if tier == "flash":
        options["ocr_mode"] = "txt"
    result = parse(pdf, **options)
    result.save(FileBasedDataWriter(str(out)))
    # Render the saved model so image references point to real local assets, not base64 data.
    from mineru.parser import ParseResult
    saved = ParseResult.from_json((out / "middle_json.json").read_text(encoding="utf-8"))
    blocks = render(saved.middle_json, RenderFormat.CONTENT_LIST)
    write_json(out / "blocks.json", blocks)
    write_json(out / "pages.json", [p.page_idx for p in result.pages])

if __name__ == "__main__":
    main()
