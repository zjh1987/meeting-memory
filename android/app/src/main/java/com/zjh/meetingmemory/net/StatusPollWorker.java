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
import com.zjh.meetingmemory.data.LocalRecording;
import com.zjh.meetingmemory.data.LocalStore;
import com.zjh.meetingmemory.util.Notifications;

import org.json.JSONObject;

import java.util.concurrent.TimeUnit;

import okhttp3.Response;

/** 上传完成后在后台轮询服务器处理状态，完成时发通知。 */
public class StatusPollWorker extends Worker {

    private static final String KEY_ID = "recording_id";
    private static final String KEY_UID = "server_uid";
    private static final int MAX_ATTEMPTS = 60;

    public StatusPollWorker(@NonNull Context context, @NonNull WorkerParameters params) {
        super(context, params);
    }

    public static void enqueue(Context context, long localId, String uid) {
        OneTimeWorkRequest request = new OneTimeWorkRequest.Builder(StatusPollWorker.class)
                .setInputData(new Data.Builder()
                        .putLong(KEY_ID, localId)
                        .putString(KEY_UID, uid)
                        .build())
                .setInitialDelay(25, TimeUnit.SECONDS)
                .setBackoffCriteria(BackoffPolicy.LINEAR, 30, TimeUnit.SECONDS)
                .setConstraints(new Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build())
                .addTag("mm_status")
                .build();
        WorkManager.getInstance(context).enqueueUniqueWork(
                "mm-status-" + uid, ExistingWorkPolicy.REPLACE, request);
    }

    /** App 重启后继续跟踪已经上传的录音。 */
    public static void recoverPending(Context context) {
        try {
            LocalStore store = LocalStore.get(context);
            for (LocalRecording item : store.listAll()) {
                if (item.hasServerUid()
                        && (LocalRecording.UPLOADED.equals(item.state)
                        || LocalRecording.PROCESSING.equals(item.state))) {
                    enqueue(context, item.id, item.serverUid);
                }
            }
        } catch (Exception ignored) {
        }
    }

    @NonNull
    @Override
    public Result doWork() {
        long localId = getInputData().getLong(KEY_ID, -1);
        String uid = getInputData().getString(KEY_UID);
        if (localId <= 0 || uid == null || uid.isEmpty()) {
            return Result.success();
        }
        Context context = getApplicationContext();
        LocalStore store = LocalStore.get(context);
        LocalRecording item = store.get(localId);
        if (item == null || LocalRecording.DONE.equals(item.state)
                || LocalRecording.FAILED.equals(item.state)) {
            return Result.success();
        }
        try (Response response = ApiClient.get(context)
                .getSync("/api/meetings/" + uid + "/status")) {
            if (response.code() == 401) {
                return Result.success();
            }
            if (!response.isSuccessful()) {
                return shouldContinue() ? Result.retry() : Result.success();
            }
            String body = response.body() == null ? "" : response.body().string();
            JSONObject json = new JSONObject(body);
            String status = json.optString("status", "");
            if ("done".equals(status)) {
                store.setServerState(localId, LocalRecording.DONE, "", uid);
                Notifications.meetingReady(context, item.title, uid);
                return Result.success();
            }
            if ("failed".equals(status)) {
                String error = json.optString("error_msg",
                        "服务器处理失败，可在 Web 后台重试");
                store.setServerState(localId, LocalRecording.FAILED, error, uid);
                Notifications.uploadFinished(context, localId, item.title, false,
                        error, uid);
                return Result.success();
            }
            store.setServerState(localId, LocalRecording.PROCESSING,
                    json.optString("error_msg", ""), uid);
            return shouldContinue() ? Result.retry() : Result.success();
        } catch (Exception e) {
            return shouldContinue() ? Result.retry() : Result.success();
        }
    }

    private boolean shouldContinue() {
        return getRunAttemptCount() < MAX_ATTEMPTS;
    }
}
