package com.zjh.meetingmemory.recording;

import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/**
 * 16 kHz / 单声道 / 16-bit PCM 录音器。
 * 直接写 WAV，进程被杀后可通过修复文件头恢复，比 MP4 更抗中断。
 */
public class WavRecorder implements Runnable {

    public interface Listener {
        void onAmplitude(float level);

        void onError(String message);
    }

    private static final String TAG = "WavRecorder";
    public static final int SAMPLE_RATE = 16000;
    public static final int BYTES_PER_MS = SAMPLE_RATE * 2 / 1000;

    private final File file;
    private final Listener listener;

    private AudioRecord record;
    private FileOutputStream output;
    private Thread thread;
    private volatile boolean running;
    private volatile boolean paused;
    private volatile long dataBytes;
    private volatile float level;
    private volatile String error = "";

    public WavRecorder(File file, Listener listener) {
        this.file = file;
        this.listener = listener;
    }

    @android.annotation.SuppressLint("MissingPermission")
    public void start() throws Exception {
        // 调用方（RecordingService）已检查 RECORD_AUDIO 权限，并在录音期间保持前台服务。
        int minBuffer = AudioRecord.getMinBufferSize(SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        if (minBuffer <= 0) {
            throw new IOException("麦克风不支持 16kHz 单声道录音");
        }
        int bufferSize = Math.max(minBuffer, BYTES_PER_MS * 200);
        record = new AudioRecord(MediaRecorder.AudioSource.MIC, SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, bufferSize);
        if (record.getState() != AudioRecord.STATE_INITIALIZED) {
            record.release();
            record = null;
            throw new IOException("麦克风初始化失败，可能被其他应用占用");
        }
        output = new FileOutputStream(file, false);
        dataBytes = 0;
        try {
            writeHeader();
            record.startRecording();
            if (record.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) {
                throw new IOException("无法开始录音，请检查麦克风权限");
            }
        } catch (Exception e) {
            try {
                record.release();
            } catch (Exception ignored) {
            }
            record = null;
            try {
                output.close();
            } catch (IOException ignored) {
            }
            output = null;
            throw e;
        }
        running = true;
        thread = new Thread(this, "wav-recorder");
        thread.start();
    }

    @Override
    public void run() {
        short[] buffer = new short[1600];
        long lastHeader = System.currentTimeMillis();
        try {
            while (running) {
                int read = record.read(buffer, 0, buffer.length);
                if (read < 0) {
                    error = "录音中断，错误码 " + read;
                    listener.onError(error);
                    break;
                }
                if (read == 0) {
                    continue;
                }
                int peak = 0;
                for (int i = 0; i < read; i++) {
                    int value = Math.abs(buffer[i]);
                    if (value > peak) {
                        peak = value;
                    }
                }
                level = Math.min(1f, (float) Math.sqrt(peak / 32767.0));
                listener.onAmplitude(level);
                if (!paused) {
                    byte[] bytes = new byte[read * 2];
                    for (int i = 0; i < read; i++) {
                        int value = buffer[i];
                        bytes[i * 2] = (byte) (value & 0xff);
                        bytes[i * 2 + 1] = (byte) ((value >> 8) & 0xff);
                    }
                    output.write(bytes);
                    dataBytes += bytes.length;
                    long now = System.currentTimeMillis();
                    if (now - lastHeader >= 5000) {
                        lastHeader = now;
                        output.flush();
                        writeHeader();
                    }
                }
            }
        } catch (Exception e) {
            error = "录音中断：" + (e.getMessage() == null ? "写入失败" : e.getMessage());
            listener.onError(error);
        } finally {
            try {
                if (output != null) {
                    output.flush();
                }
            } catch (IOException ignored) {
            }
        }
    }

    public void pause() {
        paused = true;
        level = 0;
        listener.onAmplitude(0);
    }

    public void resume() {
        paused = false;
    }

    public boolean isPaused() {
        return paused;
    }

    public long audioMs() {
        return dataBytes / BYTES_PER_MS;
    }

    public long sizeBytes() {
        return dataBytes + 44;
    }

    public String error() {
        return error;
    }

    public void stop() {
        running = false;
        Thread current = thread;
        if (current != null) {
            try {
                current.join(3000);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
        try {
            if (record != null) {
                if (record.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING) {
                    record.stop();
                }
                record.release();
            }
        } catch (Exception e) {
            Log.w(TAG, "停止录音失败", e);
        } finally {
            record = null;
        }
        try {
            if (output != null) {
                output.flush();
                output.close();
            }
        } catch (IOException ignored) {
        } finally {
            output = null;
        }
        writeHeader();
        listener.onAmplitude(0);
    }

    private void writeHeader() {
        try (RandomAccessFile raf = new RandomAccessFile(file, "rw")) {
            raf.seek(0);
            raf.write(header(dataBytes));
        } catch (IOException e) {
            Log.w(TAG, "更新 WAV 文件头失败", e);
        }
    }

    private static byte[] header(long dataBytes) {
        ByteBuffer buffer = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN);
        buffer.put("RIFF".getBytes());
        buffer.putInt((int) (36 + dataBytes));
        buffer.put("WAVE".getBytes());
        buffer.put("fmt ".getBytes());
        buffer.putInt(16);
        buffer.putShort((short) 1);
        buffer.putShort((short) 1);
        buffer.putInt(SAMPLE_RATE);
        buffer.putInt(SAMPLE_RATE * 2);
        buffer.putShort((short) 2);
        buffer.putShort((short) 16);
        buffer.put("data".getBytes());
        buffer.putInt((int) dataBytes);
        return buffer.array();
    }
}
