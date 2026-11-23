package com.zjh.meetingmemory.core;

import org.json.JSONObject;

public final class Models {

    private Models() {
    }

    public static class Project {
        public int id;
        public String name = "";
    }

    public static class Template {
        public String key = "standard";
        public String name = "常规会议";
        public String description = "";
        public String scene = "常规";

        public static Template from(JSONObject json) {
            Template template = new Template();
            template.key = json.optString("key", "standard");
            template.name = json.optString("name", template.key);
            template.description = json.optString("description", "");
            template.scene = json.optString("scene", "");
            return template;
        }
    }

    public static class Meeting {
        public String uid = "";
        public String title = "";
        public String status = "";
        public String projectName = "";
        public String recordedAt = "";
        public String errorMsg = "";
        public int openActions = 0;
        public double durationSec = 0;

        public static Meeting from(JSONObject json) {
            Meeting meeting = new Meeting();
            meeting.uid = json.optString("uid", "");
            meeting.title = json.optString("title", "未命名会议");
            meeting.status = json.optString("status", "");
            meeting.projectName = json.optString("project_name", "");
            meeting.recordedAt = json.optString("recorded_at", "");
            meeting.errorMsg = json.optString("error_msg", "");
            meeting.openActions = json.optInt("open_actions", 0);
            meeting.durationSec = json.optDouble("duration_sec", 0);
            return meeting;
        }
    }
}
