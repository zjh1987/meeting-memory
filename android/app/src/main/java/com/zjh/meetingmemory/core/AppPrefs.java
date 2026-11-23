package com.zjh.meetingmemory.core;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.security.crypto.EncryptedSharedPreferences;
import androidx.security.crypto.MasterKey;

import java.net.URI;

/**
 * 本地配置。会话 Cookie 使用 EncryptedSharedPreferences 保存；
 * 密码从不落盘。
 */
public class AppPrefs {

    private static final String PREFS = "mm_app";
    private static final String SECURE = "mm_app_secure";

    private final SharedPreferences prefs;
    private final SharedPreferences secure;

    public AppPrefs(Context context) {
        Context app = context.getApplicationContext();
        prefs = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        SharedPreferences encrypted;
        try {
            MasterKey key = new MasterKey.Builder(app)
                    .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                    .build();
            encrypted = EncryptedSharedPreferences.create(
                    app, SECURE, key,
                    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM);
        } catch (Exception ignored) {
            encrypted = app.getSharedPreferences(SECURE + "_fallback", Context.MODE_PRIVATE);
        }
        secure = encrypted;
    }

    public String baseUrl() {
        String value = prefs.getString("base_url", "");
        return value == null ? "" : value.trim();
    }

    public void setBaseUrl(String value) {
        prefs.edit().putString("base_url", normalizeBase(value)).apply();
    }

    public static String normalizeBase(String raw) {
        String value = raw == null ? "" : raw.trim();
        if (value.isEmpty()) {
            return "";
        }
        if (!value.startsWith("http://") && !value.startsWith("https://")) {
            value = "http://" + value;
        }
        while (value.endsWith("/")) {
            value = value.substring(0, value.length() - 1);
        }
        return value;
    }

    public String host() {
        try {
            return new URI(baseUrl()).getHost();
        } catch (Exception e) {
            return "";
        }
    }

    public String username() {
        return prefs.getString("username", "");
    }

    public void setUsername(String value) {
        prefs.edit().putString("username", value == null ? "" : value).apply();
    }

    public String cookie() {
        String value = secure.getString("cookie_value", "");
        return value == null ? "" : value;
    }

    public String cookieHost() {
        return secure.getString("cookie_host", "");
    }

    public void setCookie(String host, String value) {
        secure.edit()
                .putString("cookie_host", host == null ? "" : host)
                .putString("cookie_value", value == null ? "" : value)
                .apply();
    }

    public void clearCookie() {
        secure.edit().remove("cookie_host").remove("cookie_value").apply();
    }

    public boolean isConfigured() {
        if (baseUrl().isEmpty() || cookie().isEmpty()) {
            return false;
        }
        String host = host();
        return !host.isEmpty() && host.equalsIgnoreCase(cookieHost());
    }

    public boolean allowSelfSigned() {
        return prefs.getBoolean("allow_self_signed", false);
    }

    public void setAllowSelfSigned(boolean value) {
        prefs.edit().putBoolean("allow_self_signed", value).apply();
    }

    public boolean autoUpload() {
        return prefs.getBoolean("auto_upload", true);
    }

    public void setAutoUpload(boolean value) {
        prefs.edit().putBoolean("auto_upload", value).apply();
    }

    public boolean wifiOnly() {
        return prefs.getBoolean("wifi_only", true);
    }

    public void setWifiOnly(boolean value) {
        prefs.edit().putBoolean("wifi_only", value).apply();
    }

    public int maxMinutes() {
        return prefs.getInt("max_minutes", 360);
    }

    public void setMaxMinutes(int value) {
        prefs.edit().putInt("max_minutes", value).apply();
    }

    public int keepDays() {
        return prefs.getInt("keep_days", 30);
    }

    public void setKeepDays(int value) {
        prefs.edit().putInt("keep_days", value).apply();
    }

    public String lastProject() {
        return prefs.getString("last_project", "");
    }

    public void setLastProject(String value) {
        prefs.edit().putString("last_project", value == null ? "" : value).apply();
    }

    public String lastTemplate() {
        return prefs.getString("last_template", "standard");
    }

    public void setLastTemplate(String value) {
        prefs.edit().putString("last_template", value).apply();
    }

    public String lastWebPath() {
        return prefs.getString("last_web_path", "/");
    }

    public void setLastWebPath(String value) {
        prefs.edit().putString("last_web_path", value == null ? "/" : value).apply();
    }

    public String cachedProjects() {
        return prefs.getString("cache_projects", "");
    }

    public void setCachedProjects(String json) {
        prefs.edit().putString("cache_projects", json).apply();
    }

    public String cachedTemplates() {
        return prefs.getString("cache_templates", "");
    }

    public void setCachedTemplates(String json) {
        prefs.edit().putString("cache_templates", json).apply();
    }
}
