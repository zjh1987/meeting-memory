package com.zjh.meetingmemory;

import android.app.Application;

import com.zjh.meetingmemory.net.StatusPollWorker;
import com.zjh.meetingmemory.net.UploadWorker;
import com.zjh.meetingmemory.recording.RecordingFiles;
import com.zjh.meetingmemory.util.Notifications;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MeetingMemoryApp extends Application {

    private static MeetingMemoryApp instance;
    private ExecutorService io;

    @Override
    public void onCreate() {
        super.onCreate();
        instance = this;
        io = Executors.newFixedThreadPool(2);
        Notifications.ensureChannels(this);
        io.execute(() -> RecordingFiles.recoverOrphans(this));
        io.execute(() -> RecordingFiles.cleanupOld(this));
        io.execute(() -> UploadWorker.recoverInterrupted(this));
        io.execute(() -> StatusPollWorker.recoverPending(this));
    }

    public static MeetingMemoryApp get() {
        return instance;
    }

    public ExecutorService io() {
        if (io == null) {
            io = Executors.newFixedThreadPool(2);
        }
        return io;
    }
}
