package za.co.skillvaya.app;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.media.RingtoneManager;
import android.os.Build;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

public final class SkillvayaMessagingService extends FirebaseMessagingService {
    private static final String CHANNEL_ID = "skillvaya_calls_messages";

    @Override public void onNewToken(String token) {
        // MainActivity registers the latest token with the authenticated session when the app opens.
    }

    @Override public void onMessageReceived(RemoteMessage message) {
        String type = message.getData().get("type");
        boolean call = "incoming_call".equals(type);
        String title = message.getData().get("title");
        if (title == null || title.isEmpty()) title = call ? "Skillvaya calling" : "Skillvaya message";
        String body = message.getData().get("body");
        if (body == null || body.isEmpty()) body = call ? "You have an incoming video call." : "You have a new message.";
        createChannel();
        Intent intent = new Intent(this, MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        intent.putExtra("skillvaya_push_type", call ? "incoming_call" : "message");
        if (message.getData().containsKey("call_id")) intent.putExtra("skillvaya_call_id", message.getData().get("call_id"));
        PendingIntent pending = PendingIntent.getActivity(this, (int) (System.currentTimeMillis() & 0x7fffffff),
                intent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        NotificationCompat.Builder builder = new NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.drawable.skillvaya_icon)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(new NotificationCompat.BigTextStyle().bigText(body))
                .setContentIntent(pending)
                .setAutoCancel(true)
                .setPriority(call ? NotificationCompat.PRIORITY_MAX : NotificationCompat.PRIORITY_HIGH)
                .setCategory(call ? NotificationCompat.CATEGORY_CALL : NotificationCompat.CATEGORY_MESSAGE)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC);
        if (call) builder.setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)).setVibrate(new long[]{0,500,250,500,250,700});
        else builder.setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION));
        try { NotificationManagerCompat.from(this).notify((int) (System.currentTimeMillis() & 0x7fffffff), builder.build()); }
        catch (SecurityException ignored) { }
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null && manager.getNotificationChannel(CHANNEL_ID) == null) {
                NotificationChannel channel = new NotificationChannel(CHANNEL_ID, "Skillvaya calls and messages",
                        NotificationManager.IMPORTANCE_HIGH);
                channel.setDescription("Incoming video calls and new Skillvaya chat messages");
                channel.enableVibration(true);
                manager.createNotificationChannel(channel);
            }
        }
    }
}
