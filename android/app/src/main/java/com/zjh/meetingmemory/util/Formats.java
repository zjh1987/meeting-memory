package com.zjh.meetingmemory.util;

import android.content.Context;
import android.content.res.ColorStateList;
import android.widget.TextView;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

public final class Formats {

    private Formats() {
    }

    public static String duration(long millis) {
        long total = Math.max(0, millis / 1000);
        long hours = total / 3600;
        long minutes = (total % 3600) / 60;
        long seconds = total % 60;
        if (hours > 0) {
            return String.format(Locale.CHINA, "%d:%02d:%02d", hours, minutes, seconds);
        }
        return String.format(Locale.CHINA, "%02d:%02d", minutes, seconds);
    }

    public static String spokenDuration(long millis) {
        long minutes = Math.max(1, Math.round(millis / 60000.0));
        if (minutes >= 60) {
            return (minutes / 60) + " 小时 " + (minutes % 60) + " 分钟";
        }
        return minutes + " 分钟";
    }

    public static String size(long bytes) {
        if (bytes < 1024) {
            return bytes + " B";
        }
        double kb = bytes / 1024.0;
        if (kb < 1024) {
            return String.format(Locale.CHINA, "%.0f KB", kb);
        }
        double mb = kb / 1024.0;
        if (mb < 1024) {
            return String.format(Locale.CHINA, "%.1f MB", mb);
        }
        return String.format(Locale.CHINA, "%.2f GB", mb / 1024.0);
    }

    public static String dateTime(long millis) {
        return new SimpleDateFormat("M月d日 HH:mm", Locale.CHINA).format(new Date(millis));
    }

    public static String fullDateTime(long millis) {
        return new SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.CHINA).format(new Date(millis));
    }

    public static String fromServerTime(String value) {
        if (value == null || value.length() < 16) {
            return "";
        }
        try {
            Date date = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.CHINA).parse(value);
            if (date == null) {
                return value;
            }
            return new SimpleDateFormat("M月d日 HH:mm", Locale.CHINA).format(date);
        } catch (Exception e) {
            return value.length() >= 16 ? value.substring(5, 16) : value;
        }
    }

    public static String monthLabel(String serverTime) {
        if (serverTime == null || serverTime.length() < 7) {
            return "日期未知";
        }
        try {
            int year = Integer.parseInt(serverTime.substring(0, 4));
            int month = Integer.parseInt(serverTime.substring(5, 7));
            return year + "年" + month + "月";
        } catch (Exception e) {
            return "日期未知";
        }
    }

    public static String serverStatus(String status) {
        if (status == null) {
            return "未知";
        }
        switch (status) {
            case "uploading":
                return "接收中";
            case "pending":
                return "排队中";
            case "transcribing":
                return "转写中";
            case "minuting":
                return "生成纪要";
            case "relating":
                return "归档中";
            case "done":
                return "已完成";
            case "failed":
                return "处理失败";
            default:
                return status;
        }
    }

    public static boolean isProcessing(String status) {
        return "pending".equals(status) || "transcribing".equals(status)
                || "minuting".equals(status) || "relating".equals(status)
                || "uploading".equals(status);
    }

    public static void pill(TextView view, String text, int color) {
        view.setText(text);
        view.setTextColor(color);
        int alpha = (color & 0x00FFFFFF) | 0x1A000000;
        view.setBackgroundTintList(ColorStateList.valueOf(alpha));
    }

    public static int color(Context context, int res) {
        return context.getColor(res);
    }
}
