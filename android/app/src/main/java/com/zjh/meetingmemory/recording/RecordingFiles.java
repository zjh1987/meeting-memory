package com.zjh.meetingmemory.recording;

import android.content.Context;
import android.os.Environment;

import com.zjh.meetingmemory.core.AppPrefs;
import com.zjh.meetingmemory.core.Defaults;
import com.zjh.meetingmemory.core.Models;
import com.zjh.meetingmemory.data.LocalRecording;
import com.zjh.meetingmemory.data.LocalStore;
import com.zjh.meetingmemory.net.UploadWorker;
import com.zjh.meetingmemory.util.Formats;

import java.io.File;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.List;
import java.util.Locale;

public final class RecordingFiles {

    private RecordingFiles() {
    }

    public static File dir(Context context) {
        File base = context.getExternalFilesDir(Environment.DIRECTORY_MUSIC);
        if (base == null) {
            base = new File(context.getFilesDir(), "recordings");
        } else {
            base = new File(base, "recordings");
        }
        if (!base.exists()) {
            base.mkdirs();
        }
        return base;
    }

    public static File newFile(Context context) {
        String stamp = new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.CHINA)
                .format(new Date());
        File file = new File(dir(context), "rec_" + stamp + ".wav");
        int index = 1;
        while (file.exists()) {
            file = new File(dir(context), "rec_" + stamp + "_" + index + ".wav");
            index++;
        }
        return file;
    }

    public static File newImportedFile(Context context, String extension) {
        String stamp = new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.CHINA)
                .format(new Date());
        String ext = extension == null || extension.isEmpty() ? ".audio" : extension;
        if (!ext.startsWith(".")) {
            ext = "." + ext;
        }
        File file = new File(dir(context), "import_" + stamp + ext);
        int index = 1;
        while (file.exists()) {
            file = new File(dir(context), "import_" + stamp + "_" + index + ext);
            index++;
        }
        return file;
    }

    public static void recoverOrphans(Context context) {
        File folder = dir(context);
        File[] files = folder.listFiles((directory, name) -> name.endsWith(".wav"));
        if (files == null || files.length == 0) {
            return;
        }
        LocalStore store = LocalStore.get(context);
        AppPrefs prefs = new AppPrefs(context);
        for (File file : files) {
            if (RecordingState.active && file.getAbsolutePath().equals(RecordingState.filePath)) {
                continue;
            }
            LocalRecording existing = store.findByPath(file.getAbsolutePath());
            if (existing != null && !LocalRecording.RECORDING.equals(existing.state)) {
                continue;
            }
            long duration = WavRepair.repair(file);
            if (existing != null) {
                if (file.length() <= 44) {
                    store.setState(existing.id, LocalRecording.FAILED,
                            "录音文件为空，可能未成功启动");
                } else {
                    store.finishRecording(existing.id, duration, file.length());
                    if (prefs.isConfigured() && prefs.autoUpload()) {
                        try {
                            UploadWorker.enqueue(context, existing.id, false);
                        } catch (Exception ignored) {
                        }
                    }
                }
                continue;
            }
            if (file.length() <= 44) {
                continue;
            }
            LocalRecording item = new LocalRecording();
            item.title = "恢复的录音 " + Formats.dateTime(file.lastModified());
            item.project = prefs.lastProject().isEmpty() ? "未分类" : prefs.lastProject();
            item.templateKey = prefs.lastTemplate();
            item.templateName = templateName(item.templateKey);
            item.filePath = file.getAbsolutePath();
            item.startedAt = file.lastModified();
            item.durationMs = duration;
            item.sizeBytes = file.length();
            item.state = LocalRecording.READY;
            long id = store.insert(item);
            if (prefs.isConfigured() && prefs.autoUpload() && id > 0) {
                try {
                    UploadWorker.enqueue(context, id, false);
                } catch (Exception ignored) {
                }
            }
        }
    }

    public static void cleanupOld(Context context) {
        AppPrefs prefs = new AppPrefs(context);
        int days = prefs.keepDays();
        if (days <= 0) {
            return;
        }
        long cutoff = System.currentTimeMillis() - days * 86400000L;
        LocalStore store = LocalStore.get(context);
        List<LocalRecording> items = store.listFinishedOlderThan(cutoff);
        for (LocalRecording item : items) {
            File file = new File(item.filePath);
            if (file.exists()) {
                //noinspection ResultOfMethodCallIgnored
                file.delete();
            }
            store.delete(item.id);
        }
    }

    public static String templateName(String key) {
        for (Models.Template template : Defaults.templates()) {
            if (template.key.equals(key)) {
                return template.name;
            }
        }
        return "常规会议";
    }
}
