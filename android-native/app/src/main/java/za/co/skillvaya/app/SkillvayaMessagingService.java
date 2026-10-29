package za.co.skillvaya.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.Build;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

public final class SkillvayaMessagingService extends FirebaseMessagingService {
    private static final String CALL_CHANNEL_ID = "skillvaya_incoming_calls_v2";
    private static final String MESSAGE_CHANNEL_ID = "skillvaya_messages_v2";

    @Override public void onNewToken(String token) {
        // Re-register refreshed tokens. MainActivity also retries after the user signs in,
        // so this best-effort call is safe even when a session cookie is not ready yet.
        String baseUrl = BuildConfig.PUBLIC_URL;
        if (baseUrl != null && baseUrl.startsWith("https://")) {
            PushTokenRegistrar.register(getApplicationContext(), baseUrl);
        }
    }

    @Override public void onMessageReceived(RemoteMessage message) {
        String type = message.getData().get("type");
        boolean call = "incoming_call".equals(type);
        RemoteMessage.Notification remoteNotification = message.getNotification();
        String title = message.getData().get("title");
        if ((title == null || title.isEmpty()) && remoteNotification != null) title = remoteNotification.getTitle();
        if (title == null || title.isEmpty()) title = call ? "Skillvaya calling" : "Skillvaya message";
        String body = message.getData().get("body");
        if ((body == null || body.isEmpty()) && remoteNotification != null) body = remoteNotification.getBody();
        if (body == null || body.isEmpty()) body = call ? "You have an incoming video call." : "You have a new message.";

        ensureChannels(this);
        String channelId = call ? CALL_CHANNEL_ID : MESSAGE_CHANNEL_ID;
        Intent intent = new Intent(this, MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        intent.putExtra("skillvaya_push_type", call ? "incoming_call" : "message");
        if (message.getData().containsKey("call_id")) intent.putExtra("skillvaya_call_id", message.getData().get("call_id"));
        PendingIntent pending = PendingIntent.getActivity(this, (int) (System.currentTimeMillis() & 0x7fffffff),
                intent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        NotificationCompat.Builder builder = new NotificationCompat.Builder(this, channelId)
                .setSmallIcon(R.drawable.skillvaya_icon)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(new NotificationCompat.BigTextStyle().bigText(body))
                .setContentIntent(pending)
                .setAutoCancel(true)
                .setPriority(call ? NotificationCompat.PRIORITY_MAX : NotificationCompat.PRIORITY_HIGH)
                .setCategory(call ? NotificationCompat.CATEGORY_CALL : NotificationCompat.CATEGORY_MESSAGE)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC);
        // On Android O+, channel sound/vibration settings are authoritative.
        if (call && Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            builder.setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE))
                   .setVibrate(new long[]{0, 600, 250, 600, 250, 900});
        } else if (!call && Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            builder.setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION));
        }
        int notificationId = call
                ? (message.getData().getOrDefault("call_id", "call").hashCode() & 0x7fffffff)
                : (int) (System.currentTimeMillis() & 0x7fffffff);
        try {
            NotificationManagerCompat.from(this).notify(notificationId, builder.build());
        } catch (SecurityException ignored) {
            // Android notification permission can be disabled by the user; the OS owns that setting.
        }
    }

    public static void ensureChannels(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O || context == null) return;
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null) return;

        if (manager.getNotificationChannel(CALL_CHANNEL_ID) == null) {
            NotificationChannel calls = new NotificationChannel(
                    CALL_CHANNEL_ID, "Skillvaya incoming calls", NotificationManager.IMPORTANCE_HIGH);
            calls.setDescription("Ringing alerts for incoming Skillvaya video calls");
            calls.enableVibration(true);
            calls.setVibrationPattern(new long[]{0, 600, 250, 600, 250, 900});
            calls.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
            Uri ringtone = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE);
            AudioAttributes audio = new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build();
            calls.setSound(ringtone, audio);
            manager.createNotificationChannel(calls);
        }

        if (manager.getNotificationChannel(MESSAGE_CHANNEL_ID) == null) {
            NotificationChannel messages = new NotificationChannel(
                    MESSAGE_CHANNEL_ID, "Skillvaya messages", NotificationManager.IMPORTANCE_HIGH);
            messages.setDescription("Alerts for new Skillvaya messages");
            messages.enableVibration(true);
            messages.setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION),
                    new AudioAttributes.Builder()
                            .setUsage(AudioAttributes.USAGE_NOTIFICATION)
                            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                            .build());
            manager.createNotificationChannel(messages);
        }
    }
}