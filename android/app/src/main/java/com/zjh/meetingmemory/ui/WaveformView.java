package com.zjh.meetingmemory.ui;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.util.AttributeSet;
import android.view.View;

import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;

import com.zjh.meetingmemory.R;

/** 极简实时波形，只在录音页使用。 */
public class WaveformView extends View {

    private final float[] levels = new float[56];
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private float density;

    public WaveformView(Context context, @Nullable AttributeSet attrs) {
        super(context, attrs);
        density = getResources().getDisplayMetrics().density;
        paint.setColor(ContextCompat.getColor(context, R.color.orange));
        paint.setStrokeWidth(3f * density);
        paint.setStrokeCap(Paint.Cap.ROUND);
    }

    public void push(float level) {
        System.arraycopy(levels, 1, levels, 0, levels.length - 1);
        levels[levels.length - 1] = Math.max(0f, Math.min(1f, level));
        invalidate();
    }

    public void clear() {
        for (int i = 0; i < levels.length; i++) {
            levels[i] = 0;
        }
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float center = getHeight() / 2f;
        float step = getWidth() / (float) levels.length;
        float max = getHeight() * 0.42f;
        float min = 1.5f * density;
        for (int i = 0; i < levels.length; i++) {
            float x = step * i + step / 2f;
            float amplitude = levels[i];
            float height = Math.max(min, amplitude * max);
            int alpha = 80 + (int) (amplitude * 175);
            paint.setAlpha(alpha);
            canvas.drawLine(x, center - height, x, center + height, paint);
        }
    }
}
