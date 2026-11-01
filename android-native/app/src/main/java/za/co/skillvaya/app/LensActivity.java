package za.co.skillvaya.app;

import android.Manifest;
import android.content.ContentValues;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.*;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.MediaStore;
import android.util.Size;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.widget.*;
import androidx.activity.ComponentActivity;
import androidx.camera.core.*;
import androidx.camera.core.resolutionselector.ResolutionSelector;
import androidx.camera.core.resolutionselector.ResolutionStrategy;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.core.content.ContextCompat;
import com.google.android.gms.tasks.Tasks;
import com.google.common.util.concurrent.ListenableFuture;
import com.google.mlkit.vision.common.InputImage;
import com.google.mlkit.vision.face.*;
import com.google.mlkit.vision.segmentation.*;
import com.google.mlkit.vision.segmentation.selfie.SelfieSegmenterOptions;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Future Chat camera with Chatmoji Lenses. Returns the saved photo URI as the result data. */
public class LensActivity extends ComponentActivity {
    static final String EXTRA_TITLE = "title";
    private static final int TEAL = 0xFF1ED6C8, NAVY = 0xFF071426, WHITE = 0xFFFFFFFF, MUTED = 0xFF9FB8D0;

    private final int[] slot = {-1, -1};
    private int activeSlot = 0, cat = 0;
    private boolean front = true, busy = false;
    private volatile LensEngine.Frame latest;
    private LensEngine.FaceGeo smooth; private long faceSeen;
    private Bitmap lastMask; private int frameNo;
    private LensEngine engine; private LensView view;
    private ExecutorService worker; private FaceDetector faces; private Segmenter seg, segStill;
    private ImageCapture capture; private ProcessCameraProvider provider;
    private LinearLayout slotRow, strip; private HorizontalScrollView stripScroll; private TextView hint;
    private FrameLayout review; private ImageView reviewImg; private Bitmap shot;
    private SharedPreferences prefs; private final long start = System.currentTimeMillis();

    private int dp(float v) { return Math.round(v * getResources().getDisplayMetrics().density); }

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        Window w = getWindow(); w.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON); w.setStatusBarColor(NAVY); w.setNavigationBarColor(NAVY);
        prefs = getSharedPreferences("future_chat_local", MODE_PRIVATE);
        engine = new LensEngine(this); worker = Executors.newSingleThreadExecutor();
        faces = FaceDetection.getClient(new FaceDetectorOptions.Builder().setPerformanceMode(FaceDetectorOptions.PERFORMANCE_MODE_FAST).setContourMode(FaceDetectorOptions.CONTOUR_MODE_ALL).build());
        seg = Segmentation.getClient(new SelfieSegmenterOptions.Builder().setDetectorMode(SelfieSegmenterOptions.STREAM_MODE).build());
        int last = LensCatalog.index(prefs.getString("lens_last", "")); slot[0] = last;
        build();
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) startCamera();
        else requestPermissions(new String[]{Manifest.permission.CAMERA}, 701);
    }

    @Override public void onRequestPermissionsResult(int code, String[] p, int[] r) {
        super.onRequestPermissionsResult(code, p, r);
        if (code == 701) { if (r.length > 0 && r[0] == PackageManager.PERMISSION_GRANTED) startCamera(); else { Toast.makeText(this, "Camera permission is needed for Chatmoji Lenses", Toast.LENGTH_LONG).show(); finish(); } }
    }

    @Override protected void onDestroy() { super.onDestroy(); worker.shutdown(); faces.close(); seg.close(); if (segStill != null) segStill.close(); }

    // ---------- camera ----------
    private void startCamera() {
        ListenableFuture<ProcessCameraProvider> fut = ProcessCameraProvider.getInstance(this);
        fut.addListener(() -> { try { provider = fut.get(); bind(); } catch (Exception e) { Toast.makeText(this, "Camera is not available", Toast.LENGTH_LONG).show(); finish(); } }, ContextCompat.getMainExecutor(this));
    }

    private void bind() {
        if (provider == null) return;
        provider.unbindAll(); smooth = null; lastMask = null;
        ResolutionSelector rs = new ResolutionSelector.Builder().setResolutionStrategy(new ResolutionStrategy(new Size(640, 480), ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER)).build();
        ImageAnalysis an = new ImageAnalysis.Builder().setResolutionSelector(rs).setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888).build();
        an.setAnalyzer(worker, this::analyze);
        capture = new ImageCapture.Builder().setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY).build();
        CameraSelector sel = front ? CameraSelector.DEFAULT_FRONT_CAMERA : CameraSelector.DEFAULT_BACK_CAMERA;
        try { provider.bindToLifecycle(this, sel, an, capture); }
        catch (Exception e) { try { capture = null; provider.unbindAll(); provider.bindToLifecycle(this, sel, an); } catch (Exception e2) { Toast.makeText(this, "Camera is not available", Toast.LENGTH_LONG).show(); } }
    }

    private Bitmap upright(Bitmap src, int rot, boolean mirror) {
        Matrix m = new Matrix(); m.postRotate(rot); if (mirror) m.postScale(-1, 1);
        return Bitmap.createBitmap(src, 0, 0, src.getWidth(), src.getHeight(), m, true);
    }

    private void analyze(ImageProxy img) {
        try {
            Bitmap up = upright(img.toBitmap(), img.getImageInfo().getRotationDegrees(), front);
            LensEngine.Frame f = process(up, faces, seg, (frameNo++ % 2) == 0, true);
            latest = f;
        } catch (Exception ignored) {
        } finally { img.close(); }
    }

    /** Runs face tracking and person separation on an upright bitmap. */
    private LensEngine.Frame process(Bitmap up, FaceDetector fd, Segmenter sg, boolean runSeg, boolean live) throws Exception {
        LensEngine.Frame f = new LensEngine.Frame(); f.bg = up; f.w = up.getWidth(); f.h = up.getHeight();
        boolean needFace = false, needSeg = false;
        for (int l : slot) if (l >= 0) { needSeg = true; if (LensCatalog.KIND[l] < 2 || "orbit".equals(LensCatalog.FX[l]) || "burst".equals(LensCatalog.FX[l]) || "hat".equals(LensCatalog.FX[l])) needFace = true; }
        InputImage in = InputImage.fromBitmap(up, 0);
        if (needFace) {
            List<Face> list = Tasks.await(fd.process(in));
            Face best = null; for (Face x : list) if (best == null || x.getBoundingBox().width() > best.getBoundingBox().width()) best = x;
            if (best != null) { LensEngine.FaceGeo g = LensEngine.geometry(best); if (live) { smooth = g.lerp(smooth, 0.55f); faceSeen = System.currentTimeMillis(); f.face = smooth; } else f.face = g; }
            else if (live && smooth != null && System.currentTimeMillis() - faceSeen < 350) f.face = smooth;
        }
        if (needSeg) {
            Bitmap mask = live ? lastMask : null;
            if (runSeg || mask == null || mask.getWidth() != f.w) { SegmentationMask sm = Tasks.await(sg.process(in)); mask = maskBitmap(sm, f.w, f.h); if (live) lastMask = mask; }
            if (mask != null) {
                Bitmap person = Bitmap.createBitmap(f.w, f.h, Bitmap.Config.ARGB_8888); Canvas pc = new Canvas(person);
                pc.drawBitmap(up, 0, 0, null); Paint p = new Paint(Paint.FILTER_BITMAP_FLAG); p.setXfermode(new PorterDuffXfermode(PorterDuff.Mode.DST_IN));
                pc.drawBitmap(mask, null, new Rect(0, 0, f.w, f.h), p); f.person = person;
            }
        }
        return f;
    }

    private static Bitmap maskBitmap(SegmentationMask sm, int w, int h) {
        int mw = sm.getWidth(), mh = sm.getHeight(); ByteBuffer buf = sm.getBuffer(); buf.rewind();
        int[] px = new int[mw * mh];
        for (int i = 0; i < px.length; i++) { float c = buf.getFloat(); float a = (c - 0.35f) / 0.35f; a = a < 0 ? 0 : a > 1 ? 1 : a; px[i] = ((int) (a * 255)) << 24; }
        return Bitmap.createBitmap(px, mw, mh, Bitmap.Config.ARGB_8888);
    }

    // ---------- capture ----------
    private void takeShot() {
        if (busy) return; busy = true; hint.setText("Capturing…");
        final long t = System.currentTimeMillis() - start;
        if (capture == null) { renderLatest(t); return; }
        capture.takePicture(worker, new ImageCapture.OnImageCapturedCallback() {
            @Override public void onCaptureSuccess(ImageProxy img) {
                try {
                    Bitmap up = upright(img.toBitmap(), img.getImageInfo().getRotationDegrees(), front); img.close();
                    float k = 1440f / Math.max(up.getWidth(), up.getHeight()); if (k < 1) up = Bitmap.createScaledBitmap(up, Math.round(up.getWidth() * k), Math.round(up.getHeight() * k), true);
                    if (segStill == null) segStill = Segmentation.getClient(new SelfieSegmenterOptions.Builder().setDetectorMode(SelfieSegmenterOptions.SINGLE_IMAGE_MODE).build());
                    LensEngine.Frame f = process(up, faces, segStill, true, false);
                    Bitmap out = Bitmap.createBitmap(f.w, f.h, Bitmap.Config.ARGB_8888);
                    engine.render(new Canvas(out), f, f.w, f.h, t, slot.clone());
                    runOnUiThread(() -> showReview(out));
                } catch (Exception e) { img.close(); renderLatest(t); }
            }
            @Override public void onError(ImageCaptureException e) { renderLatest(t); }
        });
    }

    private void renderLatest(long t) {
        LensEngine.Frame f = latest;
        if (f == null) { runOnUiThread(() -> { busy = false; hint.setText("Camera is still starting"); }); return; }
        Bitmap out = Bitmap.createBitmap(f.w, f.h, Bitmap.Config.ARGB_8888); engine.render(new Canvas(out), f, f.w, f.h, t, slot.clone());
        runOnUiThread(() -> showReview(out));
    }

    private void showReview(Bitmap b) { shot = b; reviewImg.setImageBitmap(b); review.setVisibility(View.VISIBLE); busy = false; updateHint(); }

    private void usePhoto() {
        if (shot == null) return;
        try {
            java.io.File f = new java.io.File(getCacheDir(), "lens_" + System.currentTimeMillis() + ".jpg"); Uri u = Uri.fromFile(f);
            try (OutputStream os = new java.io.FileOutputStream(f)) { shot.compress(Bitmap.CompressFormat.JPEG, 92, os); }
            setResult(RESULT_OK, new Intent().setData(u)); finish();
        } catch (Exception e) { Toast.makeText(this, "Could not save the photo", Toast.LENGTH_LONG).show(); }
    }

    // ---------- UI ----------
    private GradientDrawable round(int color, float r) { GradientDrawable g = new GradientDrawable(); g.setColor(color); g.setCornerRadius(dp(r)); return g; }
    private TextView label(String s, float sp, int color, boolean bold) { TextView t = new TextView(this); t.setText(s); t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp); t.setTextColor(color); if (bold) t.setTypeface(Typeface.DEFAULT_BOLD); return t; }
    private ImageView icon(int res, int size) { ImageView v = new ImageView(this); v.setImageResource(res); v.setLayoutParams(new LinearLayout.LayoutParams(dp(size), dp(size))); return v; }
    private FrameLayout roundBtn(int res, int bg, int tint, int size, int iconSize, String desc, View.OnClickListener l) {
        FrameLayout f = new FrameLayout(this); GradientDrawable g = new GradientDrawable(); g.setShape(GradientDrawable.OVAL); g.setColor(bg); f.setBackground(g);
        ImageView i = new ImageView(this); i.setImageResource(res); i.setColorFilter(tint); f.addView(i, new FrameLayout.LayoutParams(dp(iconSize), dp(iconSize), Gravity.CENTER));
        f.setContentDescription(desc); f.setOnClickListener(l); f.setLayoutParams(new LinearLayout.LayoutParams(dp(size), dp(size))); return f;
    }

    private void build() {
        FrameLayout root = new FrameLayout(this); root.setBackgroundColor(NAVY);
        view = new LensView(); root.addView(view, new FrameLayout.LayoutParams(-1, -1));

        LinearLayout top = new LinearLayout(this); top.setGravity(Gravity.CENTER_VERTICAL); top.setPadding(dp(12), dp(12), dp(12), dp(24));
        top.setBackground(new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, new int[]{0xCC071426, 0x00071426}));
        top.addView(roundBtn(R.drawable.ic_close, 0x33000000, WHITE, 44, 22, "Close camera", v -> finish()));
        LinearLayout tt = new LinearLayout(this); tt.setOrientation(LinearLayout.VERTICAL); tt.setPadding(dp(12), 0, 0, 0);
        String title = getIntent().getStringExtra(EXTRA_TITLE); tt.addView(label(title == null ? "Chatmoji Lenses" : title, 18, WHITE, true));
        hint = label("", 12, MUTED, false); tt.addView(hint);
        top.addView(tt, new LinearLayout.LayoutParams(0, -2, 1));
        top.addView(roundBtn(R.drawable.ic_flip, 0x33000000, WHITE, 44, 22, "Switch camera", v -> { front = !front; bind(); }));
        root.addView(top, new FrameLayout.LayoutParams(-1, -2, Gravity.TOP));

        LinearLayout panel = new LinearLayout(this); panel.setOrientation(LinearLayout.VERTICAL); panel.setPadding(0, dp(28), 0, dp(18));
        panel.setBackground(new GradientDrawable(GradientDrawable.Orientation.BOTTOM_TOP, new int[]{0xF2071426, 0xB3071426, 0x00071426}));
        slotRow = new LinearLayout(this); slotRow.setGravity(Gravity.CENTER); panel.addView(slotRow, new LinearLayout.LayoutParams(-1, -2));

        HorizontalScrollView cats = new HorizontalScrollView(this); cats.setHorizontalScrollBarEnabled(false);
        final LinearLayout catRow = new LinearLayout(this); catRow.setPadding(dp(12), 0, dp(12), 0);
        for (int i = 0; i < FcCatalog.CM_CATS.length; i++) {
            final int ix = i; TextView c = label(FcCatalog.CM_CATS[i], 13, WHITE, true); c.setPadding(dp(14), dp(7), dp(14), dp(7));
            c.setOnClickListener(v -> { cat = ix; for (int k = 0; k < catRow.getChildCount(); k++) styleChip((TextView) catRow.getChildAt(k), k == ix); fillStrip(); });
            styleChip(c, i == 0); LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, -2); lp.setMargins(0, 0, dp(8), 0); catRow.addView(c, lp);
        }
        cats.addView(catRow); LinearLayout.LayoutParams cl = new LinearLayout.LayoutParams(-1, -2); cl.setMargins(0, dp(12), 0, dp(8)); panel.addView(cats, cl);

        stripScroll = new HorizontalScrollView(this); stripScroll.setHorizontalScrollBarEnabled(false);
        strip = new LinearLayout(this); strip.setPadding(dp(12), dp(2), dp(12), dp(2)); stripScroll.addView(strip); panel.addView(stripScroll, new LinearLayout.LayoutParams(-1, -2));

        FrameLayout shutter = new FrameLayout(this); GradientDrawable ring = new GradientDrawable(); ring.setShape(GradientDrawable.OVAL); ring.setColor(0x33FFFFFF); ring.setStroke(dp(4), WHITE); shutter.setBackground(ring);
        View dot = new View(this); GradientDrawable dg = new GradientDrawable(GradientDrawable.Orientation.TL_BR, new int[]{0xFF35EBDC, 0xFF12A8D0}); dg.setShape(GradientDrawable.OVAL); dot.setBackground(dg);
        shutter.addView(dot, new FrameLayout.LayoutParams(dp(58), dp(58), Gravity.CENTER)); shutter.setContentDescription("Take photo"); shutter.setOnClickListener(v -> takeShot());
        LinearLayout.LayoutParams sl = new LinearLayout.LayoutParams(dp(78), dp(78)); sl.gravity = Gravity.CENTER_HORIZONTAL; sl.setMargins(0, dp(14), 0, 0); panel.addView(shutter, sl);
        root.addView(panel, new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM));

        review = new FrameLayout(this); review.setBackgroundColor(NAVY); review.setVisibility(View.GONE); review.setClickable(true);
        reviewImg = new ImageView(this); reviewImg.setScaleType(ImageView.ScaleType.FIT_CENTER); review.addView(reviewImg, new FrameLayout.LayoutParams(-1, -1));
        LinearLayout acts = new LinearLayout(this); acts.setGravity(Gravity.CENTER); acts.setPadding(dp(18), dp(18), dp(18), dp(28));
        acts.setBackground(new GradientDrawable(GradientDrawable.Orientation.BOTTOM_TOP, new int[]{0xF2071426, 0x00071426}));
        TextView retake = label("Retake", 16, WHITE, true); retake.setGravity(Gravity.CENTER); retake.setBackground(round(0x33FFFFFF, 26)); retake.setOnClickListener(v -> { review.setVisibility(View.GONE); shot = null; });
        TextView use = label("Use photo", 16, 0xFF05283A, true); use.setGravity(Gravity.CENTER); use.setBackground(round(TEAL, 26)); use.setOnClickListener(v -> usePhoto());
        LinearLayout.LayoutParams bl = new LinearLayout.LayoutParams(0, dp(52), 1); bl.setMargins(dp(6), 0, dp(6), 0); acts.addView(retake, bl);
        LinearLayout.LayoutParams bl2 = new LinearLayout.LayoutParams(0, dp(52), 1); bl2.setMargins(dp(6), 0, dp(6), 0); acts.addView(use, bl2);
        review.addView(acts, new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM));
        root.addView(review, new FrameLayout.LayoutParams(-1, -1));

        setContentView(root);
        if (slot[0] >= 0) { int c = catOf(slot[0]); if (c >= 0) { cat = c; for (int k = 0; k < catRow.getChildCount(); k++) styleChip((TextView) catRow.getChildAt(k), k == c); } }
        fillStrip(); refreshSlots();
    }

    private int catOf(int lens) { String n = LensCatalog.NAME[lens]; for (int i = 0; i < FcCatalog.CM.length; i++) for (String s : FcCatalog.CM[i]) if (s.equals(n)) return i; return -1; }
    private void styleChip(TextView c, boolean on) { c.setBackground(round(on ? TEAL : 0x33FFFFFF, 16)); c.setTextColor(on ? 0xFF05283A : WHITE); }

    private void fillStrip() {
        strip.removeAllViews();
        strip.addView(lensCell(-1));
        for (String n : FcCatalog.CM[cat]) { int ix = LensCatalog.index(n); if (ix >= 0) strip.addView(lensCell(ix)); }
        stripScroll.scrollTo(0, 0);
    }

    private View lensCell(final int ix) {
        boolean on = slot[activeSlot] == ix;
        FrameLayout f = new FrameLayout(this);
        GradientDrawable g = new GradientDrawable(); g.setShape(GradientDrawable.OVAL); g.setColor(0x40000000); if (on) g.setStroke(dp(3), TEAL); else g.setStroke(dp(1), 0x44FFFFFF); f.setBackground(g);
        ImageView i = new ImageView(this);
        if (ix < 0) { i.setImageResource(R.drawable.ic_close); i.setColorFilter(WHITE); f.addView(i, new FrameLayout.LayoutParams(dp(22), dp(22), Gravity.CENTER)); f.setContentDescription("No lens"); }
        else { i.setImageResource(getResources().getIdentifier("cm_" + LensCatalog.NAME[ix], "drawable", getPackageName())); f.addView(i, new FrameLayout.LayoutParams(dp(42), dp(42), Gravity.CENTER)); f.setContentDescription(LensCatalog.NAME[ix].replace('_', ' ') + " lens"); }
        f.setOnClickListener(v -> pick(ix));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(60), dp(60)); lp.setMargins(dp(4), 0, dp(4), 0); f.setLayoutParams(lp); return f;
    }

    private void pick(int ix) {
        int other = slot[1 - activeSlot];
        if (ix >= 0 && ix == other) { Toast.makeText(this, "That lens is already in the other slot", Toast.LENGTH_SHORT).show(); return; }
        slot[activeSlot] = ix;
        if (activeSlot == 0 && ix >= 0) prefs.edit().putString("lens_last", LensCatalog.NAME[ix]).apply();
        if (activeSlot == 1 && ix < 0) activeSlot = 0;
        if (activeSlot == 0 && ix < 0 && slot[1] >= 0) { slot[0] = slot[1]; slot[1] = -1; }
        refreshSlots(); fillStrip();
    }

    private String pretty(int ix) { String n = LensCatalog.NAME[ix].replace('_', ' '); return Character.toUpperCase(n.charAt(0)) + n.substring(1); }

    private void refreshSlots() {
        slotRow.removeAllViews();
        slotRow.addView(slotChip(0));
        if (slot[0] >= 0) {
            TextView plus = label("+", 22, WHITE, true); plus.setGravity(Gravity.CENTER);
            LinearLayout.LayoutParams pl = new LinearLayout.LayoutParams(dp(28), dp(44)); slotRow.addView(plus, pl);
            slotRow.addView(slotChip(1));
        }
        updateHint();
    }

    private View slotChip(final int s) {
        LinearLayout c = new LinearLayout(this); c.setGravity(Gravity.CENTER_VERTICAL); c.setPadding(dp(8), dp(6), dp(14), dp(6));
        GradientDrawable g = round(0x66071426, 24); g.setStroke(dp(activeSlot == s ? 2 : 1), activeSlot == s ? TEAL : 0x44FFFFFF); c.setBackground(g);
        int ix = slot[s];
        if (ix >= 0) {
            ImageView i = icon(getResources().getIdentifier("cm_" + LensCatalog.NAME[ix], "drawable", getPackageName()), 30); c.addView(i);
            TextView t = label(pretty(ix), 14, WHITE, true); t.setPadding(dp(8), 0, 0, 0); c.addView(t);
            if (s == 1) { ImageView x = icon(R.drawable.ic_close, 18); x.setColorFilter(MUTED); x.setPadding(dp(4), 0, 0, 0); x.setContentDescription("Remove second lens"); x.setOnClickListener(v -> { slot[1] = -1; activeSlot = 0; refreshSlots(); fillStrip(); }); LinearLayout.LayoutParams xl = new LinearLayout.LayoutParams(dp(26), dp(18)); c.addView(x, xl); }
        } else {
            ImageView i = icon(R.drawable.ic_add, 22); i.setColorFilter(TEAL); c.addView(i);
            c.addView(label(s == 0 ? "Pick a lens" : "Add a 2nd lens", 14, WHITE, true));
        }
        c.setContentDescription(s == 0 ? "First lens" : "Second lens");
        c.setOnClickListener(v -> { activeSlot = s; refreshSlots(); fillStrip(); });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, dp(44)); c.setLayoutParams(lp); return c;
    }

    private void updateHint() {
        if (hint == null) return;
        if (slot[0] < 0) hint.setText("Choose a Chatmoji to turn into a lens");
        else if (activeSlot == 1 && slot[1] < 0) hint.setText("Now pick a second lens to combine");
        else if (slot[1] >= 0) hint.setText(pretty(slot[0]) + " + " + pretty(slot[1]));
        else hint.setText(pretty(slot[0]) + "  ·  tap + to combine two");
    }

    private final class LensView extends View {
        private final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        LensView() { super(LensActivity.this); p.setColor(MUTED); p.setTextAlign(Paint.Align.CENTER); p.setTextSize(dp(15)); }
        @Override protected void onDraw(Canvas c) {
            LensEngine.Frame f = latest;
            if (f == null) c.drawText("Starting camera…", getWidth() / 2f, getHeight() / 2f, p);
            else engine.render(c, f, getWidth(), getHeight(), System.currentTimeMillis() - start, slot);
            postInvalidateOnAnimation();
        }
    }
}
