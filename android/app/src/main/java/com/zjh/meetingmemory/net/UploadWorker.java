package com.zjh.meetingmemory.net;

import android.content.Context;

import androidx.annotation.NonNull;
import androidx.work.BackoffPolicy;
import androidx.work.Constraints;
import androidx.work.Data;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.WorkManager;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import com.zjh.meetingmemory.core.ApiClient;
import com.zjh.meetingmemory.core.AppPrefs;
import com.zjh.meetingmemory.data.LocalRecording;
import com.zjh.meetingmemory.data.LocalStore;
import com.zjh.meetingmemory.util.Notifications;

import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.util.concurrent.TimeUnit;

import okhttp3.Response;

public class UploadWorker extends Worker {

    private static final String KEY_ID = "recording_id";
    private static final int MAX_ATTEMPTS = 6;

    public UploadWorker(@NonNull Context context, @NonNull WorkerParameters params) {
        super(context, params);
    }

    public static void enqueue(Context context, long id, boolean replace) {
        AppPrefs prefs = new AppPrefs(context);
        Constraints constraints = new Constraints.Builder()
                .setRequiredNetworkType(prefs.wifiOnly()
                        ? NetworkType.UNMETERED : NetworkType.CONNECTED)
                .build();
        OneTimeWorkRequest request = new OneTimeWorkRequest.Builder(UploadWorker.class)
                .setInputData(new Data.Builder().putLong(KEY_ID, id).build())
                .setConstraints(constraints)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .addTag("mm_upload")
                .build();
        WorkManager.getInstance(context).enqueueUniqueWork(
                "mm-upload-" + id,
                replace ? ExistingWorkPolicy.REPLACE : ExistingWorkPolicy.KEEP,
                request);
    }

    /** 重新登录后，把因会话过期而暂停的录音重新排队。 */
    public static void resumeAuthPending(Context context) {
        AppPrefs prefs = new AppPrefs(context);
        LocalStore store = LocalStore.get(context);
        for (LocalRecording item : store.listAll()) {
            boolean auth = LocalRecording.AUTH.equals(item.state);
            boolean ready = LocalRecording.READY.equals(item.state);
            if (auth || (ready && prefs.autoUpload())) {
                if (auth) {
                    store.setState(item.id, LocalRecording.READY, "");
                }
                enqueue(context, item.id, true);
            }
        }
    }

    /** 进程被系统终止后，把停在“上传中”的录音重新排队。 */
    public static void recoverInterrupted(Context context) {
        try {
            LocalStore store = LocalStore.get(context);
            for (LocalRecording item : store.listAll()) {
                if (LocalRecording.UPLOADING.equals(item.state)) {
                    store.setState(item.id, LocalRecording.READY, "");
                    enqueue(context, item.id, false);
                }
            }
        } catch (Exception ignored) {
        }
    }

    @NonNull
    @Override
    public Result doWork() {
        long id = getInputData().getLong(KEY_ID, -1);
        if (id <= 0) {
            return Result.failure();
        }
        Context context = getApplicationContext();
        LocalStore store = LocalStore.get(context);
        AppPrefs prefs = new AppPrefs(context);
        LocalRecording item = store.get(id);
        if (item == null) {
            return Result.success();
        }
        if (LocalRecording.DONE.equals(item.state)
                || LocalRecording.UPLOADED.equals(item.state)
                || LocalRecording.PROCESSING.equals(item.state)) {
            return Result.success();
        }
        if (!prefs.isConfigured()) {
            store.setState(id, LocalRecording.AUTH, "登录已过期，请重新登录");
            Notifications.loginExpired(context);
            return Result.failure();
        }
        File file = new File(item.filePath);
        if (!file.isFile() || file.length() <= 44) {
            store.setState(id, LocalRecording.FAILED, "本机录音文件不存在或不完整");
            Notifications.uploadFinished(context, id, item.title, false,
                    "本机录音文件不存在或不完整", "");
            return Result.failure();
        }

        store.setUploading(id);
        Notifications.uploadProgress(context, id, item.title, 0);

        try (Response response = ApiClient.get(context).uploadSync(
                file, item.title, item.project, item.templateKey,
                recordedAt(item.startedAt), percent -> {
                    updateProgress(id, item.title, percent);
                })) {
            String body = response.body() == null ? "" : response.body().string();
            if (response.isSuccessful()) {
                String uid = "";
                try {
                    uid = new JSONObject(body).optString("uid", "");
                } catch (Exception ignored) {
                }
                if (uid.isEmpty()) {
                    return retryOrGiveUp(store, id, item.title,
                            "服务器未返回会议编号");
                }
                store.setUploaded(id, uid);
                Notifications.uploadFinished(context, id, item.title, true,
                        "", uid);
                StatusPollWorker.enqueue(context, id, uid);
                return Result.success();
            }

            int code = response.code();
            String message = ApiClient.errorMessage(body,
                    "上传失败（HTTP " + code + "）");
            if (code == 401) {
                store.setState(id, LocalRecording.AUTH, "登录已过期，请重新登录");
                Notifications.loginExpired(context);
                Notifications.uploadFinished(context, id, item.title, false,
                        "登录已过期，登录后会自动继续上传", "");
                return Result.failure();
            }
            if (code == 400 || code == 413 || code == 415 || code == 422) {
                store.setState(id, LocalRecording.FAILED, message);
                Notifications.uploadFinished(context, id, item.title, false,
                        message, "");
                return Result.failure();
            }
            return retryOrGiveUp(store, id, item.title, message);
        } catch (IOException e) {
            return retryOrGiveUp(store, id, item.title,
                    ApiClient.friendlyError(e));
        }
    }

    private Result retryOrGiveUp(LocalStore store, long id, String title,
                                 String message) {
        if (getRunAttemptCount() >= MAX_ATTEMPTS) {
            store.setState(id, LocalRecording.FAILED,
                    "多次上传失败：" + message + "（可手动重试）");
            Notifications.uploadFinished(getApplicationContext(), id, title,
                    false, "多次上传失败，可回到 App 手动重试", "");
            return Result.failure();
        }
        return Result.retry();
    }

    private void updateProgress(long id, String title, int percent) {
        setProgressAsync(new Data.Builder().putInt("progress", percent).build());
        if (percent % 5 == 0) {
            Notifications.uploadProgress(getApplicationContext(), id, title, percent);
        }
    }

    private String recordedAt(long millis) {
        if (millis <= 0) {
            return "";
        }
        return new java.text.SimpleDateFormat("yyyy-MM-dd HH:mm:ss",
                java.util.Locale.CHINA).format(new java.util.Date(millis));
    }
}
