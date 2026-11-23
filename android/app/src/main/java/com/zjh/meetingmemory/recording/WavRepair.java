package com.zjh.meetingmemory.recording;

import java.io.File;
import java.io.RandomAccessFile;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** 修复被中断的 WAV 文件头，并返回音频时长。 */
public final class WavRepair {

    private WavRepair() {
    }

    public static long repair(File file) {
        if (file == null || !file.isFile() || file.length() < 44) {
            return 0;
        }
        try (RandomAccessFile raf = new RandomAccessFile(file, "rw")) {
            byte[] head = new byte[44];
            raf.readFully(head);
            if (head[0] != 'R' || head[1] != 'I' || head[2] != 'F' || head[3] != 'F'
                    || head[8] != 'W' || head[9] != 'A' || head[10] != 'V' || head[11] != 'E') {
                return 0;
            }
            long dataBytes = file.length() - 44;
            ByteBuffer buffer = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN);
            buffer.put("RIFF".getBytes());
            buffer.putInt((int) (36 + dataBytes));
            buffer.put("WAVE".getBytes());
            buffer.put("fmt ".getBytes());
            buffer.putInt(16);
            buffer.putShort((short) 1);
            buffer.putShort((short) 1);
            buffer.putInt(WavRecorder.SAMPLE_RATE);
            buffer.putInt(WavRecorder.SAMPLE_RATE * 2);
            buffer.putShort((short) 2);
            buffer.putShort((short) 16);
            buffer.put("data".getBytes());
            buffer.putInt((int) dataBytes);
            raf.seek(0);
            raf.write(buffer.array());
            return dataBytes / WavRecorder.BYTES_PER_MS;
        } catch (Exception e) {
            return 0;
        }
    }
}
