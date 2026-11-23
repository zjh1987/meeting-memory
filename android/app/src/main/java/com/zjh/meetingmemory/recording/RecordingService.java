package com.zjh.meetingmemory.recording;

import android.Manifest;
import android.app.Notification;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.AudioManager;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.widget.Toast;

import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;

import com.zjh.meetingmemory.core.AppPrefs;
import com.zjh.meetingmemory.data.LocalRecording;
import com.zjh.meetingmemory.data.LocalStore;
import com.zjh.meetingmemory.net.UploadWorker;
import com.zjh.meetingmemory.util.Formats;
import com.zjh.meetingmemory.util.Notifications;

import java.io.File;

public class RecordingService extends Service implements WavRecorder.Listener {

    public static final String ACTION_START = "com.zjh.meetingmemory.action.START";
    public static final String ACTION_PAUSE = "com.zjh.meetingmemory.action.PAUSE";
    public static final String ACTION_RESUME = "com.zjh.meetingmemory.action.RESUME";
    public static final String ACTION_STOP = "com.zjh.meetingmemory.action.STOP";

    public static final String EXTRA_TITLE = "title";
    public static final String EXTRA_PROJECT = "project";
    public static final String EXTRA_TEMPLATE_KEY = "template_key";
    public static final String EXTRA_TEMPLATE_NAME = "template_name";
    public static final String EXTRA_MAX_MINUTES = "max_minutes";

    private static final long MIN_FREE_BYTES = 300L * 1024 * 1024;
    private static final long CRITICAL_FREE_BYTES = 120L * 1024 * 1024;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable ticker = this::tick;

    private AppPrefs prefs;
    private LocalStore store;
    private AudioManager audioManager;
    private PowerManager.WakeLock wakeLock;

    private WavRecorder recorder;
    private File file;
    private long rowId = -1;
    private String meetingTitle = "";
    private String project = "";
    private String templateKey = "standard";
    private String templateName = "常规会议";
    private int maxMinutes = 360;
    private boolean finishing;
    private boolean pausedByCall;
    private long lastStorageCheck;

    public static boolean isRunning() {
        return RecordingState.active;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        prefs = new AppPrefs(this);
        store = LocalStore.get(this);
        audioManager = (AudioManager) getSystemService(Context.AUDIO_SERVICE);
        Notifications.ensureChannels(this);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? null : intent.getAction();
        if (ACTION_START.equals(action)) {
            if (RecordingState.active) {
                return START_NOT_STICKY;
            }
            try {
                Notification notification = Notifications.recording(this,
                        "准备录音", false, System.currentTimeMillis(), 0);
                startForeground(Notifications.ID_RECORDING, notification);
            } catch (Exception e) {
                Toast.makeText(this, "无法启动录音服务：" + e.getMessage(),
                        Toast.LENGTH_LONG).show();
                stopSelf();
                return START_NOT_STICKY;
            }
            begin(intent);
        } else if (ACTION_PAUSE.equals(action)) {
            pause(true);
        } else if (ACTION_RESUME.equals(action)) {
            resume(true);
        } else if (ACTION_STOP.equals(action)) {
            finishRecording(true, "录音已结束，正在保存");
        }
        return START_NOT_STICKY;
    }

    private void begin(Intent intent) {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            Toast.makeText(this, "没有麦克风权限，无法录音", Toast.LENGTH_LONG).show();
            stopForegroundCompat();
            stopSelf();
            return;
        }
        if (RecordingFiles.dir(this).getUsableSpace() < MIN_FREE_BYTES) {
            Toast.makeText(this, "手机存储空间不足，请先清理后再录音",
                    Toast.LENGTH_LONG).show();
            stopForegroundCompat();
            stopSelf();
            return;
        }

        meetingTitle = safe(intent.getStringExtra(EXTRA_TITLE),
                "未命名会议");
        project = safe(intent.getStringExtra(EXTRA_PROJECT),
                prefs.lastProject().isEmpty() ? "未分类" : prefs.lastProject());
        templateKey = safe(intent.getStringExtra(EXTRA_TEMPLATE_KEY),
                prefs.lastTemplate());
        templateName = safe(intent.getStringExtra(EXTRA_TEMPLATE_NAME),
                RecordingFiles.templateName(templateKey));
        maxMinutes = intent.getIntExtra(EXTRA_MAX_MINUTES, prefs.maxMinutes());
        if (maxMinutes < 0) {
            maxMinutes = 0;
        }

        file = RecordingFiles.newFile(this);
        LocalRecording item = new LocalRecording();
        item.title = meetingTitle;
        item.project = project;
        item.templateKey = templateKey;
        item.templateName = templateName;
        item.filePath = file.getAbsolutePath();
        item.startedAt = System.currentTimeMillis();
        item.state = LocalRecording.RECORDING;
        rowId = store.insert(item);

        RecordingState.begin(rowId, file.getAbsolutePath(), meetingTitle,
                project, templateKey, templateName);
        recorder = new WavRecorder(file, this);
        try {
            recorder.start();
        } catch (Exception e) {
            store.setState(rowId, LocalRecording.FAILED,
                    e.getMessage() == null ? "录音启动失败" : e.getMessage());
            RecordingState.finish();
            Toast.makeText(this, "录音启动失败：" + e.getMessage(),
                    Toast.LENGTH_LONG).show();
            stopForegroundCompat();
            stopSelf();
            return;
        }

        acquireWakeLock();
        Notifications.updateRecording(this, meetingTitle, false,
                RecordingState.startedAt, 0);
        handler.postDelayed(ticker, 1000);
        Toast.makeText(this, "录音已开始，锁屏也会继续", Toast.LENGTH_SHORT).show();
    }

    private void tick() {
        if (!RecordingState.active || recorder == null) {
            return;
        }
        long elapsed = RecordingState.elapsedMs();
        if (maxMinutes > 0 && elapsed >= maxMinutes * 60000L) {
            finishRecording(true, "已达到最长录音时长，已自动保存");
            return;
        }
        long now = System.currentTimeMillis();
        if (now - lastStorageCheck > 30000) {
            lastStorageCheck = now;
            if (RecordingFiles.dir(this).getUsableSpace() < CRITICAL_FREE_BYTES) {
                finishRecording(true, "存储空间不足，录音已自动保存");
                return;
            }
        }
        if (!RecordingState.paused && isInCall()) {
            pausedByCall = true;
            pause(false);
            Toast.makeText(this, "检测到来电，录音已自动暂停", Toast.LENGTH_SHORT).show();
        } else if (RecordingState.paused && pausedByCall && !isInCall()) {
            pausedByCall = false;
            resume(false);
            Toast.makeText(this, "通话结束，录音已继续", Toast.LENGTH_SHORT).show();
        }
        handler.postDelayed(ticker, 1000);
    }

    private boolean isInCall() {
        if (audioManager == null) {
            return false;
        }
        int mode = audioManager.getMode();
        return mode == AudioManager.MODE_IN_CALL
                || mode == AudioManager.MODE_IN_COMMUNICATION;
    }

    private void pause(boolean byUser) {
        if (recorder == null || !RecordingState.active || RecordingState.paused) {
            return;
        }
        recorder.pause();
        RecordingState.pause();
        if (!byUser) {
            pausedByCall = true;
        }
        Notifications.updateRecording(this, meetingTitle, true,
                RecordingState.startedAt, RecordingState.elapsedMs());
        if (byUser) {
            Toast.makeText(this, "录音已暂停", Toast.LENGTH_SHORT).show();
        }
    }

    private void resume(boolean byUser) {
        if (recorder == null || !RecordingState.active || !RecordingState.paused) {
            return;
        }
        recorder.resume();
        RecordingState.resume();
        pausedByCall = false;
        Notifications.updateRecording(this, meetingTitle, false,
                RecordingState.startedAt, RecordingState.elapsedMs());
        if (byUser) {
            Toast.makeText(this, "录音已继续", Toast.LENGTH_SHORT).show();
        }
    }

    private void finishRecording(boolean enqueueUpload, String message) {
        if (finishing) {
            return;
        }
        finishing = true;
        handler.removeCallbacks(ticker);

        long duration = 0;
        long size = 0;
        String error = "";
        if (recorder != null) {
            error = recorder.error();
            recorder.stop();
            duration = recorder.audioMs();
            if (file != null) {
                size = file.length();
            }
        }
        if (duration <= 0) {
            duration = RecordingState.elapsedMs();
        }
        boolean hasAudio = file != null && file.isFile() && file.length() > 44;
        if (rowId > 0) {
            if (hasAudio) {
                store.finishRecording(rowId, duration, size);
            } else {
                store.setState(rowId, LocalRecording.FAILED,
                        error.isEmpty() ? "没有录到音频，请检查麦克风" : error);
            }
        }
        long finishedRow = rowId;
        String finishedTitle = meetingTitle;
        RecordingState.finish();
        releaseWakeLock();
        stopForegroundCompat();
        stopSelf();

        if (!hasAudio) {
            Toast.makeText(this, "录音失败：没有录到音频，请检查麦克风权限或占用情况",
                    Toast.LENGTH_LONG).show();
            return;
        }
        if (enqueueUpload && prefs.autoUpload() && finishedRow > 0) {
            UploadWorker.enqueue(this, finishedRow, false);
        } else {
            Notifications.recordingSaved(this, finishedTitle, duration);
        }
        Toast.makeText(this, message + " · " + Formats.duration(duration),
                Toast.LENGTH_SHORT).show();
    }

    private void acquireWakeLock() {
        try {
            PowerManager power = (PowerManager) getSystemService(Context.POWER_SERVICE);
            if (power == null) {
                return;
            }
            wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,
                    "MeetingMemory:recording");
            wakeLock.setReferenceCounted(false);
            long timeout = maxMinutes > 0
                    ? maxMinutes * 60000L + 60000L
                    : 6 * 3600_000L;
            wakeLock.acquire(timeout);
        } catch (Exception ignored) {
        }
    }

    private void releaseWakeLock() {
        try {
            if (wakeLock != null && wakeLock.isHeld()) {
                wakeLock.release();
            }
        } catch (Exception ignored) {
        }
        wakeLock = null;
    }

    private void stopForegroundCompat() {
        stopForeground(STOP_FOREGROUND_REMOVE);
    }

    private String safe(String value, String fallback) {
        return value == null || value.trim().isEmpty() ? fallback : value.trim();
    }

    @Override
    public void onAmplitude(float level) {
        RecordingState.amplitude = level;
    }

    @Override
    public void onError(String message) {
        handler.post(() -> {
            if (!finishing) {
                finishRecording(prefs.autoUpload(), "录音异常结束，已保存可用部分");
            }
        });
    }

    @Override
    public void onDestroy() {
        handler.removeCallbacks(ticker);
        if (!finishing && RecordingState.active) {
            finishRecording(prefs.autoUpload(), "录音服务结束，已保存");
        }
        releaseWakeLock();
        super.onDestroy();
    }

    @Nullable
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
