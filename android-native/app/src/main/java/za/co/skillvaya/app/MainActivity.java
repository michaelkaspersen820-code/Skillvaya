package za.co.skillvaya.app;
import android.app.Activity;
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
import android.os.Environment;
import android.webkit.URLUtil;
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
        webView.setWebViewClient(new WebViewClient()); webView.setWebChromeClient(new WebChromeClient());
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
    private void copyAsset(String name) throws Exception {
        File out=new File(getFilesDir(),name); if(out.exists()&&out.length()>0)return;
        try(InputStream in=getAssets().open(name);FileOutputStream fos=new FileOutputStream(out)){
            byte[] buffer=new byte[8192];int n;while((n=in.read(buffer))>0)fos.write(buffer,0,n);
        }
    }
    @Override public void onBackPressed(){if(webView!=null&&webView.canGoBack())webView.goBack();else super.onBackPressed();}
}
