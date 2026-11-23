package com.zjh.meetingmemory.ui;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import com.zjh.meetingmemory.R;
import com.zjh.meetingmemory.data.LocalRecording;
import com.zjh.meetingmemory.databinding.ItemRecordingBinding;
import com.zjh.meetingmemory.util.Formats;

import java.util.ArrayList;
import java.util.List;

public class RecordingAdapter extends RecyclerView.Adapter<RecordingAdapter.Holder> {

    public interface Listener {
        void onClick(LocalRecording item);

        void onMenu(LocalRecording item, View anchor);
    }

    private final List<LocalRecording> items = new ArrayList<>();
    private final Listener listener;

    public RecordingAdapter(Listener listener) {
        this.listener = listener;
    }

    public void submit(List<LocalRecording> data) {
        items.clear();
        items.addAll(data);
        notifyDataSetChanged();
    }

    @NonNull
    @Override
    public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        ItemRecordingBinding binding = ItemRecordingBinding.inflate(
                LayoutInflater.from(parent.getContext()), parent, false);
        return new Holder(binding);
    }

    @Override
    public void onBindViewHolder(@NonNull Holder holder, int position) {
        LocalRecording item = items.get(position);
        holder.binding.tvTitle.setText(item.title);
        StringBuilder meta = new StringBuilder();
        if (item.project != null && !item.project.isEmpty()) {
            meta.append(item.project).append(" · ");
        }
        meta.append(Formats.dateTime(item.startedAt));
        if (item.durationMs > 0) {
            meta.append(" · ").append(Formats.spokenDuration(item.durationMs));
        }
        if (item.sizeBytes > 0) {
            meta.append(" · ").append(Formats.size(item.sizeBytes));
        }
        if ((LocalRecording.FAILED.equals(item.state)
                || LocalRecording.AUTH.equals(item.state))
                && item.error != null && !item.error.isEmpty()) {
            meta.append("\n").append(item.error);
        }
        holder.binding.tvMeta.setText(meta.toString());
        Formats.pill(holder.binding.tvStatus, item.stateLabel(holder.itemView.getContext()),
                item.stateColor(holder.itemView.getContext()));
        holder.binding.getRoot().setOnClickListener(view -> listener.onClick(item));
        holder.binding.btnMore.setOnClickListener(view -> listener.onMenu(item, view));
    }

    @Override
    public int getItemCount() {
        return items.size();
    }

    static class Holder extends RecyclerView.ViewHolder {
        final ItemRecordingBinding binding;

        Holder(ItemRecordingBinding binding) {
            super(binding.getRoot());
            this.binding = binding;
        }
    }
}
