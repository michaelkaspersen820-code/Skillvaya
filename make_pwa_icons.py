from PIL import Image, ImageDraw
from pathlib import Path
root=Path('.')
for size in (192,512):
    im=Image.new('RGBA',(size,size),(7,20,38,255)); d=ImageDraw.Draw(im)
    m=int(size*.045); rad=int(size*.21); d.rounded_rectangle((m,m,size-m,size-m),radius=rad,outline=(25,199,193,255),width=max(2,int(size*.02)))
    # geometric, legible Skillvaya mark
    x=int(size*.23); y=int(size*.25); w=int(size*.54); h=int(size*.12); gap=int(size*.09)
    d.rounded_rectangle((x,y,x+w,y+h),radius=int(size*.025),fill=(25,199,193,255))
    d.rounded_rectangle((x,y+gap+int(size*.04),x+w-int(size*.12),y+gap+int(size*.04)+h),radius=int(size*.025),fill=(25,199,193,255))
    d.rounded_rectangle((x,y+2*(gap+int(size*.04)),x+w-int(size*.25),y+2*(gap+int(size*.04))+h),radius=int(size*.025),fill=(25,199,193,255))
    cx=int(size*.72); cy=int(size*.72); rr=int(size*.145); d.ellipse((cx-rr,cy-rr,cx+rr,cy+rr),fill=(233,189,103,255))
    lw=max(3,int(size*.035)); d.line([(int(size*.65),cy),(int(size*.70),int(size*.77)),(int(size*.80),int(size*.65))],fill=(7,20,38,255),width=lw,joint='curve')
    im.convert('RGB').save(root/f'icon-{size}.png',optimize=True)
print('Created icon-192.png and icon-512.png')
