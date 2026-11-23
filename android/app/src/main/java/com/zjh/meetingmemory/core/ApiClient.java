package com.zjh.meetingmemory.core;

import android.content.Context;

import androidx.annotation.NonNull;

import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.security.cert.X509Certificate;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

import okhttp3.Call;
import okhttp3.FormBody;
import okhttp3.HttpUrl;
import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okio.BufferedSink;
import okio.Okio;
import okio.Source;

public final class ApiClient {

    public interface ApiCallback {
        void onResponse(int code, String body);

        void onFailure(IOException error);
    }

    public interface ProgressListener {
        void onProgress(int percent);
    }

    public static class TestResult {
        public boolean ok;
        public long latencyMs;
        public String message = "";
        public String fingerprint = "";
    }

    public static class LoginResult {
        public boolean ok;
        public int code;
        public String message = "";
    }

    private static volatile ApiClient instance;

    private final AppPrefs prefs;
    private final OkHttpClient client;

    public static ApiClient get(Context context) {
        ApiClient local = instance;
        if (local == null) {
            synchronized (ApiClient.class) {
                local = instance;
                if (local == null) {
                    local = new ApiClient(context.getApplicationContext());
                    instance = local;
                }
            }
        }
        return local;
    }

    public static void reset() {
        instance = null;
    }

    private ApiClient(Context context) {
        prefs = new AppPrefs(context);
        client = buildClient(context, prefs.allowSelfSigned());
    }

    public String baseUrl() {
        return prefs.baseUrl();
    }

    public OkHttpClient http() {
        return client;
    }

    public void get(String path, ApiCallback callback) {
        HttpUrl url = HttpUrl.parse(baseUrl() + path);
        if (url == null) {
            callback.onFailure(new IOException("服务器地址无效"));
            return;
        }
        Request request = new Request.Builder()
                .url(url)
                .header("Accept", "application/json")
                .get()
                .build();
        enqueue(request, callback);
    }

    public Response getSync(String path) throws IOException {
        HttpUrl url = HttpUrl.parse(baseUrl() + path);
        if (url == null) {
            throw new IOException("服务器地址无效");
        }
        Request request = new Request.Builder()
                .url(url)
                .header("Accept", "application/json")
                .get()
                .build();
        return client.newCall(request).execute();
    }

    public void postForm(String path, Map<String, String> fields, ApiCallback callback) {
        HttpUrl url = HttpUrl.parse(baseUrl() + path);
        if (url == null) {
            callback.onFailure(new IOException("服务器地址无效"));
            return;
        }
        FormBody.Builder body = new FormBody.Builder();
        for (Map.Entry<String, String> entry : fields.entrySet()) {
            body.add(entry.getKey(), entry.getValue());
        }
        Request request = new Request.Builder().url(url).post(body.build()).build();
        enqueue(request, callback);
    }

    private void enqueue(Request request, ApiCallback callback) {
        client.newCall(request).enqueue(new okhttp3.Callback() {
            @Override
            public void onFailure(@NonNull Call call, @NonNull IOException e) {
                callback.onFailure(e);
            }

            @Override
            public void onResponse(@NonNull Call call, @NonNull Response response) {
                try (Response resp = response) {
                    String body = resp.body() == null ? "" : resp.body().string();
                    callback.onResponse(resp.code(), body);
                } catch (IOException e) {
                    callback.onFailure(e);
                }
            }
        });
    }

    public Response uploadSync(File file, String title, String project,
                               String templateKey, String recordedAt,
                               ProgressListener listener) throws IOException {
        HttpUrl url = HttpUrl.parse(baseUrl() + "/api/meetings");
        if (url == null) {
            throw new IOException("服务器地址无效");
        }
        MediaType type = MediaType.parse("audio/wav");
        RequestBody fileBody = new ProgressRequestBody(file, type, listener);
        MultipartBody.Builder multipart = new MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart("file", file.getName(), fileBody)
                .addFormDataPart("title", title)
                .addFormDataPart("project_name", project)
                .addFormDataPart("template_key", templateKey);
        if (recordedAt != null && !recordedAt.isEmpty()) {
            multipart.addFormDataPart("recorded_at", recordedAt);
        }
        Request request = new Request.Builder().url(url).post(multipart.build()).build();
        return client.newCall(request).execute();
    }

    public static TestResult testConnection(Context context, String baseUrl,
                                            boolean trustAll) {
        TestResult result = new TestResult();
        String base = AppPrefs.normalizeBase(baseUrl);
        HttpUrl url = HttpUrl.parse(base + "/healthz");
        if (url == null) {
            result.message = "地址格式不正确";
            return result;
        }
        OkHttpClient probe = buildClient(context.getApplicationContext(), trustAll)
                .newBuilder()
                .connectTimeout(8, TimeUnit.SECONDS)
                .readTimeout(8, TimeUnit.SECONDS)
                .build();
        Request request = new Request.Builder().url(url).get().build();
        long started = System.currentTimeMillis();
        try (Response response = probe.newCall(request).execute()) {
            result.latencyMs = System.currentTimeMillis() - started;
            result.ok = response.isSuccessful();
            result.message = result.ok
                    ? "连接成功 · " + result.latencyMs + " ms"
                    : "服务器返回 " + response.code();
            if (!result.ok) {
                result.message += " · " + errorMessage(response.body() == null
                        ? "" : response.body().string(), "请检查服务是否启动");
            }
            if (response.handshake() != null
                    && !response.handshake().peerCertificates().isEmpty()) {
                java.security.cert.Certificate cert =
                        response.handshake().peerCertificates().get(0);
                if (cert instanceof X509Certificate) {
                    result.fingerprint = sha256(cert.getEncoded());
                }
            }
        } catch (Exception e) {
            result.message = friendlyError(e);
        }
        return result;
    }

    public static LoginResult login(Context context, String baseUrl, String username,
                                    String password, boolean trustAll) {
        LoginResult result = new LoginResult();
        String base = AppPrefs.normalizeBase(baseUrl);
        HttpUrl loginUrl = HttpUrl.parse(base + "/login");
        if (loginUrl == null) {
            result.message = "地址格式不正确";
            return result;
        }
        AppPrefs prefs = new AppPrefs(context);
        prefs.clearCookie();
        OkHttpClient loginClient = buildClient(context.getApplicationContext(), trustAll);
        RequestBody form = new FormBody.Builder()
                .add("username", username)
                .add("password", password)
                .build();
        Request request = new Request.Builder().url(loginUrl).post(form).build();
        try (Response response = loginClient.newCall(request).execute()) {
            result.code = response.code();
            String body = response.body() == null ? "" : response.body().string();
            if (response.code() == 401) {
                result.message = "账号或密码不正确";
                return result;
            }
            if (response.code() == 429) {
                result.message = "登录尝试过于频繁，请稍后再试";
                return result;
            }
            if (!response.isSuccessful()) {
                result.message = errorMessage(body, "登录失败（HTTP " + response.code() + "）");
                return result;
            }
            if (prefs.cookie().isEmpty()) {
                result.message = "登录失败：服务器没有返回会话";
                return result;
            }
            prefs.setBaseUrl(base);
            prefs.setUsername(username);
            prefs.setAllowSelfSigned(trustAll);

            HttpUrl probeUrl = HttpUrl.parse(base + "/api/projects");
            if (probeUrl == null) {
                result.message = "地址格式不正确";
                return result;
            }
            Request probe = new Request.Builder()
                    .url(probeUrl)
                    .header("Accept", "application/json")
                    .get()
                    .build();
            try (Response check = loginClient.newCall(probe).execute()) {
                if (check.code() == 401) {
                    result.message = "登录后校验失败，请重试";
                    prefs.clearCookie();
                    return result;
                }
                if (!check.isSuccessful()) {
                    result.message = "服务器返回 " + check.code();
                    prefs.clearCookie();
                    return result;
                }
            }
            result.ok = true;
            return result;
        } catch (Exception e) {
            result.message = friendlyError(e);
            return result;
        }
    }

    public static String errorMessage(String body, String fallback) {
        if (body != null && !body.isEmpty()) {
            try {
                JSONObject json = new JSONObject(body);
                JSONObject error = json.optJSONObject("error");
                if (error != null) {
                    String message = error.optString("message", "");
                    if (!message.isEmpty()) {
                        return message;
                    }
                }
            } catch (Exception ignored) {
                // HTML 错误页不直接展示给用户。
            }
        }
        return fallback;
    }

    public static String friendlyError(Exception error) {
        String message = error.getMessage() == null ? "" : error.getMessage();
        if (error instanceof javax.net.ssl.SSLHandshakeException
                || message.contains("Trust anchor")
                || message.contains("SSLHandshake")) {
            return "证书校验失败。若服务器使用自签 HTTPS，请在登录页勾选“信任自签证书”。";
        }
        if (message.contains("Failed to connect") || message.contains("ConnectException")
                || message.contains("timeout") || message.contains("timed out")) {
            return "无法连接服务器，请检查地址、端口与网络。";
        }
        if (message.contains("ENETUNREACH") || message.contains("Network is unreachable")) {
            return "当前网络不可达，请连接与服务器相同的 Wi-Fi。";
        }
        return message.isEmpty() ? "网络请求失败" : message;
    }

    public static OkHttpClient buildClient(Context context, boolean trustAll) {
        AppPrefs prefs = new AppPrefs(context);
        OkHttpClient.Builder builder = new OkHttpClient.Builder()
                .cookieJar(new CookieStore(prefs))
                .connectTimeout(15, TimeUnit.SECONDS)
                .readTimeout(60, TimeUnit.SECONDS)
                .writeTimeout(0, TimeUnit.SECONDS)
                .callTimeout(0, TimeUnit.SECONDS)
                .retryOnConnectionFailure(true);
        if (trustAll) {
            try {
                final X509TrustManager manager = new X509TrustManager() {
                    @Override
                    public void checkClientTrusted(X509Certificate[] chain, String authType) {
                    }

                    @Override
                    public void checkServerTrusted(X509Certificate[] chain, String authType) {
                    }

                    @Override
                    public X509Certificate[] getAcceptedIssuers() {
                        return new X509Certificate[0];
                    }
                };
                SSLContext ssl = SSLContext.getInstance("TLS");
                ssl.init(null, new TrustManager[]{manager}, new SecureRandom());
                SSLSocketFactory factory = ssl.getSocketFactory();
                builder.sslSocketFactory(factory, manager);
                builder.hostnameVerifier((hostname, session) -> true);
            } catch (Exception ignored) {
                // 构建失败时回落到系统默认校验。
            }
        }
        return builder.build();
    }

    private static String sha256(byte[] data) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] out = digest.digest(data);
            StringBuilder builder = new StringBuilder();
            for (int i = 0; i < out.length; i++) {
                if (i > 0) {
                    builder.append(':');
                }
                builder.append(String.format("%02X", out[i]));
            }
            return builder.toString();
        } catch (Exception e) {
            return "";
        }
    }

    private static final class ProgressRequestBody extends RequestBody {
        private final File file;
        private final MediaType type;
        private final ProgressListener listener;

        ProgressRequestBody(File file, MediaType type, ProgressListener listener) {
            this.file = file;
            this.type = type;
            this.listener = listener;
        }

        @Override
        public MediaType contentType() {
            return type;
        }

        @Override
        public long contentLength() {
            return file.length();
        }

        @Override
        public void writeTo(@NonNull BufferedSink sink) throws IOException {
            long total = Math.max(file.length(), 1);
            long uploaded = 0;
            int lastPercent = -10;
            try (Source source = Okio.source(file)) {
                okio.Buffer buffer = new okio.Buffer();
                long read;
                while ((read = source.read(buffer, 16 * 1024)) != -1) {
                    sink.write(buffer, read);
                    uploaded += read;
                    if (listener != null) {
                        int percent = (int) (uploaded * 100 / total);
                        if (percent - lastPercent >= 3) {
                            lastPercent = percent;
                            listener.onProgress(Math.min(percent, 100));
                        }
                    }
                }
            }
            if (listener != null) {
                listener.onProgress(100);
            }
        }
    }
}
