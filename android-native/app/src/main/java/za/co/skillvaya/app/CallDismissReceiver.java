package za.co.skillvaya.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import androidx.core.app.NotificationManagerCompat;

/** "Decline" on the incoming-call screen: stops the ringing. The caller sees a missed call when it times out. */
public final class CallDismissReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        int id = intent == null ? 0 : intent.getIntExtra("notification_id", 0);
        if (id != 0) {
            try { NotificationManagerCompat.from(context).cancel(id); } catch (Exception ignored) {}
        }
    }
}
