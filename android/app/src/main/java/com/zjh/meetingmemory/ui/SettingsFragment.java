package com.zjh.meetingmemory.ui;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.PowerManager;
import android.provider.Settings;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.zjh.meetingmemory.R;
import com.zjh.meetingmemory.core.ApiClient;
import com.zjh.meetingmemory.core.AppPrefs;
import com.zjh.meetingmemory.databinding.FragmentSettingsBinding;
import com.zjh.meetingmemory.util.Formats;

import org.json.JSONObject;

import java.io.IOException;
import java.util.HashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class SettingsFragment extends Fragment {

    private FragmentSettingsBinding binding;
    private AppPrefs prefs;
    private ExecutorService executor;
    private ActivityResultLauncher<String> notificationPermission;

    @Override
    public void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        notificationPermission = registerForActivityResult(
                new ActivityResultContracts.RequestPermission(), granted -> updatePermissionUi());
    }

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentSettingsBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);
        prefs = new AppPrefs(requireContext());
        executor = Executors.newSingleThreadExecutor();

        binding.tvVersion.setText("会议记忆 Android " + versionName()
                + " · 后端与纪要生成运行在你自己服务器");
        binding.switchAutoUpload.setChecked(prefs.autoUpload());
        binding.switchWifiOnly.setChecked(prefs.wifiOnly());
        binding.switchSelfSigned.setChecked(prefs.allowSelfSigned());
        binding.etMaxMinutes.setText(String.valueOf(prefs.maxMinutes()));
        binding.etKeepDays.setText(String.valueOf(prefs.keepDays()));

        binding.switchAutoUpload.setOnCheckedChangeListener((button, checked) ->
                prefs.setAutoUpload(checked));
        binding.switchWifiOnly.setOnCheckedChangeListener((button, checked) ->
                prefs.setWifiOnly(checked));
        binding.switchSelfSigned.setOnCheckedChangeListener((button, checked) -> {
            if (checked && !prefs.allowSelfSigned()) {
                new MaterialAlertDialogBuilder(requireContext())
                        .setTitle("允许自签证书？")
                        .setMessage("开启后，App 将接受服务器提供的任意 HTTPS 证书。"
                                + "仅建议在自建内网服务器使用；公网地址请保持关闭。")
                        .setNegativeButton(R.string.cancel, (dialog, which) -> {
                            binding.switchSelfSigned.setChecked(false);
                        })
                        .setPositiveButton("开启", (dialog, which) -> {
                            prefs.setAllowSelfSigned(true);
                            ApiClient.reset();
                        })
                        .show();
            } else if (!checked) {
                prefs.setAllowSelfSigned(false);
                ApiClient.reset();
            }
        });

        binding.etMaxMinutes.addTextChangedListener(new SimpleWatcher(text -> {
            int value = parseInt(text, 360, 0, 480);
            prefs.setMaxMinutes(value);
        }));
        binding.etKeepDays.addTextChangedListener(new SimpleWatcher(text -> {
            int value = parseInt(text, 30, 0, 3650);
            prefs.setKeepDays(value);
        }));

        binding.btnTest.setOnClickListener(v -> testConnection());
        binding.btnRelogin.setOnClickListener(v -> startActivity(
                new Intent(requireContext(), LoginActivity.class)
                        .putExtra("from_settings", true)));
        binding.btnLogout.setOnClickListener(v -> confirmLogout());
        binding.btnNotification.setOnClickListener(v -> openNotificationSettings());
        binding.btnBattery.setOnClickListener(v -> openBatterySettings());

        loadAccount();
        updatePermissionUi();
    }

    private void loadAccount() {
        binding.tvServer.setText(prefs.baseUrl());
        binding.tvAccount.setText("账号：" + (prefs.username().isEmpty()
                ? "未登录" : prefs.username()));
        if (!prefs.isConfigured()) {
            binding.tvAccountStatus.setText("未登录，请重新登录服务器");
            binding.tvAccountStatus.setTextColor(
                    ContextCompat.getColor(requireContext(), R.color.red));
            return;
        }
        ApiClient.get(requireContext()).get("/api/me", new ApiClient.ApiCallback() {
            @Override
            public void onResponse(int code, String body) {
                if (binding == null || getActivity() == null) {
                    return;
                }
                getActivity().runOnUiThread(() -> {
                    if (code == 200) {
                        try {
                            JSONObject json = new JSONObject(body);
                            String role = json.optString("role", "user");
                            String label = "admin".equals(role) ? "管理员" : "成员";
                            binding.tvAccount.setText("账号：" + json.optString("username",
                                    prefs.username()) + " · " + label);
                            binding.tvAccountStatus.setText("登录状态正常 · "
                                    + Formats.fullDateTime(System.currentTimeMillis()));
                            binding.tvAccountStatus.setTextColor(
                                    ContextCompat.getColor(requireContext(), R.color.green));
                        } catch (Exception ignored) {
                        }
                    } else if (code == 401) {
                        binding.tvAccountStatus.setText("登录已过期，请重新登录");
                        binding.tvAccountStatus.setTextColor(
                                ContextCompat.getColor(requireContext(), R.color.red));
                    }
                });
            }

            @Override
            public void onFailure(IOException error) {
                if (binding == null || getActivity() == null) {
                    return;
                }
                getActivity().runOnUiThread(() -> {
                    binding.tvAccountStatus.setText("无法连接服务器："
                            + ApiClient.friendlyError(error));
                    binding.tvAccountStatus.setTextColor(
                            ContextCompat.getColor(requireContext(), R.color.red));
                });
            }
        });
    }

    private void testConnection() {
        String base = AppPrefs.normalizeBase(prefs.baseUrl());
        if (base.isEmpty()) {
            showTest("请先登录服务器", false, "");
            return;
        }
        binding.btnTest.setEnabled(false);
        showTest("正在测试…", null, "");
        boolean trust = prefs.allowSelfSigned();
        executor.execute(() -> {
            ApiClient.TestResult result = ApiClient.testConnection(
                    requireContext().getApplicationContext(), base, trust);
            if (binding == null || getActivity() == null) {
                return;
            }
            getActivity().runOnUiThread(() -> {
                binding.btnTest.setEnabled(true);
                showTest(result.message, result.ok, result.fingerprint);
            });
        });
    }

    private void showTest(String message, Boolean success, String fingerprint) {
        binding.tvTestResult.setVisibility(View.VISIBLE);
        String text = message;
        if (fingerprint != null && !fingerprint.isEmpty()) {
            text += "\n证书 SHA-256：" + fingerprint;
        }
        binding.tvTestResult.setText(text);
        int color = success == null
                ? ContextCompat.getColor(requireContext(), R.color.text_muted)
                : ContextCompat.getColor(requireContext(),
                success ? R.color.green : R.color.red);
        binding.tvTestResult.setTextColor(color);
    }

    private void confirmLogout() {
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle("退出登录？")
                .setMessage("本机录音不会被删除；重新登录后可继续上传。")
                .setNegativeButton(R.string.cancel, null)
                .setPositiveButton(R.string.logout, (dialog, which) -> {
                    String cookie = prefs.cookie();
                    if (!cookie.isEmpty() && prefs.isConfigured()) {
                        ApiClient.get(requireContext())
                                .postForm("/logout", new HashMap<>(),
                                        new ApiClient.ApiCallback() {
                                            @Override
                                            public void onResponse(int code, String body) {
                                            }

                                            @Override
                                            public void onFailure(IOException error) {
                                            }
                                        });
                    }
                    prefs.clearCookie();
                    ApiClient.reset();
                    startActivity(new Intent(requireContext(), LoginActivity.class));
                    requireActivity().finish();
                })
                .show();
    }

    private void openNotificationSettings() {
        if (Build.VERSION.SDK_INT >= 33
                && ContextCompat.checkSelfPermission(requireContext(),
                Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS);
            return;
        }
        Intent intent = new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                .putExtra(Settings.EXTRA_APP_PACKAGE, requireContext().getPackageName());
        try {
            startActivity(intent);
        } catch (Exception e) {
            Toast.makeText(requireContext(), "无法打开通知设置", Toast.LENGTH_SHORT).show();
        }
    }

    private void openBatterySettings() {
        PowerManager power = (PowerManager) requireContext()
                .getSystemService(android.content.Context.POWER_SERVICE);
        boolean ignoring = power != null
                && power.isIgnoringBatteryOptimizations(requireContext().getPackageName());
        if (!ignoring) {
            try {
                Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                        .setData(Uri.parse("package:" + requireContext().getPackageName()));
                startActivity(intent);
                return;
            } catch (Exception ignored) {
            }
        }
        try {
            startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));
        } catch (Exception e) {
            Toast.makeText(requireContext(), "无法打开电池优化设置", Toast.LENGTH_SHORT).show();
        }
    }

    private void updatePermissionUi() {
        if (binding == null) {
            return;
        }
        boolean notificationGranted = Build.VERSION.SDK_INT < 33
                || ContextCompat.checkSelfPermission(requireContext(),
                Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
        binding.btnNotification.setText(notificationGranted ? "已开启" : "去开启");
        PowerManager power = (PowerManager) requireContext()
                .getSystemService(android.content.Context.POWER_SERVICE);
        boolean ignoring = power != null
                && power.isIgnoringBatteryOptimizations(requireContext().getPackageName());
        binding.btnBattery.setText(ignoring ? "已允许后台" : "去设置");
    }

    private String versionName() {
        try {
            return requireContext().getPackageManager()
                    .getPackageInfo(requireContext().getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "1.0.0";
        }
    }

    private int parseInt(String text, int fallback, int min, int max) {
        try {
            int value = Integer.parseInt(text);
            return Math.max(min, Math.min(max, value));
        } catch (Exception e) {
            return fallback;
        }
    }

    @Override
    public void onResume() {
        super.onResume();
        if (binding != null) {
            binding.tvServer.setText(prefs.baseUrl());
            binding.switchSelfSigned.setChecked(prefs.allowSelfSigned());
            loadAccount();
            updatePermissionUi();
        }
    }

    @Override
    public void onDestroy() {
        if (executor != null) {
            executor.shutdownNow();
        }
        super.onDestroy();
    }

    private interface TextHandler {
        void onText(String text);
    }

    private static class SimpleWatcher implements android.text.TextWatcher {
        private final TextHandler handler;

        SimpleWatcher(TextHandler handler) {
            this.handler = handler;
        }

        @Override
        public void beforeTextChanged(CharSequence s, int start, int count, int after) {
        }

        @Override
        public void onTextChanged(CharSequence s, int start, int before, int count) {
        }

        @Override
        public void afterTextChanged(android.text.Editable s) {
            handler.onText(s == null ? "" : s.toString());
        }
    }
}
