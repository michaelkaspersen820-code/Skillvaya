package za.co.skillvaya.app;
import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.graphics.Color;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.DownloadListener;
import android.webkit.CookieManager;
import android.app.DownloadManager;
import android.net.Uri;
import android.provider.MediaStore;
import androidx.core.content.FileProvider;
import android.os.Environment;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient.FileChooserParams;
import android.widget.Toast;
import android.widget.FrameLayout;
import android.view.ViewGroup;
import android.view.Gravity;
import android.widget.TextView;
import java.io.File;
import java.io.InputStream;
import java.io.FileOutputStream;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

public class MainActivity extends Activity {
    private WebView webView;
    private TextView status;
    private ValueCallback<Uri[]> filePathCallback;
    private Uri cameraOutputUri;
    private static final int FILE_CHOOSER_REQUEST = 7341;
    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.rgb(7,20,38));
        getWindow().setNavigationBarColor(Color.rgb(7,20,38));
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.rgb(7,20,38));
        webView = new WebView(this);
        status = new TextView(this);
        status.setText("Starting Skillvaya…"); status.setTextColor(Color.WHITE);
        status.setTextSize(18); status.setGravity(Gravity.CENTER);
        root.addView(webView, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        root.addView(status, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root); webView.setVisibility(WebView.GONE);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true); settings.setDomStorageEnabled(true); settings.setUserAgentString(settings.getUserAgentString() + " SkillvayaNative");
        settings.setDatabaseEnabled(true); settings.setSupportZoom(false);
        // Always fetch the current hosted app instead of retaining stale WebView assets.
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        webView.clearCache(true);
        settings.setAllowFileAccess(false); settings.setAllowContentAccess(true);
        webView.setDownloadListener((url, userAgent, contentDisposition, mimeType, contentLength) -> {
            try {
                DownloadManager manager = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
                DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
                String fileName = URLUtil.guessFileName(url, contentDisposition, mimeType);
                if (fileName == null || fileName.trim().isEmpty()) fileName = "Skillvaya.apk";
                request.setTitle(fileName);
                request.setDescription("Downloading from Skillvaya");
                request.setMimeType(mimeType != null ? mimeType : "application/octet-stream");
                request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                request.setAllowedOverMetered(true);
                request.setAllowedOverRoaming(true);
                request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, fileName);
                request.addRequestHeader("User-Agent", userAgent != null ? userAgent : "SkillvayaNative");
                String cookie = CookieManager.getInstance().getCookie(url);
                if (cookie != null && !cookie.isEmpty()) request.addRequestHeader("Cookie", cookie);
                manager.enqueue(request);
                Toast.makeText(MainActivity.this, "Download started. Open the APK and confirm installation; Android will register Skillvaya as an installed app.", Toast.LENGTH_LONG).show();
            } catch (Exception e) {
                Toast.makeText(MainActivity.this, "Could not start download. Open Skillvaya in Chrome and try again.", Toast.LENGTH_LONG).show();
            }
        });
        webView.setWebViewClient(new WebViewClient());
        webView.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (filePathCallback != null) filePathCallback.onReceiveValue(null);
                filePathCallback = callback;
                cameraOutputUri = null;
                try {
                    if (params.isCaptureEnabled()) {
                        Intent camera = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
                        if (camera.resolveActivity(getPackageManager()) == null) throw new IllegalStateException("No camera app is available.");
                        File cameraDir = new File(getCacheDir(), "camera");
                        if (!cameraDir.exists() && !cameraDir.mkdirs()) throw new IllegalStateException("Could not create camera storage.");
                        File photo = File.createTempFile("skillvaya_profile_", ".jpg", cameraDir);
                        cameraOutputUri = FileProvider.getUriForFile(MainActivity.this, getPackageName() + ".fileprovider", photo);
                        camera.putExtra(MediaStore.EXTRA_OUTPUT, cameraOutputUri);
                        camera.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
                        startActivityForResult(camera, FILE_CHOOSER_REQUEST);
                        return true;
                    }
                    Intent intent;
                    try { intent = params.createIntent(); }
                    catch (Exception ignored) { intent = null; }
                    if (intent == null) {
                        intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                        intent.addCategory(Intent.CATEGORY_OPENABLE);
                        intent.setType("*/*");
                    }
                    if (params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE) intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                    startActivityForResult(intent, FILE_CHOOSER_REQUEST);
                    return true;
                } catch (Exception e) {
                    if (filePathCallback != null) filePathCallback.onReceiveValue(null);
                    filePathCallback = null;
                    cameraOutputUri = null;
                    Toast.makeText(MainActivity.this, "Could not open the camera or file picker: " + e.getMessage(), Toast.LENGTH_LONG).show();
                    return true;
                }
            }
        });
        try {
            if (BuildConfig.PUBLIC_URL != null && !BuildConfig.PUBLIC_URL.trim().isEmpty()) {
                status.setText("Connecting to Skillvaya…");
                webView.setWebViewClient(new WebViewClient() {
                    @Override public void onPageFinished(WebView view, String url) {
                        status.setVisibility(TextView.GONE); webView.setVisibility(ViewGroup.VISIBLE);
                    }
                    @Override public boolean shouldOverrideUrlLoading(WebView view, String url) {
                        return false;
                    }
                });
                String baseUrl = BuildConfig.PUBLIC_URL.trim().replaceAll("/+$", "");
                // Open the public directory first. The standalone /login gateway hides the
                // customer category list, so account actions should be entered from the app UI.
                webView.loadUrl(baseUrl + "/?native_refresh=" + System.currentTimeMillis());
                return;
            }
            for (String name : new String[]{"website.html","icon-192.png","icon-512.png","sv-logo.jpeg"}) copyAsset(name);
            if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
            new Thread(() -> {
                try { Python.getInstance().getModule("android_server").callAttr("start_server", getFilesDir().getAbsolutePath(), new File(getFilesDir(),"skillvaya.sqlite3").getAbsolutePath()); }
                catch (Exception e) { runOnUiThread(() -> status.setText("Skillvaya could not start. Please reinstall or contact support.")); }
            }, "SkillvayaPythonBootstrap").start();
            new Thread(() -> {
                for (int i=0; i<120; i++) {
                    try {
                        java.net.HttpURLConnection c=(java.net.HttpURLConnection)new java.net.URL("http://127.0.0.1:8878/healthz").openConnection();
                        c.setConnectTimeout(500); c.setReadTimeout(500); int code=c.getResponseCode(); c.disconnect();
                        if (code==200) { runOnUiThread(() -> { status.setVisibility(TextView.GONE); webView.setVisibility(WebView.VISIBLE); webView.loadUrl("http://127.0.0.1:8878/login"); }); return; }
                    } catch (Exception ignored) {}
                    try { Thread.sleep(250); } catch (InterruptedException ignored) { return; }
                }
                runOnUiThread(() -> status.setText("Skillvaya startup timed out. Close and reopen the app."));
            }, "SkillvayaHealthCheck").start();
        } catch (Exception e) { status.setText("Skillvaya setup failed. Please reinstall the app."); }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == FILE_CHOOSER_REQUEST) {
            if (filePathCallback == null) return;
            Uri[] results = null;
            if (resultCode == Activity.RESULT_OK) {
                if (cameraOutputUri != null) {
                    results = new Uri[]{cameraOutputUri};
                } else if (data != null && data.getClipData() != null) {
                    int count = data.getClipData().getItemCount();
                    results = new Uri[count];
                    for (int i = 0; i < count; i++) results[i] = data.getClipData().getItemAt(i).getUri();
                } else if (data != null && data.getData() != null) {
                    results = new Uri[]{data.getData()};
                }
            }
            filePathCallback.onReceiveValue(results);
            filePathCallback = null;
            cameraOutputUri = null;
        }
    }
    private void copyAsset(String name) throws Exception {
        File out=new File(getFilesDir(),name); if(out.exists()&&out.length()>0)return;
        try(InputStream in=getAssets().open(name);FileOutputStream fos=new FileOutputStream(out)){
            byte[] buffer=new byte[8192];int n;while((n=in.read(buffer))>0)fos.write(buffer,0,n);
        }
    }
    @Override public void onBackPressed(){if(webView!=null&&webView.canGoBack())webView.goBack();else super.onBackPressed();}
}
