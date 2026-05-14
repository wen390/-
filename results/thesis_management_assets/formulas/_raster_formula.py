from pathlib import Path
import sys
import pypdfium2 as pdfium
from PIL import Image, ImageChops

pdf_path = Path(sys.argv[1])
png_path = Path(sys.argv[2])
doc = pdfium.PdfDocument(str(pdf_path))
page = doc[0]
bitmap = page.render(scale=4).to_pil().convert("RGB")
bg = Image.new("RGB", bitmap.size, "white")
diff = ImageChops.difference(bitmap, bg)
bbox = diff.getbbox()
if bbox:
    left, top, right, bottom = bbox
    pad = 28
    crop = bitmap.crop((max(0, left-pad), max(0, top-pad), min(bitmap.width, right+pad), min(bitmap.height, bottom+pad)))
else:
    crop = bitmap
crop.save(png_path)