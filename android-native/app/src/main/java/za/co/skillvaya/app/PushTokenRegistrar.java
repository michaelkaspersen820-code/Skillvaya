package za.co.skillvaya.app;

import android.app.Activity;
import android.webkit.CookieManager;
import android.content.SharedPreferences;
import java.security.MessageDigest;
import com.google.firebase.messaging.FirebaseMessaging;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import org.json.JSONObject;

final class PushTokenRegistrar {
    private PushTokenRegistrar() {}
    static void register(Activity activity, String baseUrl) {
        if (activity == null || baseUrl == null || !baseUrl.startsWith("https://")) return;
        FirebaseMessaging.getInstance().getToken().addOnSuccessListener(token -> {
            if (token == null || token.length() < 40 || activity.isFinishing()) return;
            new Thread(() -> {
                HttpURLConnection connection = null;
                try {
                    String base = baseUrl.replaceAll("/+$", "");
                    String cookie = CookieManager.getInstance().getCookie(base);
                    if (cookie == null || !cookie.contains("skillvaya_session=")) return;
                    String sessionHash = sha256(cookie);
                    SharedPreferences prefs = activity.getSharedPreferences("skillvaya_push_registration", Activity.MODE_PRIVATE);
                    String tokenHash = sha256(token);
                    if (sessionHash.equals(prefs.getString("session_hash", "")) && tokenHash.equals(prefs.getString("token_hash", ""))) return;
                    connection = (HttpURLConnection) new URL(base + "/api/push/register").openConnection();
                    connection.setRequestMethod("POST");
                    connection.setConnectTimeout(5000);
                    connection.setReadTimeout(5000);
                    connection.setDoOutput(true);
                    connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                    connection.setRequestProperty("Cookie", cookie);
                    byte[] body = new JSONObject().put("token", token).put("platform", "android").toString().getBytes("UTF-8");
                    connection.setFixedLengthStreamingMode(body.length);
                    try (OutputStream out = connection.getOutputStream()) { out.write(body); }
                    int responseCode = connection.getResponseCode();
                    if (responseCode >= 200 && responseCode < 300) {
                        prefs.edit().putString("session_hash", sessionHash).putString("token_hash", tokenHash).apply();
                    }
                } catch (Exception ignored) {
                    // Push is best-effort; existing in-app message/call polling remains available.
                } finally {
                    if (connection != null) connection.disconnect();
                }
            }, "SkillvayaPushTokenRegister").start();
        });
    }
    private static String sha256(String value) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(value.getBytes("UTF-8"));
        StringBuilder out = new StringBuilder(digest.length * 2);
        for (byte b : digest) out.append(String.format(java.util.Locale.ROOT, "%02x", b & 0xff));
        return out.toString();
    }
}
