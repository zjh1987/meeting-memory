package com.zjh.meetingmemory.ui;

import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;

import com.zjh.meetingmemory.R;
import com.zjh.meetingmemory.core.ApiClient;
import com.zjh.meetingmemory.core.AppPrefs;
import com.zjh.meetingmemory.databinding.ActivityLoginBinding;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class LoginActivity extends AppCompatActivity {

    private ActivityLoginBinding binding;
    private AppPrefs prefs;
    private ExecutorService executor;
    private boolean busy;
    private boolean fromSettings;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        binding = ActivityLoginBinding.inflate(getLayoutInflater());
        setContentView(binding.getRoot());

        prefs = new AppPrefs(this);
        executor = Executors.newSingleThreadExecutor();
        fromSettings = getIntent().getBooleanExtra("from_settings", false);

        binding.etUrl.setText(prefs.baseUrl().isEmpty()
                ? "http://192.168.110.14:8000" : prefs.baseUrl());
        binding.etUsername.setText(prefs.username().isEmpty()
                ? "admin" : prefs.username());
        binding.cbSelfSigned.setChecked(prefs.allowSelfSigned());

        binding.btnTest.setOnClickListener(view -> testConnection());
        binding.btnLogin.setOnClickListener(view -> login());
    }

    private void testConnection() {
        if (busy) {
            return;
        }
        String base = AppPrefs.normalizeBase(binding.etUrl.getText().toString());
        if (base.isEmpty()) {
            showResult("请先填写服务器地址", false);
            return;
        }
        hideKeyboard();
        setBusy(true, "正在连接…");
        boolean trust = binding.cbSelfSigned.isChecked();
        executor.execute(() -> {
            ApiClient.TestResult result = ApiClient.testConnection(
                    getApplicationContext(), base, trust);
            runOnUiThread(() -> {
                setBusy(false, "");
                String text = result.message;
                if (result.fingerprint != null && !result.fingerprint.isEmpty()) {
                    text += "\n证书 SHA-256：" + result.fingerprint;
                }
                showResult(text, result.ok);
            });
        });
    }

    private void login() {
        if (busy) {
            return;
        }
        String base = AppPrefs.normalizeBase(binding.etUrl.getText().toString());
        String username = binding.etUsername.getText().toString().trim();
        String password = binding.etPassword.getText().toString();
        if (base.isEmpty()) {
            showResult("请填写服务器地址", false);
            return;
        }
        if (username.isEmpty()) {
            showResult("请填写账号", false);
            return;
        }
        if (password.isEmpty()) {
            showResult("请填写密码", false);
            return;
        }
        hideKeyboard();
        setBusy(true, "正在登录…");
        boolean trust = binding.cbSelfSigned.isChecked();
        executor.execute(() -> {
            ApiClient.LoginResult result = ApiClient.login(
                    getApplicationContext(), base, username, password, trust);
            runOnUiThread(() -> {
                setBusy(false, "");
                if (!result.ok) {
                    showResult(result.message, false);
                    return;
                }
                prefs.setBaseUrl(base);
                prefs.setUsername(username);
                prefs.setAllowSelfSigned(trust);
                ApiClient.reset();
                com.zjh.meetingmemory.net.UploadWorker.resumeAuthPending(
                        getApplicationContext());
                com.zjh.meetingmemory.net.StatusPollWorker.recoverPending(
                        getApplicationContext());
                Toast.makeText(this, "登录成功", Toast.LENGTH_SHORT).show();
                if (fromSettings) {
                    setResult(RESULT_OK);
                    finish();
                } else {
                    startActivity(new Intent(this, MainActivity.class));
                    finish();
                }
            });
        });
    }

    private void setBusy(boolean value, String hint) {
        busy = value;
        binding.btnLogin.setEnabled(!value);
        binding.btnTest.setEnabled(!value);
        binding.progress.setVisibility(value ? View.VISIBLE : View.GONE);
        if (value && !hint.isEmpty()) {
            showResult(hint, null);
        }
    }

    private void showResult(String text, Boolean success) {
        binding.tvTestResult.setVisibility(View.VISIBLE);
        binding.tvTestResult.setText(text);
        int color = success == null
                ? getColor(R.color.text_muted)
                : getColor(success ? R.color.green : R.color.red);
        binding.tvTestResult.setTextColor(color);
    }

    private void hideKeyboard() {
        InputMethodManager manager =
                (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        if (manager != null) {
            manager.hideSoftInputFromWindow(binding.getRoot().getWindowToken(), 0);
        }
    }

    @Override
    protected void onDestroy() {
        executor.shutdownNow();
        super.onDestroy();
    }
}
