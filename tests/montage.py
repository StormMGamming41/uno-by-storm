import sys
from PIL import Image, ImageDraw
tag = sys.argv[1]; names = sys.argv[2].split(","); out = sys.argv[3]
ims = [Image.open(f"shots/{tag}_{n}.png") for n in names]
h = int(sys.argv[4]) if len(sys.argv) > 4 else 760
ims = [i.resize((int(i.width * h / i.height), h)) for i in ims]
W = sum(i.width for i in ims) + 10 * (len(ims) + 1)
m = Image.new("RGB", (W, h + 30), (40, 40, 40)); x = 10
d = ImageDraw.Draw(m)
for n, i in zip(names, ims):
    m.paste(i, (x, 24)); d.text((x, 6), n, fill=(255, 255, 255)); x += i.width + 10
m.save(out)
