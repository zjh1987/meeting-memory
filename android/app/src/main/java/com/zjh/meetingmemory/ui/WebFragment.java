package com.zjh.meetingmemory.ui;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import com.google.android.material.snackbar.Snackbar;
import com.zjh.meetingmemory.R;
import com.zjh.meetingmemory.core.ApiClient;
import com.zjh.meetingmemory.core.AppPrefs;
import com.zjh.meetingmemory.databinding.FragmentWebBinding;

public class WebFragment extends Fragment {

    private FragmentWebBinding binding;
    private AppPrefs prefs;
    private ValueCallback<Uri[]> fileCallback;
    private ActivityResultLauncher<Intent> fileChooser;
    private String cookieSnapshot = "";
    private String currentPath = "/";
    private boolean loaded;

    @Override
    public void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        fileChooser = registerForActivityResult(
                new ActivityResultContracts.StartActivityForResult(), result -> {
                    if (fileCallback == null) {
                        return;
                    }
                    Uri[] uris = null;
                    Intent data = result.getData();
                    if (result.getResultCode() == Activity.RESULT_OK && data != null) {
                        if (data.getClipData() != null) {
                            int count = data.getClipData().getItemCount();
                            uris = new Uri[count];
                            for (int i = 0; i < count; i++) {
                                uris[i] = data.getClipData().getItemAt(i).getUri();
                                persistRead(uris[i]);
                            }
                        } else if (data.getData() != null) {
                            uris = new Uri[]{data.getData()};
                            persistRead(uris[0]);
                        }
                    }
                    fileCallback.onReceiveValue(uris);
                    fileCallback = null;
                });
    }

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentWebBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);
        prefs = new AppPrefs(requireContext());
        setupWebView();
        setupActions();
        String last = prefs.lastWebPath();
        if (last == null || last.isEmpty() || "/login".equals(last)) {
            last = "/";
        }
        selectChip(last);
        loadPath(last, false);
    }

    private void setupActions() {
        binding.btnWebRefresh.setOnClickListener(v -> binding.webView.reload());
        binding.webSwipe.setOnRefreshListener(() -> binding.webView.reload());
        binding.chipOverview.setOnClickListener(v -> loadPath("/", true));
        binding.chipMeetings.setOnClickListener(v -> loadPath("/meetings", true));
        binding.chipUpload.setOnClickListener(v -> loadPath("/upload", true));
        binding.chipAdmin.setOnClickListener(v -> loadPath("/admin", true));
        binding.chipArchive.setOnClickListener(v -> loadPath("/site/", true));
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void setupWebView() {
        WebSettings settings = binding.webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        settings.setUserAgentString(settings.getUserAgentString()
                + " MeetingMemoryApp/1.0");
        CookieManager cookieManager = CookieManager.getInstance();
        cookieManager.setAcceptCookie(true);
        cookieManager.setAcceptThirdPartyCookies(binding.webView, false);
        syncCookieToWebView();
        cookieSnapshot = prefs.cookie();

        binding.webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int progress) {
                binding.webProgress.setVisibility(progress < 100
                        ? View.VISIBLE : View.GONE);
            }

            @Override
            public boolean onShowFileChooser(WebView webView,
                                             ValueCallback<Uri[]> callback,
                                             FileChooserParams params) {
                if (fileCallback != null) {
                    fileCallback.onReceiveValue(null);
                }
                fileCallback = callback;
                // 很多录音 App 的文件 MIME 并不规范，用 */* 让系统文件选择器
                // 一定能浏览到“录音”“下载”等目录，格式由服务端最终校验。
                Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType("*/*");
                if (params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE) {
                    intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                }
                try {
                    fileChooser.launch(Intent.createChooser(intent, "选择录音文件"));
                    return true;
                } catch (Exception e) {
                    fileCallback = null;
                    return false;
                }
            }
        });

        binding.webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                binding.webProgress.setVisibility(View.GONE);
                binding.webSwipe.setRefreshing(false);
                syncCookieFromWebView();
                saveCurrentPath(url);
            }

            @Override
            public void onReceivedSslError(WebView view, SslErrorHandler handler,
                                           SslError error) {
                if (prefs.allowSelfSigned()) {
                    handler.proceed();
                } else {
                    handler.cancel();
                    snack("证书校验失败。若服务器使用自签 HTTPS，请在“我的”中开启允许自签证书。");
                }
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                String baseHost = Uri.parse(prefs.baseUrl()).getHost();
                if (uri.getHost() != null && baseHost != null
                        && uri.getHost().equalsIgnoreCase(baseHost)) {
                    return false;
                }
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, uri));
                } catch (Exception ignored) {
                }
                return true;
            }
        });

        binding.webView.setDownloadListener((url, userAgent, contentDisposition, mimeType,
                                             contentLength) -> {
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
            } catch (Exception e) {
                snack("无法打开下载链接");
            }
        });
        binding.webView.setOnLongClickListener(v -> false);
    }

    private void persistRead(Uri uri) {
        if (uri == null || getContext() == null) {
            return;
        }
        try {
            getContext().getContentResolver().takePersistableUriPermission(
                    uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
        } catch (Exception ignored) {
        }
    }

    private void loadPath(String path, boolean showChip) {
        currentPath = path;
        prefs.setLastWebPath(path);
        if (showChip) {
            selectChip(path);
        }
        syncCookieToWebView();
        binding.webProgress.setVisibility(View.VISIBLE);
        binding.webView.loadUrl(prefs.baseUrl() + path);
        loaded = true;
    }

    private void selectChip(String path) {
        if ("/meetings".equals(path)) {
            binding.chipMeetings.setChecked(true);
        } else if ("/upload".equals(path)) {
            binding.chipUpload.setChecked(true);
        } else if ("/admin".equals(path)) {
            binding.chipAdmin.setChecked(true);
        } else if (path.startsWith("/site")) {
            binding.chipArchive.setChecked(true);
        } else {
            binding.chipOverview.setChecked(true);
        }
    }

    private void syncCookieToWebView() {
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

    private void syncCookieFromWebView() {
        if (binding == null) {
            return;
        }
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
        if (session == null || session.isEmpty()) {
            return;
        }
        if (!session.equals(prefs.cookie())) {
            String host = Uri.parse(prefs.baseUrl()).getHost();
            prefs.setCookie(host == null ? "" : host, session);
            ApiClient.reset();
            com.zjh.meetingmemory.net.UploadWorker.resumeAuthPending(
                    requireContext().getApplicationContext());
            com.zjh.meetingmemory.net.StatusPollWorker.recoverPending(
                    requireContext().getApplicationContext());
            cookieSnapshot = session;
            Snackbar.make(binding.getRoot(), "已同步网页登录状态",
                    Snackbar.LENGTH_SHORT).show();
        }
    }

    private void saveCurrentPath(String url) {
        if (url == null) {
            return;
        }
        String base = prefs.baseUrl();
        if (!url.startsWith(base)) {
            return;
        }
        String path = url.substring(base.length());
        if (path.isEmpty()) {
            path = "/";
        }
        int query = path.indexOf('?');
        if (query >= 0) {
            path = path.substring(0, query);
        }
        if ("/login".equals(path)) {
            return;
        }
        currentPath = path;
        prefs.setLastWebPath(path);
        selectChip(path);
    }

    public boolean canGoBack() {
        return binding != null && binding.webView.canGoBack();
    }

    public void goBack() {
        if (binding != null) {
            binding.webView.goBack();
        }
    }

    private void snack(String text) {
        if (binding != null) {
            Snackbar.make(binding.getRoot(), text, Snackbar.LENGTH_LONG).show();
        }
    }

    @Override
    public void onResume() {
        super.onResume();
        if (binding == null || isHidden()) {
            return;
        }
        if (!loaded) {
            loadPath("/", false);
        } else {
            binding.webView.onResume();
        }
        if (prefs.isConfigured() && !prefs.cookie().equals(cookieSnapshot)) {
            cookieSnapshot = prefs.cookie();
            syncCookieToWebView();
            binding.webView.reload();
        }
    }

    @Override
    public void onPause() {
        if (binding != null) {
            binding.webView.onPause();
        }
        super.onPause();
    }

    @Override
    public void onHiddenChanged(boolean hidden) {
        super.onHiddenChanged(hidden);
        if (binding == null) {
            return;
        }
        if (hidden) {
            binding.webView.onPause();
        } else {
            binding.webView.onResume();
            if (!prefs.cookie().equals(cookieSnapshot)) {
                cookieSnapshot = prefs.cookie();
                syncCookieToWebView();
                binding.webView.reload();
            }
        }
    }

    @Override
    public void onDestroyView() {
        if (binding != null) {
            binding.webView.destroy();
        }
        binding = null;
        super.onDestroyView();
    }
}
