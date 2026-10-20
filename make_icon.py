from PIL import Image, ImageDraw
p=r"C:\Users\user\Documents\Codex\Skillvaya\skillvaya.ico"
im=Image.new("RGBA",(256,256),(16,35,63,255)); d=ImageDraw.Draw(im)
d.rounded_rectangle((24,24,232,232),radius=42,fill=(16,35,63,255),outline=(117,183,255,255),width=6)
d.rounded_rectangle((53,57,202,82),radius=8,fill=(117,183,255,255))
d.rounded_rectangle((53,99,167,124),radius=8,fill=(117,183,255,255))
d.rounded_rectangle((53,141,139,166),radius=8,fill=(117,183,255,255))
d.ellipse((133,131,222,220),fill=(35,101,216,255))
d.line((157,175,174,191,201,158),fill="white",width=10)
im.save(p,format="ICO",sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])
print(p)
