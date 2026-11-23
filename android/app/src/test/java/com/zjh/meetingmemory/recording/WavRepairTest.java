package com.zjh.meetingmemory.recording;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;

public class WavRepairTest {

    @Test
    public void repairsHeaderAndComputesDuration() throws Exception {
        File file = File.createTempFile("mm_rec_", ".wav");
        file.deleteOnExit();
        try (FileOutputStream out = new FileOutputStream(file)) {
            out.write(placeholderHeader());
            out.write(new byte[32000]);
        }
        long duration = WavRepair.repair(file);
        assertEquals(1000, duration);

        byte[] head = new byte[44];
        try (java.io.FileInputStream in = new java.io.FileInputStream(file)) {
            assertEquals(44, in.read(head));
        }
        assertEquals('R', head[0]);
        assertEquals('I', head[1]);
        assertEquals('F', head[2]);
        assertEquals('F', head[3]);
        ByteBuffer buffer = ByteBuffer.wrap(head).order(ByteOrder.LITTLE_ENDIAN);
        assertEquals(32000 + 36, buffer.getInt(4));
        assertEquals(32000, buffer.getInt(40));
    }

    @Test
    public void rejectsShortOrInvalidFile() throws Exception {
        File file = File.createTempFile("mm_rec_bad_", ".wav");
        file.deleteOnExit();
        try (FileOutputStream out = new FileOutputStream(file)) {
            out.write(new byte[10]);
        }
        assertEquals(0, WavRepair.repair(file));

        File missing = new File(file.getParentFile(), "missing-" + System.nanoTime() + ".wav");
        assertEquals(0, WavRepair.repair(missing));
    }

    @Test
    public void repairedFileHasValidWaveMagic() throws Exception {
        File file = File.createTempFile("mm_rec_magic_", ".wav");
        file.deleteOnExit();
        try (FileOutputStream out = new FileOutputStream(file)) {
            out.write(placeholderHeader());
            out.write(new byte[64]);
        }
        WavRepair.repair(file);
        byte[] head = new byte[12];
        try (java.io.FileInputStream in = new java.io.FileInputStream(file)) {
            assertTrue(in.read(head) == 12);
        }
        assertEquals("RIFF", new String(head, 0, 4));
        assertEquals("WAVE", new String(head, 8, 4));
    }

    /** 模拟录音刚创建、尚未写入数据时的合法 WAV 头。 */
    private static byte[] placeholderHeader() {
        ByteBuffer buffer = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN);
        buffer.put("RIFF".getBytes());
        buffer.putInt(36);
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
        buffer.putInt(0);
        return buffer.array();
    }
}
