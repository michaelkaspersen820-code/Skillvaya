package za.co.skillvaya.app;
import android.app.Activity;
import android.content.Intent;
import android.content.Context;
import android.content.ActivityNotFoundException;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.RecognitionListener;
import android.os.SystemClock;
import android.webkit.JavascriptInterface;
import java.util.ArrayList;
import java.util.Locale;
import android.content.pm.PackageManager;
import android.Manifest;
import android.content.ClipData;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.graphics.Color;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebChromeClient;
import android.webkit.PermissionRequest;
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
import android.widget.LinearLayout;
import java.io.File;
import java.io.InputStream;
import java.io.FileOutputStream;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

public class MainActivity extends Activity {
    private SpeechRecognizer nativeSpeechRecognizer;
    private boolean nativeVoiceActive = false;
    private long lastVoiceStartAt = 0L;
    private static final int NATIVE_VOICE_PERMISSION_REQUEST = 7343;
    private NativeVoiceBridge nativeVoiceBridge;
    private PlayBillingBridge playBillingBridge;
    public void runBillingJavascript(String script) {
        if (webView != null) runOnUiThread(() -> webView.evaluateJavascript(script, null));
    }
    public final class NativeVoiceBridge {
        @JavascriptInterface public void start() { runOnUiThread(() -> startNativeVoice()); }
        @JavascriptInterface public void stop() { runOnUiThread(() -> stopNativeVoice(true)); }
    }
    private void voiceJs(String script) {
        if (webView != null) runOnUiThread(() -> webView.evaluateJavascript(script, null));
    }
    private void stopNativeVoice(boolean notifyPage) {
        nativeVoiceActive = false;
        if (nativeSpeechRecognizer != null) {
            try { nativeSpeechRecognizer.cancel(); } catch (Exception ignored) {}
            try { nativeSpeechRecognizer.destroy(); } catch (Exception ignored) {}
            nativeSpeechRecognizer = null;
        }
        if (notifyPage) voiceJs("window.svNativeVoiceEnded && window.svNativeVoiceEnded(true)");
    }
    private void scheduleNativeVoiceRestart() {
        if (!nativeVoiceActive) return;
        loadingHandler.postDelayed(() -> {
            if (!nativeVoiceActive || isFinishing() || isDestroyed()) return;
            try {
                if (nativeSpeechRecognizer != null) {
                    Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
                    intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
                    // Prefer broadly available English resources; the previous device-default en-ZA
                    // locale was reported missing by the installed recognition service.
                    intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-US");
                    intent.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
                    intent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
                    intent.putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, false);
                    // Ask compatible Android speech services for punctuation and text formatting.
                    if (android.os.Build.VERSION.SDK_INT >= 33) intent.putExtra("android.speech.extra.ENABLE_FORMATTING", "quality");
                    intent.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 180000L);
                    intent.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 180000L);
                    nativeSpeechRecognizer.startListening(intent);
                }
            } catch (Exception e) {
                nativeVoiceActive = false;
                voiceJs("window.svNativeVoiceEnded && window.svNativeVoiceEnded(false)");
                voiceJs("window.svNativeVoiceError && window.svNativeVoiceError('Android could not continue listening. Check the speech service and try again.')");
            }
        }, 350);
    }
    private void startNativeVoice() {
        if (nativeVoiceActive) return;
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, NATIVE_VOICE_PERMISSION_REQUEST);
            return;
        }
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            voiceJs("window.svNativeVoiceError && window.svNativeVoiceError('Speech recognition is not available on this device.')");
            return;
        }
        try {
            nativeVoiceActive = true;
            nativeSpeechRecognizer = SpeechRecognizer.createSpeechRecognizer(this);
            nativeSpeechRecognizer.setRecognitionListener(new RecognitionListener() {
                @Override public void onReadyForSpeech(Bundle params) { voiceJs("window.svNativeVoiceReady && window.svNativeVoiceReady()"); }
                @Override public void onBeginningOfSpeech() {}
                @Override public void onRmsChanged(float rmsdB) {}
                @Override public void onBufferReceived(byte[] buffer) {}
                @Override public void onEndOfSpeech() {}
                @Override public void onError(int error) {
                    if (!nativeVoiceActive) return;
                    if (error == SpeechRecognizer.ERROR_NO_MATCH || error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT) {
                        scheduleNativeVoiceRestart();
                        return;
                    }
                    nativeVoiceActive = false;
                    if (nativeSpeechRecognizer != null) { try { nativeSpeechRecognizer.destroy(); } catch (Exception ignored) {} nativeSpeechRecognizer = null; }
                    voiceJs("window.svNativeVoiceEnded && window.svNativeVoiceEnded(false)");
                    voiceJs("window.svNativeVoiceError && window.svNativeVoiceError(" + org.json.JSONObject.quote("Android speech recognition stopped (error " + error + "). Check that English speech recognition is available, then tap the microphone to try again.") + ")");
                }
                @Override public void onResults(Bundle results) {
                    if (!nativeVoiceActive) return;
                    ArrayList<String> matches = results == null ? null : results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                    if (matches != null && !matches.isEmpty()) voiceJs("window.svNativeVoiceResult && window.svNativeVoiceResult(" + org.json.JSONObject.quote(matches.get(0)) + ",true)");
                    scheduleNativeVoiceRestart();
                }
                @Override public void onPartialResults(Bundle partialResults) {
                    if (!nativeVoiceActive || partialResults == null) return;
                    ArrayList<String> matches = partialResults.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                    if (matches != null && !matches.isEmpty()) voiceJs("window.svNativeVoiceResult && window.svNativeVoiceResult(" + org.json.JSONObject.quote(matches.get(0)) + ",false)");
                }
                @Override public void onEvent(int eventType, Bundle params) {}
            });
            Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
            intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
            intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-US");
            intent.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
            intent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
            intent.putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, false);
                    // Ask compatible Android speech services for punctuation and text formatting.
                    if (android.os.Build.VERSION.SDK_INT >= 33) intent.putExtra("android.speech.extra.ENABLE_FORMATTING", "quality");
            intent.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 180000L);
            intent.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 180000L);
            nativeSpeechRecognizer.startListening(intent);
        } catch (Exception e) {
            nativeVoiceActive = false;
            if (nativeSpeechRecognizer != null) { try { nativeSpeechRecognizer.destroy(); } catch (Exception ignored) {} nativeSpeechRecognizer = null; }
            voiceJs("window.svNativeVoiceError && window.svNativeVoiceError('Could not start Android voice recognition.')");
        }
    }
    private WebView webView;
    private TextView status;
    private TextView loadingDots;
    private final Handler loadingHandler = new Handler(Looper.getMainLooper());
    private int loadingDotCount = 1;
    private int hostedRetryCount = 0;
    private boolean hostedAppReady = false;
    private final Runnable loadingAnimation = new Runnable() {
        @Override public void run() {
            if (loadingDots == null || hostedAppReady) return;
            StringBuilder dots = new StringBuilder();
            for (int i = 0; i < loadingDotCount; i++) dots.append(".");
            loadingDots.setText(dots.toString());
            loadingDotCount = loadingDotCount >= 3 ? 1 : loadingDotCount + 1;
            loadingHandler.postDelayed(this, 420);
        }
    };
    private final Runnable retryHostedPage = new Runnable() {
        @Override public void run() {
            if (!hostedAppReady && webView != null && hostedRetryCount < 5) {
                hostedRetryCount++;
                String baseUrl = BuildConfig.PUBLIC_URL.trim().replaceAll("/+$", "");
                String currentUrl = webView.getUrl();
                String targetPath = "/customer-app";
                if (currentUrl != null && Uri.parse(currentUrl).getPath() != null && Uri.parse(currentUrl).getPath().startsWith("/owner-app")) targetPath = "/owner-app";
                webView.loadUrl(baseUrl + targetPath + "?native_refresh=" + System.currentTimeMillis());
            }
        }
    };
    private ValueCallback<Uri[]> filePathCallback;
    private Uri cameraOutputUri;
    private PermissionRequest pendingWebPermission;
    private File cameraOutputFile;
    private static final int FILE_CHOOSER_REQUEST = 7341;
    private static final int WEB_RTC_PERMISSION_REQUEST = 7342;
    private boolean handleExternalNavigation(String rawUrl) {
        if (rawUrl == null || rawUrl.trim().isEmpty()) return true;
        Uri uri = Uri.parse(rawUrl);
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase();
        if (("http".equals(scheme) || "https".equals(scheme)) && BuildConfig.PUBLIC_URL != null) {
            Uri base = Uri.parse(BuildConfig.PUBLIC_URL.trim());
            if (base.getHost() != null && base.getHost().equalsIgnoreCase(uri.getHost())) return false;
        }
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (ActivityNotFoundException e) {
            Toast.makeText(this, "No app is available to open this contact link. You can copy the provider's number and open WhatsApp manually.", Toast.LENGTH_LONG).show();
        } catch (Exception e) {
            Toast.makeText(this, "Could not open this contact link.", Toast.LENGTH_LONG).show();
        }
        return true;
    }

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.rgb(7,20,38));
        getWindow().setNavigationBarColor(Color.rgb(7,20,38));
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.rgb(7,20,38));
        webView = new WebView(this);
        LinearLayout loadingPanel = new LinearLayout(this);
        loadingPanel.setOrientation(LinearLayout.VERTICAL);
        loadingPanel.setGravity(Gravity.CENTER);
        loadingPanel.setPadding(24, 24, 24, 24);
        loadingPanel.setBackgroundColor(Color.rgb(7,20,38));
        TextView brand = new TextView(this);
        brand.setText("Skillvaya");
        brand.setTextColor(Color.WHITE);
        brand.setTextSize(32);
        brand.setTypeface(android.graphics.Typeface.DEFAULT, android.graphics.Typeface.BOLD);
        brand.setGravity(Gravity.CENTER);
        loadingPanel.addView(brand, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        status = new TextView(this);
        status.setText("Loading");
        status.setTextColor(Color.rgb(218,232,244));
        status.setTextSize(17);
        status.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams statusParams = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        statusParams.topMargin = 12;
        loadingPanel.addView(status, statusParams);
        loadingDots = new TextView(this);
        loadingDots.setText(".");
        loadingDots.setTextColor(Color.rgb(34,211,204));
        loadingDots.setTextSize(30);
        loadingDots.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams dotsParams = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, 48);
        loadingPanel.addView(loadingDots, dotsParams);
        root.addView(webView, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        root.addView(loadingPanel, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root); webView.setVisibility(WebView.GONE);
        loadingHandler.post(loadingAnimation);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true); settings.setDomStorageEnabled(true); settings.setUserAgentString(settings.getUserAgentString() + " SkillvayaNative");
        nativeVoiceBridge = new NativeVoiceBridge();
        webView.addJavascriptInterface(nativeVoiceBridge, "SkillvayaVoice");
        if (BuildConfig.PUBLIC_URL != null && BuildConfig.PUBLIC_URL.trim().startsWith("https://")) {
            playBillingBridge = new PlayBillingBridge(this, BuildConfig.PUBLIC_URL.trim());
            webView.addJavascriptInterface(playBillingBridge, "SkillvayaBilling");
        }
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
            @Override public void onPermissionRequest(PermissionRequest request) {
                runOnUiThread(() -> {
                    if (request == null || request.getOrigin() == null) {
                        if (request != null) request.deny();
                        return;
                    }
                    String origin = request.getOrigin().toString();
                    String base = BuildConfig.PUBLIC_URL == null ? "" : BuildConfig.PUBLIC_URL.trim().replaceAll("/+$", "");
                    boolean trusted = (!base.isEmpty() && (origin.equals(base) || origin.startsWith(base + "/")))
                        || origin.equals("http://127.0.0.1:8878") || origin.startsWith("http://127.0.0.1:8878/")
                        || origin.equals("http://localhost:8878") || origin.startsWith("http://localhost:8878/");
                    if (!trusted) { request.deny(); return; }
                    java.util.ArrayList<String> needed = new java.util.ArrayList<>();
                    for (String resource : request.getResources()) {
                        if (PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(resource)
                                && checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED
                                && !needed.contains(Manifest.permission.CAMERA)) needed.add(Manifest.permission.CAMERA);
                        if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resource)
                                && checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED
                                && !needed.contains(Manifest.permission.RECORD_AUDIO)) needed.add(Manifest.permission.RECORD_AUDIO);
                    }
                    if (!needed.isEmpty()) {
                        if (pendingWebPermission != null && pendingWebPermission != request) pendingWebPermission.deny();
                        pendingWebPermission = request;
                        requestPermissions(needed.toArray(new String[0]), WEB_RTC_PERMISSION_REQUEST);
                    } else {
                        request.grant(request.getResources());
                    }
                });
            }
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (filePathCallback != null) filePathCallback.onReceiveValue(null);
                filePathCallback = callback;
                cameraOutputUri = null;
                cameraOutputFile = null;
                try {
                    boolean wantsCapture = params.isCaptureEnabled();
                    String[] acceptTypes = params.getAcceptTypes();
                    if (!wantsCapture && acceptTypes != null) {
                        for (String type : acceptTypes) if (type != null && type.startsWith("image/")) wantsCapture = false;
                    }
                    if (wantsCapture) {
                        Intent camera = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
                        // Do not gate camera launch on resolveActivity(): Android 11+ package
                        // visibility can hide installed camera apps unless they are declared in <queries>.
                        File cameraDir = new File(getCacheDir(), "camera");
                        if (!cameraDir.exists() && !cameraDir.mkdirs()) throw new IllegalStateException("Could not create camera storage.");
                        File photo = File.createTempFile("skillvaya_profile_", ".jpg", cameraDir);
                        cameraOutputFile = photo;
                        cameraOutputUri = FileProvider.getUriForFile(MainActivity.this, getPackageName() + ".fileprovider", photo);
                        camera.putExtra(MediaStore.EXTRA_OUTPUT, cameraOutputUri);
                        camera.setClipData(ClipData.newRawUri("Skillvaya profile photo", cameraOutputUri));
                        camera.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
                        try {
                            startActivityForResult(camera, FILE_CHOOSER_REQUEST);
                            return true;
                        } catch (ActivityNotFoundException noCamera) {
                            if (cameraOutputFile != null) cameraOutputFile.delete();
                            cameraOutputFile = null; cameraOutputUri = null;
                            // Some OEMs don't expose a camera intent; fall back to the system
                            // picker so users can still select an image rather than a dead button.
                            Intent picker = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                            picker.addCategory(Intent.CATEGORY_OPENABLE); picker.setType("image/*");
                            startActivityForResult(picker, FILE_CHOOSER_REQUEST);
                            return true;
                        }
                    }
                    // Use Android's system document picker directly. This avoids WebView-generated
                    // chooser intents that can behave inconsistently across Android versions.
                    Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                    intent.addCategory(Intent.CATEGORY_OPENABLE);
                    String[] acceptedTypes = params.getAcceptTypes();
                    int acceptedCount = 0;
                    String singleType = null;
                    if (acceptedTypes != null) {
                        for (String acceptedType : acceptedTypes) {
                            if (acceptedType != null && !acceptedType.trim().isEmpty() && !"*/*".equals(acceptedType.trim())) {
                                acceptedCount++;
                                singleType = acceptedType.trim();
                            }
                        }
                    }
                    if (acceptedCount == 1) {
                        intent.setType(singleType);
                    } else if (acceptedCount > 1) {
                        intent.setType("*/*");
                        intent.putExtra(Intent.EXTRA_MIME_TYPES, acceptedTypes);
                    } else {
                        intent.setType("*/*");
                    }
                    if (params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE) intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                    try {
                        startActivityForResult(intent, FILE_CHOOSER_REQUEST);
                        return true;
                    } catch (ActivityNotFoundException noPicker) {
                        Intent fallback = new Intent(Intent.ACTION_GET_CONTENT);
                        fallback.addCategory(Intent.CATEGORY_OPENABLE); fallback.setType("image/*");
                        startActivityForResult(Intent.createChooser(fallback, "Choose profile picture"), FILE_CHOOSER_REQUEST);
                        return true;
                    }
                } catch (Exception e) {
                    if (filePathCallback != null) filePathCallback.onReceiveValue(null);
                    filePathCallback = null;
                    cameraOutputUri = null;
                    cameraOutputFile = null;
                    Toast.makeText(MainActivity.this, "Could not open the camera or file picker: " + e.getMessage(), Toast.LENGTH_LONG).show();
                    return true;
                }
            }
        });
        try {
            if (BuildConfig.PUBLIC_URL != null && !BuildConfig.PUBLIC_URL.trim().isEmpty()) {
                status.setText("Loading");
                webView.setWebViewClient(new WebViewClient() {
                    @Override public void onPageFinished(WebView view, String url) {
                        // Render can briefly return its own wake-up/status page while the service starts.
                        // Keep the branded Skillvaya splash visible until the real app document is loaded.
                        view.evaluateJavascript("(function(){var p=location.pathname||'';var b=document.body;var owner=p.indexOf('/owner-app')===0;var customer=p.indexOf('/customer-app')===0;var t=(document.title||'').toLowerCase();if(owner)return !!(b&&b.children.length>0&&(document.getElementById('loginScreen')||document.getElementById('appShell')));return customer&&!!b&&t.indexOf('skillvaya')>=0&&t.indexOf('render')<0&&b.innerText.trim().length>20;})()", value -> {
                            if ("true".equals(value)) {
                                hostedAppReady = true;
                                loadingHandler.removeCallbacks(retryHostedPage);
                                loadingHandler.removeCallbacks(loadingAnimation);
                                status.setText("Ready");
                                ViewGroup parent = (ViewGroup) status.getParent();
                                if (parent != null) {
                                    parent.setVisibility(ViewGroup.GONE);
                                }
                                webView.setVisibility(ViewGroup.VISIBLE);
                            } else if (!hostedAppReady) {
                                loadingHandler.removeCallbacks(retryHostedPage);
                                loadingHandler.postDelayed(retryHostedPage, 2200);
                            }
                        });
                    }
                    @Override public boolean shouldOverrideUrlLoading(WebView view, String url) {
                        return handleExternalNavigation(url);
                    }
                });
                String baseUrl = BuildConfig.PUBLIC_URL.trim().replaceAll("/+$", "");
                // Open the public directory first. The standalone /login gateway hides the
                // customer category list, so account actions should be entered from the app UI.
                webView.loadUrl(baseUrl + "/customer-app?native_refresh=" + System.currentTimeMillis());
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
                        if (code==200) { runOnUiThread(() -> { loadingHandler.removeCallbacks(loadingAnimation); ((ViewGroup) status.getParent().getParent()).setVisibility(ViewGroup.GONE); webView.setVisibility(WebView.VISIBLE); webView.loadUrl("http://127.0.0.1:8878/login"); }); return; }
                    } catch (Exception ignored) {}
                    try { Thread.sleep(250); } catch (InterruptedException ignored) { return; }
                }
                runOnUiThread(() -> status.setText("Skillvaya startup timed out. Close and reopen the app."));
            }, "SkillvayaHealthCheck").start();
        } catch (Exception e) { status.setText("Skillvaya setup failed. Please reinstall the app."); }
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == NATIVE_VOICE_PERMISSION_REQUEST) {
            boolean granted = grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED;
            if (granted) startNativeVoice();
            else voiceJs("window.svNativeVoiceError && window.svNativeVoiceError('Microphone permission is required for voice typing.')");
            return;
        }
        if (requestCode != WEB_RTC_PERMISSION_REQUEST) return;
        PermissionRequest pending = pendingWebPermission;
        pendingWebPermission = null;
        if (pending == null) return;
        boolean granted = grantResults.length > 0;
        for (int result : grantResults) if (result != PackageManager.PERMISSION_GRANTED) granted = false;
        if (granted) {
            pending.grant(pending.getResources());
        } else {
            pending.deny();
            Toast.makeText(this, "Allow camera and microphone permissions to use Skillvaya video calls.", Toast.LENGTH_LONG).show();
        }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == FILE_CHOOSER_REQUEST) {
            if (filePathCallback == null) return;
            Uri[] results = null;
            if (resultCode == Activity.RESULT_OK) {
                if (cameraOutputUri != null) {
                    // Some camera apps return RESULT_OK without writing the requested output.
                    // Only hand the URI to WebView if the actual photo file contains data.
                    if (cameraOutputFile != null && cameraOutputFile.isFile() && cameraOutputFile.length() > 0) {
                        results = new Uri[]{cameraOutputUri};
                    } else if (data != null && data.getData() != null) {
                        results = new Uri[]{data.getData()};
                    } else {
                        Toast.makeText(MainActivity.this, "The camera did not return a photo. Please try again.", Toast.LENGTH_LONG).show();
                    }
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
            cameraOutputFile = null;
        }
    }
    private void copyAsset(String name) throws Exception {
        File out=new File(getFilesDir(),name); if(out.exists()&&out.length()>0)return;
        try(InputStream in=getAssets().open(name);FileOutputStream fos=new FileOutputStream(out)){
            byte[] buffer=new byte[8192];int n;while((n=in.read(buffer))>0)fos.write(buffer,0,n);
        }
    }
    @Override protected void onDestroy() {
        if (playBillingBridge != null) playBillingBridge.shutdown();
        stopNativeVoice(false);
        super.onDestroy();
    }
    @Override public void onBackPressed(){if(webView!=null&&webView.canGoBack())webView.goBack();else super.onBackPressed();}
}
