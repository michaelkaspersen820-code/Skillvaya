package za.co.skillvaya.app;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.provider.ContactsContract;
import android.net.Uri;
import android.util.Base64;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import android.widget.Toast;
import com.google.firebase.FirebaseException;
import com.google.firebase.FirebaseTooManyRequestsException;
import com.google.firebase.auth.FirebaseAuth;
import com.google.firebase.auth.FirebaseAuthInvalidCredentialsException;
import com.google.firebase.auth.PhoneAuthCredential;
import com.google.firebase.auth.PhoneAuthOptions;
import com.google.firebase.auth.PhoneAuthProvider;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;

/** Native helpers for Future Chat inside Skillvaya: SMS phone verification and the Chatmoji Lens camera. */
public final class FutureChatBridge {
    static final int LENS_REQUEST = 7402;
    static final int CONTACTS_REQUEST = 7403;
    private final Activity activity;
    private final WebView web;
    private String verificationId;
    private PhoneAuthProvider.ForceResendingToken resendToken;

    FutureChatBridge(Activity activity, WebView web) { this.activity = activity; this.web = web; }

    private void js(String fn, String... args) {
        StringBuilder s = new StringBuilder("window.").append(fn).append("&&window.").append(fn).append("(");
        for (int i = 0; i < args.length; i++) { if (i > 0) s.append(','); s.append(JSONObject.quote(args[i] == null ? "" : args[i])); }
        s.append(")");
        String script = s.toString();
        activity.runOnUiThread(() -> { if (web != null) web.evaluateJavascript(script, null); });
    }

    @JavascriptInterface public boolean hasLens() { return true; }

    @JavascriptInterface public void openLens() {
        activity.runOnUiThread(() -> {
            try {
                Intent i = new Intent(activity, LensActivity.class);
                i.putExtra(LensActivity.EXTRA_TITLE, "Chatmoji Lenses");
                activity.startActivityForResult(i, LENS_REQUEST);
            } catch (Exception e) { Toast.makeText(activity, "The camera couldn't open", Toast.LENGTH_LONG).show(); }
        });
    }

    /** Called from MainActivity.onActivityResult with the Lens photo. */
    void deliverLens(int resultCode, Intent data) {
        if (resultCode != Activity.RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData();
        new Thread(() -> {
            try (InputStream in = activity.getContentResolver().openInputStream(uri)) {
                ByteArrayOutputStream out = new ByteArrayOutputStream(); byte[] buf = new byte[16384]; int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                js("fcLensResult", Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP), "image/jpeg");
            } catch (Exception e) {
                activity.runOnUiThread(() -> Toast.makeText(activity, "The photo couldn't be added", Toast.LENGTH_LONG).show());
            }
        }, "fc-lens-result").start();
    }

    // ---- phone contacts: the in-app disclosure is shown by Future Chat before readContacts() is called.
    @JavascriptInterface public String contactsPermission() {
        if (android.os.Build.VERSION.SDK_INT < 23) return "granted";
        return activity.checkSelfPermission(Manifest.permission.READ_CONTACTS) == PackageManager.PERMISSION_GRANTED ? "granted" : "ask";
    }

    @JavascriptInterface public void readContacts() {
        activity.runOnUiThread(() -> {
            if ("granted".equals(contactsPermission())) { readContactsNow(); return; }
            activity.requestPermissions(new String[]{Manifest.permission.READ_CONTACTS}, CONTACTS_REQUEST);
        });
    }

    /** Called from MainActivity.onRequestPermissionsResult. */
    void onContactsPermission(boolean granted) {
        if (granted) readContactsNow(); else js("fcContactsDenied");
    }

    private void readContactsNow() {
        new Thread(() -> {
            JSONArray out = new JSONArray();
            String[] cols = {ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME, ContactsContract.CommonDataKinds.Phone.NUMBER};
            try (Cursor cur = activity.getContentResolver().query(ContactsContract.CommonDataKinds.Phone.CONTENT_URI, cols, null, null, null)) {
                if (cur != null) {
                    while (cur.moveToNext() && out.length() < 5000) {
                        String num = cur.getString(1);
                        if (num == null || num.trim().isEmpty()) continue;
                        JSONObject o = new JSONObject();
                        o.put("name", cur.getString(0) == null ? "" : cur.getString(0));
                        o.put("phone", num);
                        out.put(o);
                    }
                }
            } catch (Exception e) {
                js("fcContactsDenied");
                return;
            }
            js("fcContacts", out.toString());
        }, "fc-contacts").start();
    }

    @JavascriptInterface public void startPhoneVerification(String phone) {
        activity.runOnUiThread(() -> {
            try {
                PhoneAuthOptions.Builder b = PhoneAuthOptions.newBuilder(FirebaseAuth.getInstance())
                        .setPhoneNumber(phone).setTimeout(60L, TimeUnit.SECONDS).setActivity(activity)
                        .setCallbacks(new PhoneAuthProvider.OnVerificationStateChangedCallbacks() {
                            @Override public void onVerificationCompleted(PhoneAuthCredential credential) { signIn(credential); }
                            @Override public void onVerificationFailed(FirebaseException e) { js("fcPhoneError", friendly(e)); }
                            @Override public void onCodeSent(String id, PhoneAuthProvider.ForceResendingToken token) {
                                verificationId = id; resendToken = token; js("fcPhoneCodeSent");
                            }
                        });
                if (resendToken != null) b.setForceResendingToken(resendToken);
                PhoneAuthProvider.verifyPhoneNumber(b.build());
            } catch (Exception e) { js("fcPhoneError", "We couldn't send a code right now. Please try again."); }
        });
    }

    @JavascriptInterface public void confirmPhoneCode(String code) {
        activity.runOnUiThread(() -> {
            if (verificationId == null) { js("fcPhoneError", "Request a code first."); return; }
            try { signIn(PhoneAuthProvider.getCredential(verificationId, code)); }
            catch (Exception e) { js("fcPhoneError", "That code didn't work. Check it or send a new one."); }
        });
    }

    private void signIn(PhoneAuthCredential credential) {
        FirebaseAuth auth = FirebaseAuth.getInstance();
        auth.signInWithCredential(credential).addOnCompleteListener(activity, t -> {
            if (!t.isSuccessful() || t.getResult() == null || t.getResult().getUser() == null) { js("fcPhoneError", "That code didn't work. Check it or send a new one."); return; }
            t.getResult().getUser().getIdToken(true).addOnCompleteListener(activity, tt -> {
                if (tt.isSuccessful() && tt.getResult() != null && tt.getResult().getToken() != null) js("fcPhoneVerified", tt.getResult().getToken());
                else js("fcPhoneError", "Verification failed. Please try again.");
                // Skillvaya keeps its own session; the Firebase sign-in is only used to prove the number.
                auth.signOut();
            });
        });
    }

    private static String friendly(FirebaseException e) {
        if (e instanceof FirebaseTooManyRequestsException) return "Too many attempts. Please try again a bit later.";
        if (e instanceof FirebaseAuthInvalidCredentialsException) return "That phone number doesn't look right. Include your full number.";
        String m = String.valueOf(e.getMessage());
        if (m.contains("quota") || m.contains("QUOTA")) return "We've sent the maximum codes for today. Please try again tomorrow.";
        return "We couldn't send a code right now. Please try again.";
    }
}
