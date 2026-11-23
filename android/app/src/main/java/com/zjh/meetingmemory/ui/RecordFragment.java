package com.zjh.meetingmemory.ui;

import android.Manifest;
import android.content.ContentResolver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.OpenableColumns;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.InputMethodManager;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.PopupMenu;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AlertDialog;
import androidx.core.content.ContextCompat;
import androidx.core.content.FileProvider;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.LinearLayoutManager;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.textfield.TextInputLayout;
import com.zjh.meetingmemory.R;
import com.zjh.meetingmemory.core.ApiClient;
import com.zjh.meetingmemory.core.AppPrefs;
import com.zjh.meetingmemory.core.Defaults;
import com.zjh.meetingmemory.core.Models;
import com.zjh.meetingmemory.data.LocalRecording;
import com.zjh.meetingmemory.data.LocalStore;
import com.zjh.meetingmemory.databinding.FragmentRecordBinding;
import com.zjh.meetingmemory.net.UploadWorker;
import com.zjh.meetingmemory.recording.RecordingFiles;
import com.zjh.meetingmemory.recording.RecordingService;
import com.zjh.meetingmemory.recording.RecordingState;
import com.zjh.meetingmemory.util.Formats;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import okhttp3.Response;

public class RecordFragment extends Fragment {

    private static final long GB = 1024L * 1024 * 1024;
    private static final long MIN_FREE_BYTES = 300L * 1024 * 1024;
    private static final List<String> AUDIO_EXTENSIONS = Arrays.asList(
            ".m4a", ".mp3", ".wav", ".opus", ".aac", ".amr", ".flac");

    private FragmentRecordBinding binding;
    private AppPrefs prefs;
    private LocalStore store;
    private ExecutorService executor;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private RecordingAdapter adapter;

    private final List<Models.Project> projects = new ArrayList<>();
    private final List<String> projectNames = new ArrayList<>();
    private final List<Models.Template> templates = new ArrayList<>();
    private String templateKey = "standard";
    private String templateName = "常规会议";

    private ActivityResultLauncher<String> recordPermission;
    private ActivityResultLauncher<String> notificationPermission;
    private ActivityResultLauncher<String[]> importAudioLauncher;
    private boolean pendingAfterPermission;
    private boolean importing;

    private MediaPlayer player;
    private long playingId = -1;
    private boolean pollingStatus;
    private boolean lastActive;
    private long lastPollAt;

    private final Runnable uiTicker = new Runnable() {
        @Override
        public void run() {
            updateRecordUi();
            handler.postDelayed(this, 160);
        }
    };

    private final Runnable refreshTicker = new Runnable() {
        @Override
        public void run() {
            refreshLocal();
            refreshCapacity();
            if (System.currentTimeMillis() - lastPollAt > 12000) {
                lastPollAt = System.currentTimeMillis();
                pollServerStatuses();
            }
            handler.postDelayed(this, 2500);
        }
    };

    @Override
    public void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        recordPermission = registerForActivityResult(
                new ActivityResultContracts.RequestPermission(), granted -> {
                    if (granted && pendingAfterPermission) {
                        pendingAfterPermission = false;
                        startRecordingInternal();
                    } else if (!granted) {
                        pendingAfterPermission = false;
                        snack("需要麦克风权限才能录音，请在系统设置中开启");
                    }
                });
        notificationPermission = registerForActivityResult(
                new ActivityResultContracts.RequestPermission(), granted -> {
                });
        importAudioLauncher = registerForActivityResult(
                new ActivityResultContracts.OpenDocument(), uri -> {
                    if (uri != null) {
                        importAudio(uri);
                    }
                });
    }

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        binding = FragmentRecordBinding.inflate(inflater, container, false);
        return binding.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);
        prefs = new AppPrefs(requireContext());
        store = LocalStore.get(requireContext());
        executor = Executors.newSingleThreadExecutor();

        adapter = new RecordingAdapter(new RecordingAdapter.Listener() {
            @Override
            public void onClick(LocalRecording item) {
                handleItemClick(item);
            }

            @Override
            public void onMenu(LocalRecording item, View anchor) {
                showItemMenu(item, anchor);
            }
        });
        binding.rvRecordings.setLayoutManager(new LinearLayoutManager(requireContext()));
        binding.rvRecordings.setAdapter(adapter);

        setupProjectInput();
        setupTemplateInput();

        binding.btnRecord.setOnClickListener(view1 -> {
            if (RecordingState.active) {
                confirmStop();
            } else {
                requestStart();
            }
        });
        binding.btnPause.setOnClickListener(view12 -> {
            if (!RecordingState.active) {
                return;
            }
            if (RecordingState.paused) {
                sendServiceAction(RecordingService.ACTION_RESUME);
            } else {
                sendServiceAction(RecordingService.ACTION_PAUSE);
            }
        });
        binding.btnStop.setOnClickListener(view13 -> confirmStop());
        binding.btnImport.setOnClickListener(view14 -> {
            if (!importing) {
                importAudioLauncher.launch(new String[]{"*/*"});
            }
        });

        loadCachedData();
        refreshFromServer();
        refreshLocal();
        refreshCapacity();
        updateRecordUi();
    }

    private void setupProjectInput() {
        rebuildProjectAdapter();
        binding.actProject.setOnClickListener(v -> {
            if (!binding.actProject.isEnabled()) {
                return;
            }
            if (projectNames.isEmpty()) {
                showNewProjectDialog();
            } else {
                binding.actProject.showDropDown();
            }
        });
        binding.actProject.setOnFocusChangeListener((v, hasFocus) -> {
            if (hasFocus && !projectNames.isEmpty()) {
                binding.actProject.showDropDown();
            }
        });
        binding.actProject.setOnItemClickListener((parent, view, position, id) -> {
            Object value = parent.getItemAtPosition(position);
            if (value != null) {
                prefs.setLastProject(value.toString());
                binding.tilProject.setError(null);
            }
        });
        binding.tilProject.setEndIconOnClickListener(v -> showNewProjectDialog());
    }

    private void rebuildProjectAdapter() {
        ArrayAdapter<String> projectAdapter = new ArrayAdapter<>(requireContext(),
                android.R.layout.simple_list_item_1, new ArrayList<>(projectNames));
        binding.actProject.setAdapter(projectAdapter);
    }

    private void showNewProjectDialog() {
        if (binding == null || !binding.actProject.isEnabled()) {
            return;
        }
        View content = getLayoutInflater().inflate(R.layout.dialog_new_project, null);
        TextInputLayout til = content.findViewById(R.id.til_new_project);
        EditText input = content.findViewById(R.id.et_new_project);
        AlertDialog dialog = new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.new_project)
                .setView(content)
                .setNegativeButton(R.string.cancel, null)
                .setPositiveButton(R.string.create, null)
                .create();
        dialog.setOnShowListener(ignored -> {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
                String name = input.getText().toString().trim();
                if (name.isEmpty()) {
                    til.setError(getString(R.string.new_project_empty));
                    return;
                }
                til.setError(null);
                addProject(name);
                dialog.dismiss();
            });
        });
        dialog.show();
        input.requestFocus();
        InputMethodManager manager = (InputMethodManager)
                requireContext().getSystemService(Context.INPUT_METHOD_SERVICE);
        if (manager != null) {
            input.post(() -> manager.showSoftInput(input, InputMethodManager.SHOW_IMPLICIT));
        }
    }

    private void addProject(String name) {
        if (!projectNames.contains(name)) {
            projectNames.add(name);
            rebuildProjectAdapter();
        }
        binding.actProject.setText(name, false);
        prefs.setLastProject(name);
        binding.tilProject.setError(null);
    }

    private void setupTemplateInput() {
        ArrayAdapter<String> templateAdapter = new ArrayAdapter<>(requireContext(),
                android.R.layout.simple_list_item_1, new ArrayList<>());
        binding.actTemplate.setAdapter(templateAdapter);
        binding.actTemplate.setThreshold(0);
        binding.actTemplate.setOnClickListener(v -> binding.actTemplate.showDropDown());
        binding.actTemplate.setOnFocusChangeListener((v, hasFocus) -> {
            if (hasFocus) {
                binding.actTemplate.showDropDown();
            }
        });
        binding.actTemplate.setOnItemClickListener((parent, view, position, id) -> {
            if (position >= 0 && position < templates.size()) {
                Models.Template template = templates.get(position);
                templateKey = template.key;
                templateName = template.name;
                prefs.setLastTemplate(template.key);
            }
        });
    }

    private void loadCachedData() {
        List<Models.Project> cachedProjects = parseProjects(prefs.cachedProjects());
        if (!cachedProjects.isEmpty()) {
            applyProjects(cachedProjects, false);
        }
        List<Models.Template> cachedTemplates = parseTemplates(prefs.cachedTemplates());
        if (cachedTemplates.isEmpty()) {
            cachedTemplates = Defaults.templates();
        }
        applyTemplates(cachedTemplates);
    }

    private void refreshFromServer() {
        if (!prefs.isConfigured()) {
            setServerState(false, "未登录，请先登录服务器");
            return;
        }
        long started = System.currentTimeMillis();
        ApiClient.get(requireContext()).get("/healthz", new ApiClient.ApiCallback() {
            @Override
            public void onResponse(int code, String body) {
                long latency = System.currentTimeMillis() - started;
                handler.post(() -> {
                    if (code == 200) {
                        setServerState(true, "服务器在线 · " + latency + " ms");
                    } else {
                        setServerState(false, "服务器返回 " + code);
                    }
                });
            }

            @Override
            public void onFailure(IOException error) {
                handler.post(() -> setServerState(false,
                        ApiClient.friendlyError(error)));
            }
        });
        ApiClient.get(requireContext()).get("/api/projects", new ApiClient.ApiCallback() {
            @Override
            public void onResponse(int code, String body) {
                if (code == 200) {
                    prefs.setCachedProjects(body);
                    List<Models.Project> items = parseProjects(body);
                    handler.post(() -> applyProjects(items, true));
                } else if (code == 401) {
                    handler.post(() -> {
                        setServerState(false, "登录已过期，请重新登录");
                        snackWithAction("登录已过期", "登录", () -> openLogin());
                    });
                }
            }

            @Override
            public void onFailure(IOException error) {
                // 离线时保留缓存项目。
            }
        });
        ApiClient.get(requireContext()).get("/api/templates", new ApiClient.ApiCallback() {
            @Override
            public void onResponse(int code, String body) {
                if (code == 200) {
                    prefs.setCachedTemplates(body);
                    List<Models.Template> items = parseTemplates(body);
                    if (!items.isEmpty()) {
                        handler.post(() -> applyTemplates(items));
                    }
                }
            }

            @Override
            public void onFailure(IOException error) {
            }
        });
    }

    private List<Models.Project> parseProjects(String body) {
        List<Models.Project> result = new ArrayList<>();
        if (body == null || body.isEmpty()) {
            return result;
        }
        try {
            JSONArray array = new JSONObject(body).optJSONArray("items");
            if (array == null) {
                return result;
            }
            for (int i = 0; i < array.length(); i++) {
                JSONObject json = array.getJSONObject(i);
                Models.Project project = new Models.Project();
                project.id = json.optInt("id");
                project.name = json.optString("name", "");
                if (!project.name.isEmpty()) {
                    result.add(project);
                }
            }
        } catch (Exception ignored) {
        }
        return result;
    }

    private List<Models.Template> parseTemplates(String body) {
        List<Models.Template> result = new ArrayList<>();
        if (body == null || body.isEmpty()) {
            return result;
        }
        try {
            JSONArray array = new JSONObject(body).optJSONArray("items");
            if (array == null) {
                return result;
            }
            for (int i = 0; i < array.length(); i++) {
                result.add(Models.Template.from(array.getJSONObject(i)));
            }
        } catch (Exception ignored) {
        }
        return result;
    }

    private void applyProjects(List<Models.Project> items, boolean fromServer) {
        if (binding == null) {
            return;
        }
        projects.clear();
        projects.addAll(items);
        projectNames.clear();
        for (Models.Project project : items) {
            projectNames.add(project.name);
        }
        rebuildProjectAdapter();
        String current = binding.actProject.getText().toString().trim();
        if (!current.isEmpty() && !projectNames.contains(current)) {
            // 新建但尚未上传的项目：服务端还没有，不能把它冲掉。
            projectNames.add(current);
            rebuildProjectAdapter();
            binding.actProject.setText(current, false);
        } else if (current.isEmpty()) {
            String last = prefs.lastProject();
            if (projectNames.contains(last)) {
                binding.actProject.setText(last, false);
            } else if (!last.isEmpty()) {
                projectNames.add(last);
                rebuildProjectAdapter();
                binding.actProject.setText(last, false);
            } else if (!projectNames.isEmpty()) {
                binding.actProject.setText(projectNames.get(0), false);
                prefs.setLastProject(projectNames.get(0));
            }
        }
    }

    private void applyTemplates(List<Models.Template> items) {
        if (binding == null) {
            return;
        }
        templates.clear();
        templates.addAll(items);
        List<String> names = new ArrayList<>();
        for (Models.Template template : items) {
            String label = template.name;
            if (template.scene != null && !template.scene.isEmpty()
                    && !template.scene.equals(template.name)) {
                label += " · " + template.scene;
            }
            names.add(label);
        }
        ArrayAdapter<String> templateAdapter = new ArrayAdapter<>(requireContext(),
                android.R.layout.simple_list_item_1, names);
        binding.actTemplate.setAdapter(templateAdapter);

        String wanted = prefs.lastTemplate();
        int index = 0;
        boolean found = false;
        for (int i = 0; i < items.size(); i++) {
            if (items.get(i).key.equals(wanted)) {
                index = i;
                found = true;
                break;
            }
        }
        if (!items.isEmpty()) {
            Models.Template selected = items.get(index);
            templateKey = selected.key;
            templateName = selected.name;
            binding.actTemplate.setText(selected.name, false);
            if (!found) {
                prefs.setLastTemplate(selected.key);
            }
        }
    }

    private void importAudio(Uri uri) {
        if (binding == null) {
            return;
        }
        Context app = requireContext().getApplicationContext();
        ContentResolver resolver = app.getContentResolver();
        try {
            resolver.takePersistableUriPermission(uri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION);
        } catch (Exception ignored) {
        }
        String displayName = null;
        try (Cursor cursor = resolver.query(uri,
                new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE},
                null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) {
                displayName = cursor.getString(0);
            }
        } catch (Exception ignored) {
        }
        String ext = extensionOf(displayName);
        if (!isAudioExtension(ext)) {
            ext = extensionFromMime(resolver.getType(uri));
        }
        if (!isAudioExtension(ext)) {
            snack(getString(R.string.import_invalid));
            return;
        }
        String project = binding.actProject.getText().toString().trim();
        if (project.isEmpty()) {
            project = "未分类";
        }
        String title = displayName == null ? "导入的录音" : stripExtension(displayName);
        if (title.trim().isEmpty()) {
            title = "导入的录音";
        }
        final String finalProject = project;
        final String finalTitle = title;
        final String finalExt = ext;
        final String finalTemplateKey = templateKey;
        final String finalTemplateName = templateName;
        importing = true;
        binding.btnImport.setEnabled(false);
        snack(getString(R.string.importing));
        executor.execute(() -> {
            File dest = RecordingFiles.newImportedFile(app, finalExt);
            try (InputStream input = resolver.openInputStream(uri);
                 OutputStream output = new FileOutputStream(dest)) {
                if (input == null) {
                    throw new IOException("无法读取所选文件");
                }
                byte[] buffer = new byte[64 * 1024];
                int read;
                long total = 0;
                while ((read = input.read(buffer)) != -1) {
                    output.write(buffer, 0, read);
                    total += read;
                }
                if (total == 0) {
                    throw new IOException("文件为空");
                }
            } catch (Exception error) {
                //noinspection ResultOfMethodCallIgnored
                dest.delete();
                handler.post(() -> {
                    importing = false;
                    if (binding != null) {
                        binding.btnImport.setEnabled(true);
                        snack(getString(R.string.import_failed)
                                + (error.getMessage() == null ? "" : error.getMessage()));
                    }
                });
                return;
            }
            LocalRecording item = new LocalRecording();
            item.title = finalTitle;
            item.project = finalProject;
            item.templateKey = finalTemplateKey;
            item.templateName = finalTemplateName;
            item.filePath = dest.getAbsolutePath();
            item.startedAt = System.currentTimeMillis();
            item.durationMs = 0;
            item.sizeBytes = dest.length();
            item.state = LocalRecording.READY;
            long id;
            try {
                id = store.insert(item);
            } catch (Exception error) {
                //noinspection ResultOfMethodCallIgnored
                dest.delete();
                handler.post(() -> {
                    importing = false;
                    if (binding != null) {
                        binding.btnImport.setEnabled(true);
                        snack(getString(R.string.import_failed)
                                + (error.getMessage() == null ? "" : error.getMessage()));
                    }
                });
                return;
            }
            boolean autoUpload = prefs.autoUpload() && prefs.isConfigured();
            if (autoUpload) {
                UploadWorker.enqueue(app, id, false);
            }
            handler.post(() -> {
                importing = false;
                if (binding != null) {
                    binding.btnImport.setEnabled(true);
                    refreshLocal();
                    snack(getString(autoUpload
                            ? R.string.imported_uploading : R.string.imported_local));
                }
            });
        });
    }

    private String extensionOf(String name) {
        if (name == null) {
            return "";
        }
        int dot = name.lastIndexOf('.');
        return dot >= 0 ? name.substring(dot).toLowerCase(Locale.ROOT) : "";
    }

    private String extensionFromMime(String mime) {
        if (mime == null) {
            return "";
        }
        switch (mime.toLowerCase(Locale.ROOT)) {
            case "audio/mp4":
            case "audio/x-m4a":
                return ".m4a";
            case "audio/mpeg":
                return ".mp3";
            case "audio/wav":
            case "audio/x-wav":
                return ".wav";
            case "audio/ogg":
            case "audio/opus":
                return ".opus";
            case "audio/aac":
                return ".aac";
            case "audio/amr":
                return ".amr";
            case "audio/flac":
            case "audio/x-flac":
                return ".flac";
            default:
                return "";
        }
    }

    private boolean isAudioExtension(String ext) {
        return ext != null && AUDIO_EXTENSIONS.contains(ext);
    }

    private String stripExtension(String name) {
        int dot = name == null ? -1 : name.lastIndexOf('.');
        return dot > 0 ? name.substring(0, dot) : (name == null ? "" : name);
    }

    private void requestStart() {
        if (!prefs.isConfigured()) {
            openLogin();
            return;
        }
        String project = binding.actProject.getText().toString().trim();
        if (project.isEmpty()) {
            binding.tilProject.setError(getString(R.string.project_required));
            return;
        }
        binding.tilProject.setError(null);
        if (ContextCompat.checkSelfPermission(requireContext(),
                Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            pendingAfterPermission = true;
            recordPermission.launch(Manifest.permission.RECORD_AUDIO);
            return;
        }
        if (Build.VERSION.SDK_INT >= 33
                && ContextCompat.checkSelfPermission(requireContext(),
                Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS);
        }
        startRecordingInternal();
    }

    private void startRecordingInternal() {
        if (RecordingState.active) {
            return;
        }
        String project = binding.actProject.getText().toString().trim();
        if (project.isEmpty()) {
            binding.tilProject.setError(getString(R.string.project_required));
            return;
        }
        long free = RecordingFiles.dir(requireContext()).getUsableSpace();
        if (free < MIN_FREE_BYTES) {
            new MaterialAlertDialogBuilder(requireContext())
                    .setTitle("存储空间不足")
                    .setMessage("手机剩余空间不足 300 MB，无法开始长录音。请清理后重试。")
                    .setPositiveButton("知道了", null)
                    .show();
            return;
        }
        String title = binding.etTitle.getText().toString().trim();
        if (title.isEmpty()) {
            title = new SimpleDateFormat("M月d日 HH:mm", Locale.CHINA)
                    .format(new Date()) + " 录音";
        }
        prefs.setLastProject(project);
        prefs.setLastTemplate(templateKey);

        Intent intent = new Intent(requireContext(), RecordingService.class)
                .setAction(RecordingService.ACTION_START)
                .putExtra(RecordingService.EXTRA_TITLE, title)
                .putExtra(RecordingService.EXTRA_PROJECT, project)
                .putExtra(RecordingService.EXTRA_TEMPLATE_KEY, templateKey)
                .putExtra(RecordingService.EXTRA_TEMPLATE_NAME, templateName)
                .putExtra(RecordingService.EXTRA_MAX_MINUTES, prefs.maxMinutes());
        ContextCompat.startForegroundService(requireContext(), intent);
        binding.etTitle.setText("");
        binding.waveform.clear();
        hideKeyboard();
        snack("录音已开始，锁屏也会继续");
        handler.postDelayed(this::updateRecordUi, 400);
    }

    private void confirmStop() {
        boolean auto = prefs.autoUpload();
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle("结束本次录音？")
                .setMessage(auto
                        ? "结束后会自动上传到服务器，并生成结构化纪要。"
                        : "结束后会保存在本机，你可以稍后手动上传。")
                .setNegativeButton("继续录音", null)
                .setPositiveButton(auto ? "结束并上传" : "结束并保存",
                        (dialog, which) -> sendServiceAction(RecordingService.ACTION_STOP))
                .show();
    }

    private void sendServiceAction(String action) {
        try {
            Intent intent = new Intent(requireContext(), RecordingService.class)
                    .setAction(action);
            requireContext().startService(intent);
        } catch (Exception e) {
            snack("操作失败：" + e.getMessage());
        }
    }

    private void updateRecordUi() {
        if (binding == null) {
            return;
        }
        boolean active = RecordingState.active;
        if (active) {
            binding.tvTimer.setText(Formats.duration(RecordingState.elapsedMs()));
            binding.tvRecordHint.setText(RecordingState.paused
                    ? getString(R.string.paused_hint) : getString(R.string.recording_hint));
            binding.waveform.push(RecordingState.paused ? 0 : RecordingState.amplitude);
            binding.btnPause.setVisibility(View.VISIBLE);
            binding.btnStop.setVisibility(View.VISIBLE);
            binding.btnPause.setText(RecordingState.paused
                    ? getString(R.string.resume) : getString(R.string.pause));
            binding.btnPause.setIconResource(RecordingState.paused
                    ? R.drawable.ic_play : R.drawable.ic_pause);
            binding.btnRecord.setIconResource(R.drawable.ic_stop);
            binding.btnRecord.setContentDescription(getString(R.string.stop_record));
            binding.btnRecord.setBackgroundTintList(
                    android.content.res.ColorStateList.valueOf(
                            getColorCompat(R.color.red)));
            setInputsEnabled(false);
            long recorded = RecordingState.elapsedMs();
            long bytes = recorded * 32;
            binding.tvEstimate.setText("已录制 " + Formats.duration(recorded)
                    + " · 约 " + Formats.size(bytes) + " · "
                    + (prefs.maxMinutes() > 0
                    ? "最长 " + prefs.maxMinutes() + " 分钟" : "不限制时长"));
            if (!lastActive) {
                lastActive = true;
            }
        } else {
            binding.tvTimer.setText("00:00");
            binding.tvRecordHint.setText(R.string.idle_hint);
            if (lastActive) {
                binding.waveform.clear();
                lastActive = false;
                refreshLocal();
            }
            binding.btnPause.setVisibility(View.GONE);
            binding.btnStop.setVisibility(View.GONE);
            binding.btnRecord.setIconResource(R.drawable.ic_mic);
            binding.btnRecord.setContentDescription(getString(R.string.start_record));
            binding.btnRecord.setBackgroundTintList(
                    android.content.res.ColorStateList.valueOf(
                            getColorCompat(R.color.orange)));
            setInputsEnabled(true);
        }
    }

    private void setInputsEnabled(boolean enabled) {
        binding.etTitle.setEnabled(enabled);
        binding.actProject.setEnabled(enabled);
        binding.actTemplate.setEnabled(enabled);
        binding.btnRecord.setEnabled(true);
    }

    private void refreshCapacity() {
        if (binding == null) {
            return;
        }
        long free = RecordingFiles.dir(requireContext()).getUsableSpace();
        double freeGb = free / (double) GB;
        String limit = prefs.maxMinutes() > 0
                ? "单场最长 " + prefs.maxMinutes() + " 分钟" : "时长不限制";
        String text = "WAV · 约 115 MB/小时 · " + limit
                + " · 手机可用 " + String.format(Locale.CHINA, "%.1f", freeGb) + " GB";
        binding.tvEstimate.setText(text);
    }

    private void refreshLocal() {
        if (binding == null) {
            return;
        }
        List<LocalRecording> items = new ArrayList<>();
        for (LocalRecording item : store.listAll()) {
            if (!LocalRecording.RECORDING.equals(item.state)) {
                items.add(item);
            }
        }
        adapter.submit(items);
        binding.tvLocalEmpty.setVisibility(items.isEmpty() ? View.VISIBLE : View.GONE);
        int pending = 0;
        for (LocalRecording item : items) {
            if (LocalRecording.READY.equals(item.state)
                    || LocalRecording.FAILED.equals(item.state)
                    || LocalRecording.AUTH.equals(item.state)) {
                pending++;
            }
        }
        String count = items.isEmpty() ? "" : items.size() + " 条";
        if (pending > 0) {
            count += (count.isEmpty() ? "" : " · ") + pending + " 条待上传";
        }
        binding.tvLocalCount.setText(count);
    }

    private void pollServerStatuses() {
        if (pollingStatus || !prefs.isConfigured()) {
            return;
        }
        List<LocalRecording> targets = new ArrayList<>();
        for (LocalRecording item : store.listAll()) {
            if (item.hasServerUid() && (LocalRecording.UPLOADED.equals(item.state)
                    || LocalRecording.PROCESSING.equals(item.state))) {
                targets.add(item);
            }
        }
        if (targets.isEmpty()) {
            return;
        }
        pollingStatus = true;
        Context appContext = requireContext().getApplicationContext();
        executor.execute(() -> {
            boolean changed = false;
            for (LocalRecording item : targets) {
                try (Response response = ApiClient.get(appContext)
                        .getSync("/api/meetings/" + item.serverUid + "/status")) {
                    if (!response.isSuccessful()) {
                        continue;
                    }
                    String body = response.body() == null ? "" : response.body().string();
                    JSONObject json = new JSONObject(body);
                    String status = json.optString("status", "");
                    if ("done".equals(status)) {
                        store.setServerState(item.id, LocalRecording.DONE, "",
                                item.serverUid);
                        changed = true;
                    } else if ("failed".equals(status)) {
                        store.setServerState(item.id, LocalRecording.FAILED,
                                json.optString("error_msg", "服务器处理失败"),
                                item.serverUid);
                        changed = true;
                    } else {
                        store.setServerState(item.id, LocalRecording.PROCESSING,
                                "", item.serverUid);
                        changed = true;
                    }
                } catch (Exception ignored) {
                }
            }
            boolean finalChanged = changed;
            handler.post(() -> {
                pollingStatus = false;
                if (finalChanged) {
                    refreshLocal();
                }
            });
        });
    }

    private void setServerState(boolean online, String text) {
        if (binding == null) {
            return;
        }
        binding.serverDot.setBackgroundTintList(android.content.res.ColorStateList.valueOf(
                getColorCompat(online ? R.color.green : R.color.red)));
        binding.tvServerStatus.setText(text);
    }

    private void handleItemClick(LocalRecording item) {
        if (item.hasServerUid()) {
            openMeeting(item);
        } else if (LocalRecording.READY.equals(item.state)
                || LocalRecording.FAILED.equals(item.state)
                || LocalRecording.AUTH.equals(item.state)) {
            uploadItem(item);
        } else if (LocalRecording.PROCESSING.equals(item.state)) {
            snack("服务器正在转写，稍后下拉刷新或等待通知");
        }
    }

    private void showItemMenu(LocalRecording item, View anchor) {
        PopupMenu menu = new PopupMenu(requireContext(), anchor);
        int playId = 1;
        int openId = 2;
        int uploadId = 3;
        int renameId = 4;
        int shareId = 5;
        int deleteId = 6;
        menu.getMenu().add(0, playId, 0,
                playingId == item.id ? getString(R.string.action_stop_play)
                        : getString(R.string.action_play));
        if (item.hasServerUid()) {
            menu.getMenu().add(0, openId, 1, getString(R.string.action_open));
        }
        if (!LocalRecording.DONE.equals(item.state)
                && !LocalRecording.UPLOADED.equals(item.state)
                && !LocalRecording.PROCESSING.equals(item.state)) {
            menu.getMenu().add(0, uploadId, 2,
                    LocalRecording.READY.equals(item.state)
                            ? getString(R.string.action_upload) : getString(R.string.retry));
        }
        menu.getMenu().add(0, renameId, 3, getString(R.string.action_rename));
        menu.getMenu().add(0, shareId, 4, getString(R.string.action_share));
        menu.getMenu().add(0, deleteId, 5, getString(R.string.action_delete));
        menu.setOnMenuItemClickListener(menuItem -> {
            int id = menuItem.getItemId();
            if (id == playId) {
                togglePlay(item);
            } else if (id == openId) {
                openMeeting(item);
            } else if (id == uploadId) {
                uploadItem(item);
            } else if (id == renameId) {
                renameItem(item);
            } else if (id == shareId) {
                shareItem(item);
            } else if (id == deleteId) {
                deleteItem(item);
            }
            return true;
        });
        menu.show();
    }

    private void togglePlay(LocalRecording item) {
        if (playingId == item.id) {
            stopPlayer();
            return;
        }
        stopPlayer();
        File file = new File(item.filePath);
        if (!file.isFile()) {
            snack("音频文件不存在");
            return;
        }
        executor.execute(() -> {
            try {
                MediaPlayer mp = new MediaPlayer();
                mp.setDataSource(file.getAbsolutePath());
                mp.prepare();
                mp.setOnCompletionListener(player -> stopPlayer());
                handler.post(() -> {
                    player = mp;
                    playingId = item.id;
                    mp.start();
                    snack("正在播放：" + item.title);
                });
            } catch (Exception e) {
                handler.post(() -> snack("无法播放：" + e.getMessage()));
            }
        });
    }

    private void stopPlayer() {
        if (player != null) {
            try {
                player.stop();
            } catch (Exception ignored) {
            }
            player.release();
            player = null;
        }
        playingId = -1;
    }

    private void uploadItem(LocalRecording item) {
        if (!prefs.isConfigured()) {
            openLogin();
            return;
        }
        UploadWorker.enqueue(requireContext(), item.id, true);
        refreshLocal();
        snack(prefs.wifiOnly()
                ? "已加入上传队列，将在 Wi-Fi 下自动上传"
                : "已加入上传队列");
    }

    private void renameItem(LocalRecording item) {
        EditText input = new EditText(requireContext());
        input.setText(item.title);
        input.setSelection(input.getText().length());
        FrameLayout container = new FrameLayout(requireContext());
        int padding = (int) (20 * getResources().getDisplayMetrics().density);
        container.setPadding(padding, padding / 2, padding, 0);
        container.addView(input);
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.rename_title)
                .setView(container)
                .setNegativeButton(R.string.cancel, null)
                .setPositiveButton(R.string.confirm, (dialog, which) -> {
                    String title = input.getText().toString().trim();
                    if (title.isEmpty()) {
                        return;
                    }
                    store.updateTitle(item.id, title);
                    refreshLocal();
                })
                .show();
    }

    private void shareItem(LocalRecording item) {
        File file = new File(item.filePath);
        if (!file.isFile()) {
            snack("音频文件不存在");
            return;
        }
        try {
            Uri uri = FileProvider.getUriForFile(requireContext(),
                    requireContext().getPackageName() + ".files", file);
            Intent intent = new Intent(Intent.ACTION_SEND)
                    .setType("audio/wav")
                    .putExtra(Intent.EXTRA_STREAM, uri)
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            startActivity(Intent.createChooser(intent, "分享录音"));
        } catch (Exception e) {
            snack("分享失败：" + e.getMessage());
        }
    }

    private void deleteItem(LocalRecording item) {
        boolean uploaded = item.hasServerUid();
        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(R.string.delete_title)
                .setMessage(uploaded ? R.string.delete_msg_uploaded : R.string.delete_msg)
                .setNegativeButton(R.string.cancel, null)
                .setPositiveButton(R.string.action_delete, (dialog, which) -> {
                    File file = new File(item.filePath);
                    if (file.exists()) {
                        //noinspection ResultOfMethodCallIgnored
                        file.delete();
                    }
                    if (playingId == item.id) {
                        stopPlayer();
                    }
                    store.delete(item.id);
                    refreshLocal();
                })
                .show();
    }

    private void openMeeting(LocalRecording item) {
        if (!item.hasServerUid()) {
            return;
        }
        startActivity(MeetingDetailActivity.intent(requireContext(),
                item.serverUid, item.title));
    }

    private void openLogin() {
        startActivity(new Intent(requireContext(), LoginActivity.class)
                .putExtra("from_settings", true));
    }

    private void snack(String text) {
        if (binding == null) {
            return;
        }
        com.google.android.material.snackbar.Snackbar.make(
                binding.getRoot(), text, com.google.android.material.snackbar.Snackbar.LENGTH_LONG).show();
    }

    private void snackWithAction(String text, String action, Runnable callback) {
        if (binding == null) {
            return;
        }
        com.google.android.material.snackbar.Snackbar bar =
                com.google.android.material.snackbar.Snackbar.make(
                        binding.getRoot(), text,
                        com.google.android.material.snackbar.Snackbar.LENGTH_LONG);
        bar.setAction(action, view -> callback.run());
        bar.show();
    }

    private int getColorCompat(int res) {
        return ContextCompat.getColor(requireContext(), res);
    }

    private void hideKeyboard() {
        InputMethodManager manager = (InputMethodManager)
                requireContext().getSystemService(Context.INPUT_METHOD_SERVICE);
        if (manager != null && binding != null) {
            manager.hideSoftInputFromWindow(binding.getRoot().getWindowToken(), 0);
        }
    }

    @Override
    public void onResume() {
        super.onResume();
        if (!isHidden()) {
            startTickers();
        }
        refreshLocal();
        refreshFromServer();
    }

    @Override
    public void onHiddenChanged(boolean hidden) {
        super.onHiddenChanged(hidden);
        if (hidden) {
            stopTickers();
            stopPlayer();
        } else {
            startTickers();
            refreshLocal();
            refreshCapacity();
        }
    }

    @Override
    public void onPause() {
        stopTickers();
        stopPlayer();
        super.onPause();
    }

    private void startTickers() {
        handler.removeCallbacks(uiTicker);
        handler.removeCallbacks(refreshTicker);
        handler.post(uiTicker);
        handler.post(refreshTicker);
    }

    private void stopTickers() {
        handler.removeCallbacks(uiTicker);
        handler.removeCallbacks(refreshTicker);
    }

    @Override
    public void onDestroyView() {
        stopTickers();
        stopPlayer();
        handler.removeCallbacksAndMessages(null);
        binding = null;
        super.onDestroyView();
    }

    @Override
    public void onDestroy() {
        if (executor != null) {
            executor.shutdownNow();
        }
        super.onDestroy();
    }
}
