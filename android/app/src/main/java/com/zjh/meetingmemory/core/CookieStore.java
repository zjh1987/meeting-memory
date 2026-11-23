package com.zjh.meetingmemory.core;

import androidx.annotation.NonNull;

import java.util.ArrayList;
import java.util.List;

import okhttp3.Cookie;
import okhttp3.CookieJar;
import okhttp3.HttpUrl;

/** 把服务器会话 Cookie 持久化，并绑定到当前服务器域名。 */
public class CookieStore implements CookieJar {

    private final AppPrefs prefs;

    public CookieStore(AppPrefs prefs) {
        this.prefs = prefs;
    }

    @Override
    public void saveFromResponse(@NonNull HttpUrl url, @NonNull List<Cookie> cookies) {
        if (cookies.isEmpty()) {
            return;
        }
        StringBuilder builder = new StringBuilder();
        for (Cookie cookie : cookies) {
            if (builder.length() > 0) {
                builder.append("; ");
            }
            builder.append(cookie.name()).append('=').append(cookie.value());
        }
        prefs.setCookie(url.host(), builder.toString());
    }

    @NonNull
    @Override
    public List<Cookie> loadForRequest(@NonNull HttpUrl url) {
        List<Cookie> result = new ArrayList<>();
        String host = prefs.cookieHost();
        String raw = prefs.cookie();
        if (raw.isEmpty() || host.isEmpty() || !host.equalsIgnoreCase(url.host())) {
            return result;
        }
        for (String part : raw.split(";")) {
            Cookie cookie = Cookie.parse(url, part.trim());
            if (cookie != null) {
                result.add(cookie);
            }
        }
        return result;
    }
}
