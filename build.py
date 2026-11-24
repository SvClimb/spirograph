# Builds deploy/index.html (full document) and share/spirograph.html (same, with mp4-muxer inlined) from spirograph-app.html.
# Usage: python3 build.py   (run after every change to spirograph-app.html)
import sys, pathlib
root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parent
src = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else root / "spirograph-app.html"
muxer_src = pathlib.Path(sys.argv[3]) if len(sys.argv) > 3 else root / "vendor/mp4-muxer.js"
app = src.read_text()
assert app.startswith("<title>Спинограф</title>\n")
doc = ('<!doctype html>\n<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
       '<title>Спинограф</title></head><body>\n' + app[len("<title>Спинограф</title>\n"):].rstrip("\n") + "\n\n</body></html>\n")
tag = '<script src="https://cdn.jsdelivr.net/npm/mp4-muxer@5.1.3/build/mp4-muxer.js"></script>'
assert doc.count(tag) == 1
muxer = muxer_src.read_text()
for d in ("deploy", "share"): (root / d).mkdir(exist_ok=True)
(root / "deploy/index.html").write_text(doc)
(root / "share/spirograph.html").write_text(doc.replace(tag, "<script>\n" + muxer.rstrip("\n") + "\n</script>"))
