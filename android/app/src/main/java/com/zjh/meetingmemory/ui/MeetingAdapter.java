package com.zjh.meetingmemory.ui;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import com.zjh.meetingmemory.R;
import com.zjh.meetingmemory.core.Models;
import com.zjh.meetingmemory.databinding.ItemMeetingBinding;
import com.zjh.meetingmemory.databinding.ItemMonthHeaderBinding;
import com.zjh.meetingmemory.util.Formats;

import java.util.ArrayList;
import java.util.List;

public class MeetingAdapter extends RecyclerView.Adapter<RecyclerView.ViewHolder> {

    private static final int TYPE_MONTH = 0;
    private static final int TYPE_MEETING = 1;

    public interface Listener {
        void onClick(Models.Meeting meeting);
    }

    private final List<Object> rows = new ArrayList<>();
    private final Listener listener;

    public MeetingAdapter(Listener listener) {
        this.listener = listener;
    }

    public void submit(List<Models.Meeting> meetings) {
        rows.clear();
        String lastMonth = "";
        for (Models.Meeting meeting : meetings) {
            String month = Formats.monthLabel(meeting.recordedAt);
            if (!month.equals(lastMonth)) {
                rows.add(month);
                lastMonth = month;
            }
            rows.add(meeting);
        }
        notifyDataSetChanged();
    }

    @Override
    public int getItemViewType(int position) {
        return rows.get(position) instanceof String ? TYPE_MONTH : TYPE_MEETING;
    }

    @NonNull
    @Override
    public RecyclerView.ViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        LayoutInflater inflater = LayoutInflater.from(parent.getContext());
        if (viewType == TYPE_MONTH) {
            return new MonthHolder(ItemMonthHeaderBinding.inflate(inflater, parent, false));
        }
        return new MeetingHolder(ItemMeetingBinding.inflate(inflater, parent, false));
    }

    @Override
    public void onBindViewHolder(@NonNull RecyclerView.ViewHolder holder, int position) {
        Object row = rows.get(position);
        if (holder instanceof MonthHolder && row instanceof String) {
            ((MonthHolder) holder).binding.tvMonth.setText((String) row);
            return;
        }
        if (!(holder instanceof MeetingHolder) || !(row instanceof Models.Meeting)) {
            return;
        }
        MeetingHolder meetingHolder = (MeetingHolder) holder;
        Models.Meeting meeting = (Models.Meeting) row;
        ItemMeetingBinding binding = meetingHolder.binding;
        binding.tvTitle.setText(meeting.title);
        StringBuilder meta = new StringBuilder();
        if (meeting.projectName != null && !meeting.projectName.isEmpty()) {
            meta.append(meeting.projectName).append(" · ");
        }
        String time = Formats.fromServerTime(meeting.recordedAt);
        meta.append(time.isEmpty() ? "时间未知" : time);
        if (meeting.durationSec > 0) {
            meta.append(" · ").append(Formats.spokenDuration((long) (meeting.durationSec * 1000)));
        }
        binding.tvMeta.setText(meta.toString());
        int color;
        switch (meeting.status) {
            case "done":
                color = holder.itemView.getContext().getColor(R.color.green);
                break;
            case "failed":
                color = holder.itemView.getContext().getColor(R.color.red);
                break;
            case "transcribing":
            case "minuting":
            case "relating":
            case "pending":
            case "uploading":
                color = holder.itemView.getContext().getColor(R.color.blue);
                break;
            default:
                color = holder.itemView.getContext().getColor(R.color.text_muted);
                break;
        }
        Formats.pill(binding.tvStatus, Formats.serverStatus(meeting.status), color);
        if ("failed".equals(meeting.status)
                && meeting.errorMsg != null && !meeting.errorMsg.isEmpty()) {
            String message = meeting.errorMsg;
            if (message.length() > 90) {
                message = message.substring(0, 90) + "…";
            }
            binding.tvActions.setVisibility(View.VISIBLE);
            binding.tvActions.setText("失败原因：" + message);
            binding.tvActions.setTextColor(
                    holder.itemView.getContext().getColor(R.color.red));
        } else if (meeting.openActions > 0) {
            binding.tvActions.setVisibility(View.VISIBLE);
            binding.tvActions.setText(meeting.openActions + " 项待办待跟进");
            binding.tvActions.setTextColor(
                    holder.itemView.getContext().getColor(R.color.orange));
        } else {
            binding.tvActions.setVisibility(View.GONE);
        }
        binding.getRoot().setOnClickListener(view -> listener.onClick(meeting));
    }

    @Override
    public int getItemCount() {
        return rows.size();
    }

    static class MonthHolder extends RecyclerView.ViewHolder {
        final ItemMonthHeaderBinding binding;

        MonthHolder(ItemMonthHeaderBinding binding) {
            super(binding.getRoot());
            this.binding = binding;
        }
    }

    static class MeetingHolder extends RecyclerView.ViewHolder {
        final ItemMeetingBinding binding;

        MeetingHolder(ItemMeetingBinding binding) {
            super(binding.getRoot());
            this.binding = binding;
        }
    }
}
