package com.zjh.meetingmemory.ui;

import android.annotation.SuppressLint;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Bundle;
import android.webkit.CookieManager;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;

import com.zjh.meetingmemory.R;
import com.zjh.meetingmemory.core.AppPrefs;
import com.zjh.meetingmemory.databinding.ActivityMeetingDetailBinding;

public class MeetingDetailActivity extends AppCompatActivity {

    private static final String EXTRA_UID = "uid";
    private static final String EXTRA_TITLE = "title";

    private ActivityMeetingDetailBinding binding;
    private AppPrefs prefs;
    private String uid;

    public static Intent intent(Context context, String uid, String title) {
        return new Intent(context, MeetingDetailActivity.class)
                .putExtra(EXTRA_UID, uid)
                .putExtra(EXTRA_TITLE, title)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        binding = ActivityMeetingDetailBinding.inflate(getLayoutInflater());
        setContentView(binding.getRoot());
        prefs = new AppPrefs(this);
        uid = getIntent().getStringExtra(EXTRA_UID);
        if (uid == null || uid.isEmpty()) {
            finish();
            return;
        }
        String title = getIntent().getStringExtra(EXTRA_TITLE);
        binding.tvTitle.setText(title == null || title.isEmpty() ? "会议详情" : title);
        binding.btnBack.setOnClickListener(view -> finish());
        binding.btnRefresh.setOnClickListener(view -> {
            syncCookie();
            binding.webView.reload();
        });
        binding.swipe.setOnRefreshListener(() -> binding.webView.reload());
        setupWebView();
        syncCookie();
        binding.webView.loadUrl(prefs.baseUrl() + "/m/" + uid);
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void setupWebView() {
        WebSettings settings = binding.webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        settings.setUserAgentString(settings.getUserAgentString()
                + " MeetingMemoryApp/1.0");
        CookieManager.getInstance().setAcceptCookie(true);
        binding.webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int progress) {
                binding.progress.setVisibility(progress < 100 ? android.view.View.VISIBLE
                        : android.view.View.GONE);
            }
        });
        binding.webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                binding.progress.setVisibility(android.view.View.GONE);
                binding.swipe.setRefreshing(false);
                syncCookieFromWeb();
            }

            @Override
            public void onReceivedSslError(WebView view, SslErrorHandler handler,
                                           SslError error) {
                if (prefs.allowSelfSigned()) {
                    handler.proceed();
                } else {
                    handler.cancel();
                    Toast.makeText(MeetingDetailActivity.this,
                            "证书校验失败，可在“我的”中允许自签证书",
                            Toast.LENGTH_LONG).show();
                }
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                String baseHost = Uri.parse(prefs.baseUrl()).getHost();
                if (uri.getHost() != null && uri.getHost().equalsIgnoreCase(baseHost)) {
                    return false;
                }
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, uri));
                } catch (Exception ignored) {
                }
                return true;
            }
        });
    }

    private void syncCookie() {
        String cookie = prefs.cookie();
        String host = prefs.cookieHost();
        String baseHost = Uri.parse(prefs.baseUrl()).getHost();
        if (cookie.isEmpty() || host.isEmpty() || baseHost == null
                || !host.equalsIgnoreCase(baseHost)) {
            return;
        }
        for (String part : cookie.split(";")) {
            String value = part.trim();
            if (!value.isEmpty()) {
                CookieManager.getInstance().setCookie(prefs.baseUrl(),
                        value + "; path=/");
            }
        }
        CookieManager.getInstance().flush();
    }

    /** 详情页里重新登录后，把新的会话同步回原生请求。 */
    private void syncCookieFromWeb() {
        String raw = CookieManager.getInstance().getCookie(prefs.baseUrl());
        if (raw == null || raw.isEmpty()) {
            return;
        }
        String session = null;
        for (String part : raw.split(";")) {
            String value = part.trim();
            if (value.startsWith("mm_session=")) {
                session = value;
                break;
            }
        }
        if (session == null || session.isEmpty() || session.equals(prefs.cookie())) {
            return;
        }
        String host = Uri.parse(prefs.baseUrl()).getHost();
        prefs.setCookie(host == null ? "" : host, session);
        com.zjh.meetingmemory.core.ApiClient.reset();
        com.zjh.meetingmemory.net.UploadWorker.resumeAuthPending(
                getApplicationContext());
        com.zjh.meetingmemory.net.StatusPollWorker.recoverPending(
                getApplicationContext());
    }

    @Override
    protected void onDestroy() {
        if (binding != null) {
            binding.webView.destroy();
        }
        super.onDestroy();
    }
}
