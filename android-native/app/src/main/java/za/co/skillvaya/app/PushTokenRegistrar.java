package za.co.skillvaya.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;
import android.webkit.CookieManager;
import com.google.firebase.messaging.FirebaseMessaging;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import org.json.JSONObject;

final class PushTokenRegistrar {
    private static final String TAG = "SkillvayaPush";
    private PushTokenRegistrar() {}

    static void register(Context context, String baseUrl) {
        if (context == null || baseUrl == null || !baseUrl.startsWith("https://")) return;
        final Context appContext = context.getApplicationContext();
        FirebaseMessaging.getInstance().getToken()
                .addOnSuccessListener(token -> {
                    if (token == null || token.length() < 40) {
                        Log.w(TAG, "Firebase returned an empty or invalid registration token");
                        return;
                    }
                    new Thread(() -> {
                        HttpURLConnection connection = null;
                        try {
                            String base = baseUrl.replaceAll("/+$", "");
                            String cookie = CookieManager.getInstance().getCookie(base);
                            if (cookie == null || !cookie.contains("skillvaya_session=")) {
                                // The launcher may start before sign-in. The activity retries this
                                // registration after sign-in/foregrounding; never register to an anonymous user.
                                return;
                            }
                            String sessionHash = sha256(cookie);
                            SharedPreferences prefs = appContext.getSharedPreferences(
                                    "skillvaya_push_registration", Context.MODE_PRIVATE);
                            String tokenHash = sha256(token);
                            if (sessionHash.equals(prefs.getString("session_hash", "")) &&
                                    tokenHash.equals(prefs.getString("token_hash", ""))) return;

                            connection = (HttpURLConnection) new URL(base + "/api/push/register").openConnection();
                            connection.setRequestMethod("POST");
                            connection.setConnectTimeout(5000);
                            connection.setReadTimeout(5000);
                            connection.setDoOutput(true);
                            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                            connection.setRequestProperty("Cookie", cookie);
                            byte[] body = new JSONObject()
                                    .put("token", token)
                                    .put("platform", "android")
                                    .toString().getBytes("UTF-8");
                            connection.setFixedLengthStreamingMode(body.length);
                            try (OutputStream out = connection.getOutputStream()) {
                                out.write(body);
                            }
                            int responseCode = connection.getResponseCode();
                            if (responseCode >= 200 && responseCode < 300) {
                                prefs.edit().putString("session_hash", sessionHash)
                                        .putString("token_hash", tokenHash).apply();
                                Log.i(TAG, "Push token registered for the signed-in Skillvaya account");
                            } else {
                                Log.w(TAG, "Push token registration returned HTTP " + responseCode);
                            }
                        } catch (Exception e) {
                            Log.w(TAG, "Push token registration failed: " + e.getClass().getSimpleName());
                        } finally {
                            if (connection != null) connection.disconnect();
                        }
                    }, "SkillvayaPushTokenRegister").start();
                })
                .addOnFailureListener(error ->
                        Log.w(TAG, "Could not retrieve Firebase token: " + error.getClass().getSimpleName()));
    }

    private static String sha256(String value) throws Exception {
        byte[] digest = java.security.MessageDigest.getInstance("SHA-256").digest(value.getBytes("UTF-8"));
        StringBuilder out = new StringBuilder(digest.length * 2);
        for (byte b : digest) out.append(String.format(java.util.Locale.ROOT, "%02x", b & 0xff));
        return out.toString();
    }
}