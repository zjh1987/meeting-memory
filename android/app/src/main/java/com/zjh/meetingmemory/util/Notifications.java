package com.zjh.meetingmemory.util;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;

import androidx.core.app.NotificationCompat;

import com.zjh.meetingmemory.R;
import com.zjh.meetingmemory.recording.RecordingService;
import com.zjh.meetingmemory.ui.MainActivity;
import com.zjh.meetingmemory.ui.MeetingDetailActivity;

public final class Notifications {

    public static final String CHANNEL_RECORDING = "mm_recording";
    public static final String CHANNEL_UPLOAD = "mm_upload";
    public static final String CHANNEL_DONE = "mm_done";
    public static final int ID_RECORDING = 1001;

    private Notifications() {
    }

    public static void ensureChannels(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null) {
            return;
        }
        NotificationChannel recording = new NotificationChannel(
                CHANNEL_RECORDING, "录音", NotificationManager.IMPORTANCE_LOW);
        recording.setDescription("长录音前台服务与暂停/结束控制");
        recording.setSound(null, null);
        recording.setShowBadge(false);
        manager.createNotificationChannel(recording);

        NotificationChannel upload = new NotificationChannel(
                CHANNEL_UPLOAD, "上传", NotificationManager.IMPORTANCE_DEFAULT);
        upload.setDescription("录音上传进度与失败提醒");
        manager.createNotificationChannel(upload);

        NotificationChannel done = new NotificationChannel(
                CHANNEL_DONE, "纪要完成", NotificationManager.IMPORTANCE_DEFAULT);
        done.setDescription("纪要生成完成提醒");
        manager.createNotificationChannel(done);
    }

    public static Notification recording(Context context, String title, boolean paused,
                                         long startedAt, long elapsedMs) {
        Intent pause = new Intent(context, RecordingService.class)
                .setAction(paused ? RecordingService.ACTION_RESUME
                        : RecordingService.ACTION_PAUSE);
        Intent stop = new Intent(context, RecordingService.class)
                .setAction(RecordingService.ACTION_STOP);
        PendingIntent pauseIntent = PendingIntent.getService(context, 11, pause,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        PendingIntent stopIntent = PendingIntent.getService(context, 12, stop,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        NotificationCompat.Builder builder = new NotificationCompat.Builder(context,
                CHANNEL_RECORDING)
                .setSmallIcon(R.drawable.ic_stat_mic)
                .setContentTitle(paused ? "录音已暂停" : "正在录音")
                .setContentText(paused
                        ? title + " · " + Formats.duration(elapsedMs)
                        : title)
                .setContentIntent(openMain(context, "record"))
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setCategory(NotificationCompat.CATEGORY_SERVICE)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .setWhen(startedAt)
                .setShowWhen(true)
                .setUsesChronometer(!paused)
                .addAction(paused ? R.drawable.ic_play : R.drawable.ic_pause,
                        paused ? "继续" : "暂停", pauseIntent)
                .addAction(R.drawable.ic_stop, "结束", stopIntent)
                .setForegroundServiceBehavior(
                        NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE);
        return builder.build();
    }

    public static void updateRecording(Context context, String title, boolean paused,
                                       long startedAt, long elapsedMs) {
        notify(context, ID_RECORDING, recording(context, title, paused, startedAt, elapsedMs));
    }

    public static void uploadProgress(Context context, long localId, String title,
                                      int progress) {
        String text = progress <= 0 ? title : title + " · " + progress + "%";
        NotificationCompat.Builder builder = new NotificationCompat.Builder(context,
                CHANNEL_UPLOAD)
                .setSmallIcon(R.drawable.ic_stat_mic)
                .setContentTitle("正在上传录音")
                .setContentText(text)
                .setContentIntent(openMain(context, "record"))
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .setShowWhen(false)
                .setTimeoutAfter(15 * 60 * 1000L);
        if (progress <= 0) {
            builder.setProgress(0, 0, true);
        } else {
            builder.setProgress(100, progress, false);
        }
        notify(context, notificationId(localId), builder.build());
    }

    public static void uploadFinished(Context context, long localId, String title,
                                      boolean ok, String message, String uid) {
        Intent intent = uid != null && !uid.isEmpty()
                ? MeetingDetailActivity.intent(context, uid, title)
                : new Intent(context, MainActivity.class)
                .putExtra("tab", "meetings")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent content = PendingIntent.getActivity(context,
                (int) (3000 + localId % 500), intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        NotificationCompat.Builder builder = new NotificationCompat.Builder(context,
                CHANNEL_UPLOAD)
                .setSmallIcon(ok ? R.drawable.ic_check : R.drawable.ic_error)
                .setContentTitle(ok ? "录音已上传" : "录音上传失败")
                .setContentText(ok ? title + " · 正在转写并生成纪要" : message)
                .setContentIntent(content)
                .setAutoCancel(true)
                .setPriority(NotificationCompat.PRIORITY_DEFAULT);
        notify(context, notificationId(localId), builder.build());
    }

    public static void recordingSaved(Context context, String title, long durationMs) {
        NotificationCompat.Builder builder = new NotificationCompat.Builder(context,
                CHANNEL_DONE)
                .setSmallIcon(R.drawable.ic_check)
                .setContentTitle("录音已保存")
                .setContentText(title + " · " + Formats.duration(durationMs))
                .setContentIntent(openMain(context, "record"))
                .setAutoCancel(true);
        notify(context, 1200, builder.build());
    }

    public static void meetingReady(Context context, String title, String uid) {
        PendingIntent content = PendingIntent.getActivity(context, 1300,
                MeetingDetailActivity.intent(context, uid, title),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        NotificationCompat.Builder builder = new NotificationCompat.Builder(context,
                CHANNEL_DONE)
                .setSmallIcon(R.drawable.ic_check)
                .setContentTitle("纪要已生成")
                .setContentText(title)
                .setContentIntent(content)
                .setAutoCancel(true);
        notify(context, 1300, builder.build());
    }

    public static void loginExpired(Context context) {
        NotificationCompat.Builder builder = new NotificationCompat.Builder(context,
                CHANNEL_UPLOAD)
                .setSmallIcon(R.drawable.ic_error)
                .setContentTitle("登录已过期")
                .setContentText("录音仍保存在手机里，重新登录后会自动继续上传。")
                .setContentIntent(openMain(context, "record"))
                .setAutoCancel(true);
        notify(context, 1400, builder.build());
    }

    public static PendingIntent openMain(Context context, String tab) {
        Intent intent = new Intent(context, MainActivity.class)
                .putExtra("tab", tab)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        return PendingIntent.getActivity(context, 1500, intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    public static int notificationId(long localId) {
        return (int) (2100 + (localId % 500));
    }

    private static void notify(Context context, int id, Notification notification) {
        NotificationManager manager =
                (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) {
            return;
        }
        try {
            manager.notify(id, notification);
        } catch (SecurityException ignored) {
            // 通知权限被关闭时不影响录音与上传本身。
        }
    }
}
