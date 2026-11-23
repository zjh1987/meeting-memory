package com.zjh.meetingmemory.ui;

import android.content.Intent;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.zjh.meetingmemory.R;
import com.zjh.meetingmemory.core.ApiClient;
import com.zjh.meetingmemory.core.AppPrefs;
import com.zjh.meetingmemory.core.Models;
import com.zjh.meetingmemory.databinding.FragmentMeetingsBinding;
import com.zjh.meetingmemory.util.Formats;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MeetingsFragment extends Fragment {

    private FragmentMeetingsBinding binding;
    private AppPrefs prefs;
    private ExecutorService executor;
    private MeetingAdapter adapter;

    private final List<Models.Meeting> meetings = new ArrayList<>();
    private final List<Models.Project> projects = new ArrayList<>();

    private int page = 1;
    private boolean hasMore = true;
    private boolean loading;
    private String statusFilter = null;
    private Integer projectFilter = null;
    private long lastLoadedAt;
    private boolean projectsLoaded;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentMeetingsBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);
        prefs = new AppPrefs(requireContext());
        executor = Executors.newSingleThreadExecutor();

        adapter = new MeetingAdapter(meeting -> startActivity(
                MeetingDetailActivity.intent(requireContext(), meeting.uid, meeting.title)));
        LinearLayoutManager manager = new LinearLayoutManager(requireContext());
        binding.rvMeetings.setLayoutManager(manager);
        binding.rvMeetings.setAdapter(adapter);

        binding.swipe.setOnRefreshListener(() -> {
            loadProjects();
            loadPage(true);
        });
        binding.btnRefresh.setOnClickListener(v -> {
            binding.swipe.setRefreshing(true);
            loadProjects();
            loadPage(true);
        });
        binding.chipAll.setOnClickListener(v -> setStatus(null));
        binding.chipDone.setOnClickListener(v -> setStatus("done"));
        binding.chipFailed.setOnClickListener(v -> setStatus("failed"));

        setupProjectFilter();

        binding.rvMeetings.addOnScrollListener(new RecyclerView.OnScrollListener() {
            @Override
            public void onScrolled(@NonNull RecyclerView recyclerView, int dx, int dy) {
                if (dy <= 0 || loading || !hasMore) {
                    return;
                }
                int last = manager.findLastVisibleItemPosition();
                if (last >= adapter.getItemCount() - 3) {
                    loadPage(false);
                }
            }
        });

        loadProjects();
        loadPage(true);
    }

    private void setupProjectFilter() {
        binding.actProjectFilter.setAdapter(new ArrayAdapter<>(requireContext(),
                android.R.layout.simple_list_item_1, new ArrayList<>()));
        binding.actProjectFilter.setThreshold(0);
        binding.actProjectFilter.setOnClickListener(v ->
                binding.actProjectFilter.showDropDown());
        binding.actProjectFilter.setOnItemClickListener((parent, view, position, id) -> {
            if (position == 0) {
                projectFilter = null;
            } else if (position - 1 < projects.size()) {
                projectFilter = projects.get(position - 1).id;
            }
            loadPage(true);
        });
    }

    private void setStatus(String status) {
        statusFilter = status;
        loadPage(true);
    }

    private void loadProjects() {
        if (!prefs.isConfigured()) {
            return;
        }
        ApiClient.get(requireContext()).get("/api/projects", new ApiClient.ApiCallback() {
            @Override
            public void onResponse(int code, String body) {
                if (code != 200) {
                    return;
                }
                List<Models.Project> items = new ArrayList<>();
                try {
                    JSONArray array = new JSONObject(body).optJSONArray("items");
                    if (array != null) {
                        for (int i = 0; i < array.length(); i++) {
                            JSONObject json = array.getJSONObject(i);
                            Models.Project project = new Models.Project();
                            project.id = json.optInt("id");
                            project.name = json.optString("name", "");
                            if (!project.name.isEmpty()) {
                                items.add(project);
                            }
                        }
                    }
                } catch (Exception ignored) {
                }
                if (getActivity() == null) {
                    return;
                }
                getActivity().runOnUiThread(() -> applyProjects(items));
            }

            @Override
            public void onFailure(IOException error) {
            }
        });
    }

    private void applyProjects(List<Models.Project> items) {
        if (binding == null) {
            return;
        }
        projects.clear();
        projects.addAll(items);
        List<String> names = new ArrayList<>();
        names.add(getString(R.string.all_projects));
        for (Models.Project project : items) {
            names.add(project.name);
        }
        ArrayAdapter<String> projectAdapter = new ArrayAdapter<>(requireContext(),
                android.R.layout.simple_list_item_1, names);
        binding.actProjectFilter.setAdapter(projectAdapter);
        if (binding.actProjectFilter.getText().toString().isEmpty()) {
            binding.actProjectFilter.setText(getString(R.string.all_projects), false);
        }
        projectsLoaded = true;
    }

    private void loadPage(boolean reset) {
        if (loading) {
            return;
        }
        if (!reset && !hasMore) {
            return;
        }
        if (!prefs.isConfigured()) {
            binding.swipe.setRefreshing(false);
            showEmpty("登录已过期，请重新登录");
            return;
        }
        if (reset) {
            page = 1;
            hasMore = true;
        }
        loading = true;
        if (reset) {
            binding.loadingMore.setVisibility(View.GONE);
        } else {
            binding.loadingMore.setVisibility(View.VISIBLE);
        }
        int requestPage = page;
        StringBuilder path = new StringBuilder("/api/meetings?page=")
                .append(requestPage).append("&size=20");
        if (statusFilter != null) {
            path.append("&status=").append(statusFilter);
        }
        if (projectFilter != null) {
            path.append("&project_id=").append(projectFilter);
        }
        ApiClient.get(requireContext()).get(path.toString(), new ApiClient.ApiCallback() {
            @Override
            public void onResponse(int code, String body) {
                if (binding == null || getActivity() == null) {
                    return;
                }
                getActivity().runOnUiThread(() -> {
                    loading = false;
                    binding.swipe.setRefreshing(false);
                    binding.loadingMore.setVisibility(View.GONE);
                    if (code == 401) {
                        showEmpty("登录已过期，请重新登录");
                        snackWithAction("登录已过期", "登录",
                                () -> startActivity(new Intent(requireContext(),
                                        LoginActivity.class)
                                        .putExtra("from_settings", true)));
                        return;
                    }
                    if (code != 200) {
                        snack("加载失败（HTTP " + code + "）");
                        return;
                    }
                    try {
                        JSONObject json = new JSONObject(body);
                        int total = json.optInt("total", 0);
                        JSONArray array = json.optJSONArray("items");
                        if (reset) {
                            meetings.clear();
                        }
                        if (array != null) {
                            for (int i = 0; i < array.length(); i++) {
                                meetings.add(Models.Meeting.from(array.getJSONObject(i)));
                            }
                        }
                        hasMore = meetings.size() < total;
                        page = requestPage + 1;
                        adapter.submit(meetings);
                        binding.emptyView.setVisibility(
                                meetings.isEmpty() ? View.VISIBLE : View.GONE);
                        lastLoadedAt = System.currentTimeMillis();
                    } catch (Exception e) {
                        snack("解析会议列表失败");
                    }
                });
            }

            @Override
            public void onFailure(IOException error) {
                if (binding == null || getActivity() == null) {
                    return;
                }
                getActivity().runOnUiThread(() -> {
                    loading = false;
                    binding.swipe.setRefreshing(false);
                    binding.loadingMore.setVisibility(View.GONE);
                    if (meetings.isEmpty()) {
                        showEmpty("无法连接服务器");
                    }
                    snack(ApiClient.friendlyError(error));
                });
            }
        });
    }

    private void showEmpty(String message) {
        binding.emptyView.setVisibility(View.VISIBLE);
        binding.tvEmpty.setText(message);
    }

    private void snack(String text) {
        if (binding != null) {
            com.google.android.material.snackbar.Snackbar.make(binding.getRoot(), text,
                    com.google.android.material.snackbar.Snackbar.LENGTH_LONG).show();
        }
    }

    private void snackWithAction(String text, String action, Runnable callback) {
        if (binding == null) {
            return;
        }
        com.google.android.material.snackbar.Snackbar bar =
                com.google.android.material.snackbar.Snackbar.make(binding.getRoot(),
                        text, com.google.android.material.snackbar.Snackbar.LENGTH_LONG);
        bar.setAction(action, view -> callback.run());
        bar.show();
    }

    @Override
    public void onResume() {
        super.onResume();
        if (!isHidden() && System.currentTimeMillis() - lastLoadedAt > 30000) {
            loadPage(true);
        }
        if (!projectsLoaded) {
            loadProjects();
        }
    }

    @Override
    public void onHiddenChanged(boolean hidden) {
        super.onHiddenChanged(hidden);
        if (!hidden && System.currentTimeMillis() - lastLoadedAt > 30000) {
            loadPage(true);
        }
    }

    @Override
    public void onDestroy() {
        if (executor != null) {
            executor.shutdownNow();
        }
        super.onDestroy();
    }
}
