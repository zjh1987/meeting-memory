package com.zjh.meetingmemory.recording;

public final class RecordingState {

    public static volatile boolean active;
    public static volatile boolean paused;
    public static volatile long startedAt;
    public static volatile long pausedAt;
    public static volatile long pausedTotal;
    public static volatile float amplitude;
    public static volatile long rowId = -1;
    public static volatile String filePath = "";
    public static volatile String title = "";
    public static volatile String project = "";
    public static volatile String templateKey = "standard";
    public static volatile String templateName = "常规会议";

    private RecordingState() {
    }

    public static synchronized void begin(long id, String path, String meetingTitle,
                                         String meetingProject, String key, String name) {
        active = true;
        paused = false;
        startedAt = System.currentTimeMillis();
        pausedAt = 0;
        pausedTotal = 0;
        amplitude = 0;
        rowId = id;
        filePath = path;
        title = meetingTitle;
        project = meetingProject;
        templateKey = key;
        templateName = name;
    }

    public static synchronized void pause() {
        if (active && !paused) {
            paused = true;
            pausedAt = System.currentTimeMillis();
        }
    }

    public static synchronized void resume() {
        if (active && paused) {
            pausedTotal += System.currentTimeMillis() - pausedAt;
            pausedAt = 0;
            paused = false;
        }
    }

    public static synchronized void finish() {
        active = false;
        paused = false;
        amplitude = 0;
        startedAt = 0;
        pausedAt = 0;
        pausedTotal = 0;
        rowId = -1;
        filePath = "";
    }

    public static synchronized long elapsedMs() {
        if (!active || startedAt <= 0) {
            return 0;
        }
        long end = paused ? pausedAt : System.currentTimeMillis();
        return Math.max(0, end - startedAt - pausedTotal);
    }
}
