package za.co.skillvaya.app;

import android.content.Context;
import android.graphics.*;
import android.graphics.drawable.Drawable;
import com.google.mlkit.vision.face.Face;
import com.google.mlkit.vision.face.FaceContour;
import java.util.HashMap;
import java.util.List;

/** Renders Chatmoji Lenses: colour, tracked expression, and effects behind / in front of the person. */
final class LensEngine {
    /** One processed camera frame. Coordinates are in frame pixels, image already upright and mirrored for selfies. */
    static final class Frame {
        Bitmap bg, person; FaceGeo face; int w, h;
    }
    /** Face placement: maps Chatmoji 64x64 design space onto the real face. */
    static final class FaceGeo {
        float mx, my, ux, uy, sx, sy, cx, cy, fw, fh;
        Matrix emojiMatrix(float bitmapSize) {
            float vx = -uy, vy = ux;
            float a = sx * ux, b = sy * vx, d = sx * uy, e = sy * vy;
            float c = mx - 32 * a - 28 * b, f = my - 32 * d - 28 * e;
            Matrix m = new Matrix(); m.setValues(new float[]{a, b, c, d, e, f, 0, 0, 1});
            m.preScale(64f / bitmapSize, 64f / bitmapSize); return m;
        }
        FaceGeo lerp(FaceGeo prev, float k) {
            if (prev == null) return this;
            FaceGeo g = new FaceGeo();
            g.mx = prev.mx + (mx - prev.mx) * k; g.my = prev.my + (my - prev.my) * k;
            float ux2 = prev.ux + (ux - prev.ux) * k, uy2 = prev.uy + (uy - prev.uy) * k, n = (float) Math.hypot(ux2, uy2);
            g.ux = n == 0 ? 1 : ux2 / n; g.uy = n == 0 ? 0 : uy2 / n;
            g.sx = prev.sx + (sx - prev.sx) * k; g.sy = prev.sy + (sy - prev.sy) * k;
            g.cx = prev.cx + (cx - prev.cx) * k; g.cy = prev.cy + (cy - prev.cy) * k;
            g.fw = prev.fw + (fw - prev.fw) * k; g.fh = prev.fh + (fh - prev.fh) * k; return g;
        }
    }

    private final Context ctx;
    private final HashMap<String, Bitmap> cache = new HashMap<>();
    private final Paint bmpPaint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
    private final Paint fx = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
    private final Paint glow = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint line = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Matrix tmp = new Matrix();

    LensEngine(Context c) { ctx = c; line.setStrokeCap(Paint.Cap.ROUND); }

    static FaceGeo geometry(Face f) {
        Rect bb = f.getBoundingBox(); FaceGeo g = new FaceGeo();
        PointF le = avg(f.getContour(FaceContour.LEFT_EYE)), re = avg(f.getContour(FaceContour.RIGHT_EYE));
        if (le == null || re == null) {
            le = new PointF(bb.left + bb.width() * 0.32f, bb.top + bb.height() * 0.42f);
            re = new PointF(bb.left + bb.width() * 0.68f, bb.top + bb.height() * 0.42f);
        }
        if (le.x > re.x) { PointF t = le; le = re; re = t; }
        g.mx = (le.x + re.x) / 2; g.my = (le.y + re.y) / 2;
        float dx = re.x - le.x, dy = re.y - le.y, d = (float) Math.hypot(dx, dy);
        if (d < 1) d = bb.width() * 0.4f;
        g.ux = dx / d; g.uy = dy / d; g.sx = d / 20f;
        PointF up = avg(f.getContour(FaceContour.UPPER_LIP_BOTTOM)), lo = avg(f.getContour(FaceContour.LOWER_LIP_TOP));
        float vx = -g.uy, vy = g.ux, md;
        if (up != null && lo != null) md = ((up.x + lo.x) / 2 - g.mx) * vx + ((up.y + lo.y) / 2 - g.my) * vy;
        else md = d * 0.95f;
        g.sy = Math.max(g.sx * 0.75f, Math.min(g.sx * 1.5f, md / 16f));
        g.cx = bb.exactCenterX(); g.cy = bb.exactCenterY(); g.fw = bb.width(); g.fh = bb.height();
        return g;
    }

    private static PointF avg(FaceContour c) {
        if (c == null) return null; List<PointF> p = c.getPoints(); if (p == null || p.isEmpty()) return null;
        float x = 0, y = 0; for (PointF q : p) { x += q.x; y += q.y; } return new PointF(x / p.size(), y / p.size());
    }

    Bitmap raster(String res, int size) {
        String key = res + "@" + size; Bitmap b = cache.get(key); if (b != null) return b;
        int id = ctx.getResources().getIdentifier(res, "drawable", ctx.getPackageName()); if (id == 0) return null;
        Drawable d = ctx.getResources().getDrawable(id, ctx.getTheme());
        b = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888); d.setBounds(0, 0, size, size); d.draw(new Canvas(b));
        cache.put(key, b); return b;
    }

    private static ColorFilter tintFilter(int tint, float k) {
        int r = Color.red(tint), g = Color.green(tint), b = Color.blue(tint);
        int mul = Color.rgb((int) (255 * (1 - k) + r * k), (int) (255 * (1 - k) + g * k), (int) (255 * (1 - k) + b * k));
        int add = Color.rgb((int) (r * k * 0.22f), (int) (g * k * 0.22f), (int) (b * k * 0.22f));
        return new LightingColorFilter(mul, add);
    }

    /** Draw the frame with up to two lenses (indexes into LensCatalog, -1 for none). */
    void render(Canvas c, Frame f, float vw, float vh, long t, int[] lenses) {
        if (f == null || f.bg == null) return;
        float s = Math.max(vw / f.w, vh / f.h);
        c.save(); c.translate((vw - f.w * s) / 2f, (vh - f.h * s) / 2f); c.scale(s, s);
        int faceLens = -1, sceneLens = -1, any = -1;
        for (int l : lenses) { if (l < 0) continue; if (any < 0) any = l; if (LensCatalog.KIND[l] < 2) { if (faceLens < 0) faceLens = l; } else if (sceneLens < 0) sceneLens = l; }
        int personTint = any < 0 ? 0 : LensCatalog.TINT[faceLens >= 0 ? faceLens : any];
        int bgTint = any < 0 ? 0 : LensCatalog.TINT[sceneLens >= 0 ? sceneLens : any];
        bmpPaint.setColorFilter(any < 0 ? null : tintFilter(bgTint, f.person != null ? 0.34f : 0.22f));
        c.drawBitmap(f.bg, 0, 0, bmpPaint);
        for (int l : lenses) if (l >= 0) effects(c, f, l, t, true);
        if (f.person != null) { bmpPaint.setColorFilter(any < 0 ? null : tintFilter(personTint, 0.16f)); c.drawBitmap(f.person, 0, 0, bmpPaint); }
        bmpPaint.setColorFilter(null);
        if (f.face != null) for (int l : lenses) if (l >= 0 && LensCatalog.KIND[l] < 2) faceLayer(c, f.face, l);
        for (int l : lenses) if (l >= 0) effects(c, f, l, t, false);
        c.restore();
    }

    private void faceLayer(Canvas c, FaceGeo g, int l) {
        int tint = LensCatalog.TINT[l];
        if (LensCatalog.KIND[l] == 0) {
            float rx = g.fw * 0.62f, ry = g.fh * 0.66f;
            glow.setShader(new RadialGradient(g.cx, g.cy, Math.max(rx, ry), new int[]{(tint & 0x00FFFFFF) | 0x50000000, (tint & 0x00FFFFFF) | 0x26000000, tint & 0x00FFFFFF}, new float[]{0f, 0.65f, 1f}, Shader.TileMode.CLAMP));
            c.drawOval(g.cx - rx, g.cy - ry, g.cx + rx, g.cy + ry, glow); glow.setShader(null);
            Bitmap b = raster("lf_" + LensCatalog.NAME[l], 512); if (b != null) c.drawBitmap(b, g.emojiMatrix(512), bmpPaint);
        } else {
            Bitmap b = raster("cm_" + LensCatalog.NAME[l], 512); if (b != null) c.drawBitmap(b, g.emojiMatrix(512), bmpPaint);
        }
    }

    private static float h(int i, int k) { double v = Math.sin(i * 12.9898 + k * 78.233) * 43758.5453; return (float) (v - Math.floor(v)); }
    private static float fr(float v) { return v - (float) Math.floor(v); }

    private void sprite(Canvas c, Bitmap b, float x, float y, float size, float rot, float alpha) {
        if (b == null || alpha <= 0.01f) return;
        tmp.reset(); float k = size / b.getWidth(); tmp.postTranslate(-b.getWidth() / 2f, -b.getHeight() / 2f); tmp.postScale(k, k); tmp.postRotate(rot); tmp.postTranslate(x, y);
        fx.setAlpha((int) (255 * Math.min(1f, alpha))); c.drawBitmap(b, tmp, fx);
    }

    private void effects(Canvas c, Frame f, int l, long t, boolean back) {
        String m = LensCatalog.FX[l]; Bitmap b = raster("cm_" + LensCatalog.SPRITE[l], 160); int tint = LensCatalog.TINT[l];
        float W = f.w, H = f.h, U = Math.min(W, H); FaceGeo g = f.face;
        float cx = g != null ? g.cx : W / 2f, cy = g != null ? g.cy : H * 0.42f, fw = g != null ? g.fw : U * 0.45f;
        switch (m) {
            case "rise": if (!back) return;
                for (int i = 0; i < 14; i++) { float p = fr(t / 5200f + h(i, 1)); float a = p < 0.12f ? p / 0.12f : p > 0.8f ? (1 - p) / 0.2f : 1;
                    sprite(c, b, h(i, 2) * W + (float) Math.sin(p * 6.28f + i) * U * 0.04f, H * (1.1f - p * 1.3f), U * (0.07f + 0.06f * h(i, 3)), (h(i, 4) - 0.5f) * 30, a); }
                return;
            case "fall": if (!back) return;
                for (int i = 0; i < 16; i++) { float p = fr(t / 6000f + h(i, 1));
                    sprite(c, b, h(i, 2) * W + (float) Math.sin(p * 9 + i) * U * 0.03f, H * (-0.1f + p * 1.25f), U * (0.06f + 0.05f * h(i, 3)), p * 360 * (h(i, 4) - 0.5f) * 2, 0.95f); }
                return;
            case "drift": if (!back) return;
                for (int i = 0; i < 6; i++) { float p = fr(t / 14000f + i / 6f + h(i, 1) * 0.1f);
                    sprite(c, b, W * (-0.2f + p * 1.4f), H * (0.08f + 0.6f * h(i, 2)), U * (0.12f + 0.1f * h(i, 3)), 0, 0.9f); }
                return;
            case "orbit":
                for (int i = 0; i < 6; i++) { double ang = 6.2832 * (t / 6000.0 + i / 6.0); float sn = (float) Math.sin(ang);
                    if ((sn < 0) != back) continue; float rx = fw * 0.95f, ry = rx * 0.3f;
                    sprite(c, b, cx + (float) Math.cos(ang) * rx, cy - fw * 0.1f + sn * ry, U * 0.1f * (0.8f + 0.3f * sn), 0, 0.75f + 0.25f * sn); }
                return;
            case "burst": if (back) return;
                for (int i = 0; i < 12; i++) { float p = fr(t / 2400f + h(i, 1) * 0.3f); double ang = 6.2832 * (i / 12.0 + h(i, 2) * 0.05);
                    float r = fw * 0.55f + p * U * 0.55f;
                    sprite(c, b, cx + (float) Math.cos(ang) * r, cy + (float) Math.sin(ang) * r, U * (0.05f + 0.06f * p), (float) Math.toDegrees(ang) * 0.2f, 1 - p); }
                return;
            case "rain": if (!back) return;
                line.setColor((tint & 0x00FFFFFF) | 0x8C000000); line.setStrokeWidth(U * 0.008f);
                for (int i = 0; i < 34; i++) { float p = fr(t / 900f + h(i, 1)); float x = h(i, 2) * W, y = H * (-0.1f + p * 1.2f); c.drawLine(x, y, x - U * 0.01f, y + U * 0.06f, line); }
                for (int i = 0; i < 3; i++) { float p = fr(t / 16000f + i / 3f); sprite(c, b, W * (-0.2f + p * 1.4f), H * (0.07f + 0.05f * i), U * 0.2f, 0, 0.95f); }
                return;
            case "corner": if (!back) return;
                { float size = U * 0.32f, x = W * 0.8f, y = H * 0.14f + (float) Math.sin(t / 900.0) * U * 0.015f;
                  glow.setShader(new RadialGradient(x, y, size * 1.2f, new int[]{(tint & 0x00FFFFFF) | 0x66000000, tint & 0x00FFFFFF}, null, Shader.TileMode.CLAMP));
                  c.drawCircle(x, y, size * 1.2f, glow); glow.setShader(null); sprite(c, b, x, y, size, (float) Math.sin(t / 1400.0) * 6, 1); }
                return;
            case "bottom": if (!back) return;
                for (int i = 0; i < 3; i++) { float p = fr(t / 9000f + i / 3f); sprite(c, b, W * (-0.3f + p * 1.6f), H * 0.86f + (float) Math.sin(t / 500.0 + i) * U * 0.01f, U * 0.22f, 0, 1); }
                return;
            case "launch": if (!back) return;
                { float p = fr(t / 4500f); if (p > 0.8f) return; float q = p / 0.8f;
                  float x = W * (0.12f + 0.76f * q), y = H * (1.1f - 1.35f * q);
                  glow.setShader(null); glow.setColor((tint & 0x00FFFFFF) | 0x99000000);
                  for (int k = 1; k <= 8; k++) { float qq = Math.max(0, q - k * 0.025f); glow.setAlpha((int) (150 * (1 - k / 9f)));
                      c.drawCircle(W * (0.12f + 0.76f * qq), H * (1.1f - 1.35f * qq) + U * 0.08f, U * 0.02f * (1 - k / 10f), glow); }
                  sprite(c, b, x, y, U * 0.3f, 0, 1); }
                return;
            case "hat": if (back) return;
                { float size = fw * 0.8f, rot = g != null ? (float) Math.toDegrees(Math.atan2(g.uy, g.ux)) : 0;
                  float top = g != null ? g.cy - g.fh * 0.5f : H * 0.15f;
                  float ox = g != null ? g.uy * size * 0.35f : 0, oy = g != null ? -g.ux * size * 0.35f : 0;
                  sprite(c, b, cx + ox, top + oy + (float) Math.sin(t / 700.0) * U * 0.01f, size, rot, 1); }
                return;
            default:
        }
    }
}
