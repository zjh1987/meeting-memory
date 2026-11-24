package com.zjh.meetingmemory.core;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.widget.Toast;

import androidx.core.content.FileProvider;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import okhttp3.Request;
import okhttp3.Response;

/**
 * 应用内升级：从自己的服务器读取最新版本并下载 APK。
 * 只覆盖安装，不经过应用商店，也不需要卸载旧版。
 */
public final class AppUpdater {

    public static class Info {
        public boolean available;
        public int versionCode;
        public String versionName = "";
        public String notes = "";
        public String url = "";
        public String sha256 = "";
        public long size;

        static Info parse(String body) throws Exception {
            JSONObject json = new JSONObject(body);
            Info info = new Info();
            info.available = json.optBoolean("available", false);
            info.versionCode = json.optInt("version_code", 0);
            info.versionName = json.optString("version_name", "");
            info.notes = json.optString("notes", "");
            info.url = json.optString("url", "");
            info.sha256 = json.optString("sha256", "");
            info.size = json.optLong("size", 0);
            if (info.url.isEmpty() || info.versionCode <= 0) {
                info.available = false;
            }
            return info;
        }
    }

    public interface CheckCallback {
        void onResult(Info info, String error);
    }

    public interface DownloadCallback {
        void onProgress(int percent);

        void onDone(File file, String error);
    }

    private static final ExecutorService EXECUTOR = Executors.newSingleThreadExecutor();

    private AppUpdater() {
    }

    public static int currentVersionCode(Context context) {
        try {
            PackageInfo info = context.getPackageManager()
                    .getPackageInfo(context.getPackageName(), 0);
            if (Build.VERSION.SDK_INT >= 28) {
                return (int) info.getLongVersionCode();
            }
            return info.versionCode;
        } catch (Exception e) {
            return 0;
        }
    }

    public static String currentVersionName(Context context) {
        try {
            return context.getPackageManager()
                    .getPackageInfo(context.getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "";
        }
    }

    public static void checkAsync(Context context, CheckCallback callback) {
        Context app = context.getApplicationContext();
        EXECUTOR.execute(() -> {
            try {
                String body;
                try (Response response = ApiClient.get(app)
                        .getSync("/api/app/android/latest")) {
                    if (!response.isSuccessful()) {
                        throw new IOException("服务器返回 " + response.code());
                    }
                    body = response.body() == null ? "" : response.body().string();
                }
                callback.onResult(Info.parse(body), null);
            } catch (Exception error) {
                callback.onResult(null, ApiClient.friendlyError(error));
            }
        });
    }

    public static void downloadAsync(Context context, Info info,
                                     DownloadCallback callback) {
        Context app = context.getApplicationContext();
        EXECUTOR.execute(() -> {
            String base = new AppPrefs(app).baseUrl();
            if (base.isEmpty()) {
                callback.onDone(null, "服务器地址为空，请先登录");
                return;
            }
            File dir = new File(app.getCacheDir(), "updates");
            if (!dir.isDirectory() && !dir.mkdirs()) {
                callback.onDone(null, "无法创建下载目录");
                return;
            }
            File target = new File(dir, "meeting-memory-latest.apk");
            File part = new File(dir, "meeting-memory-latest.apk.part");
            Request request = new Request.Builder().url(base + info.url).get().build();
            try (Response response = ApiClient.get(app).http()
                    .newCall(request).execute()) {
                if (!response.isSuccessful() || response.body() == null) {
                    throw new IOException("服务器返回 " + response.code());
                }
                long total = response.body().contentLength();
                if (total <= 0) {
                    total = info.size;
                }
                long read = 0;
                int lastPercent = -5;
                try (InputStream input = response.body().byteStream();
                     FileOutputStream output = new FileOutputStream(part)) {
                    byte[] buffer = new byte[64 * 1024];
                    int count;
                    while ((count = input.read(buffer)) != -1) {
                        output.write(buffer, 0, count);
                        read += count;
                        if (total > 0) {
                            int percent = (int) (read * 100 / total);
                            if (percent - lastPercent >= 2) {
                                lastPercent = percent;
                                callback.onProgress(Math.min(percent, 100));
                            }
                        }
                    }
                }
                if (read == 0) {
                    throw new IOException("安装包为空");
                }
                if (info.sha256 != null && !info.sha256.isEmpty()) {
                    String actual = sha256(part);
                    if (!actual.equalsIgnoreCase(info.sha256)) {
                        throw new IOException("安装包校验失败，请重试");
                    }
                }
                if (target.exists() && !target.delete()) {
                    throw new IOException("无法覆盖旧安装包");
                }
                if (!part.renameTo(target)) {
                    throw new IOException("无法保存安装包");
                }
                callback.onProgress(100);
                callback.onDone(target, null);
            } catch (Exception error) {
                //noinspection ResultOfMethodCallIgnored
                part.delete();
                callback.onDone(null, ApiClient.friendlyError(error));
            }
        });
    }

    public static boolean install(Activity activity, File apk) {
        if (Build.VERSION.SDK_INT >= 26
                && !activity.getPackageManager().canRequestPackageInstalls()) {
            Toast.makeText(activity,
                    "请允许本应用安装未知来源应用，然后重新点击升级",
                    Toast.LENGTH_LONG).show();
            try {
                activity.startActivity(new Intent(
                        Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:" + activity.getPackageName())));
            } catch (Exception ignored) {
            }
            return false;
        }
        Uri uri = FileProvider.getUriForFile(activity,
                activity.getPackageName() + ".files", apk);
        Intent intent = new Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        activity.startActivity(intent);
        return true;
    }

    private static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = new java.io.FileInputStream(file)) {
            byte[] buffer = new byte[64 * 1024];
            int count;
            while ((count = input.read(buffer)) != -1) {
                digest.update(buffer, 0, count);
            }
        }
        byte[] out = digest.digest();
        StringBuilder builder = new StringBuilder();
        for (byte value : out) {
            builder.append(String.format(Locale.ROOT, "%02x", value));
        }
        return builder.toString();
    }
}
