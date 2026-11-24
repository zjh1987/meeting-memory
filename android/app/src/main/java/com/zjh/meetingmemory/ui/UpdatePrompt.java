package com.zjh.meetingmemory.ui;

import android.app.Activity;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.ProgressBar;
import android.widget.Toast;

import androidx.appcompat.app.AlertDialog;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.zjh.meetingmemory.core.AppPrefs;
import com.zjh.meetingmemory.core.AppUpdater;

import java.io.File;
import java.util.Locale;

/** 检查更新、下载进度与覆盖安装的界面流程。 */
public final class UpdatePrompt {

    private static final long CHECK_INTERVAL_MS = 12 * 60 * 60 * 1000L;

    private UpdatePrompt() {
    }

    public static void check(Activity activity, boolean manual) {
        if (activity == null || activity.isFinishing()) {
            return;
        }
        AppPrefs prefs = new AppPrefs(activity);
        long now = System.currentTimeMillis();
        if (!manual && now - prefs.lastUpdateCheck() < CHECK_INTERVAL_MS) {
            return;
        }
        prefs.setLastUpdateCheck(now);
        AppUpdater.checkAsync(activity, (info, error) -> activity.runOnUiThread(() -> {
            if (activity.isFinishing()) {
                return;
            }
            if (error != null) {
                if (manual) {
                    Toast.makeText(activity, "检查更新失败：" + error,
                            Toast.LENGTH_LONG).show();
                }
                return;
            }
            if (info == null || !info.available
                    || info.versionCode <= AppUpdater.currentVersionCode(activity)) {
                if (manual) {
                    String version = AppUpdater.currentVersionName(activity);
                    Toast.makeText(activity,
                            "已是最新版本" + (version.isEmpty() ? "" : " v" + version),
                            Toast.LENGTH_SHORT).show();
                }
                return;
            }
            prompt(activity, info);
        }));
    }

    private static void prompt(Activity activity, AppUpdater.Info info) {
        String size = info.size > 0
                ? String.format(Locale.CHINA, "\n\n安装包 %.1f MB",
                info.size / 1024.0 / 1024.0)
                : "";
        String notes = info.notes == null || info.notes.isEmpty()
                ? "包含问题修复与体验优化。" : info.notes;
        new MaterialAlertDialogBuilder(activity)
                .setTitle("发现新版本 v" + info.versionName)
                .setMessage(notes + size + "\n\n升级会直接覆盖安装，本机录音不会丢失。")
                .setNegativeButton("稍后", null)
                .setPositiveButton("立即升级", (dialog, which) -> download(activity, info))
                .show();
    }

    private static void download(Activity activity, AppUpdater.Info info) {
        ProgressBar bar = new ProgressBar(activity, null,
                android.R.attr.progressBarStyleHorizontal);
        bar.setMax(100);
        bar.setProgress(0);
        int padding = (int) (20 * activity.getResources().getDisplayMetrics().density);
        FrameLayout container = new FrameLayout(activity);
        container.setPadding(padding, padding / 2, padding, 0);
        container.addView(bar, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));
        AlertDialog dialog = new MaterialAlertDialogBuilder(activity)
                .setTitle("正在下载更新")
                .setMessage("请保持网络连接，下载完成后会自动打开安装界面。")
                .setView(container)
                .setCancelable(false)
                .create();
        dialog.show();
        AppUpdater.downloadAsync(activity, info, new AppUpdater.DownloadCallback() {
            @Override
            public void onProgress(int percent) {
                activity.runOnUiThread(() -> {
                    if (dialog.isShowing()) {
                        bar.setProgress(percent);
                    }
                });
            }

            @Override
            public void onDone(File file, String error) {
                activity.runOnUiThread(() -> {
                    if (dialog.isShowing()) {
                        dialog.dismiss();
                    }
                    if (activity.isFinishing()) {
                        return;
                    }
                    if (error != null) {
                        Toast.makeText(activity, "下载失败：" + error,
                                Toast.LENGTH_LONG).show();
                        return;
                    }
                    AppUpdater.install(activity, file);
                });
            }
        });
    }
}
