package com.zjh.meetingmemory.ui;

import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.inputmethod.InputMethodManager;

import androidx.activity.OnBackPressedCallback;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.fragment.app.Fragment;
import androidx.fragment.app.FragmentTransaction;

import com.google.android.material.badge.BadgeDrawable;
import com.zjh.meetingmemory.R;
import com.zjh.meetingmemory.core.AppPrefs;
import com.zjh.meetingmemory.data.LocalStore;
import com.zjh.meetingmemory.databinding.ActivityMainBinding;
import com.zjh.meetingmemory.recording.RecordingState;

public class MainActivity extends AppCompatActivity {

    private static final String TAG_RECORD = "record";
    private static final String TAG_MEETINGS = "meetings";
    private static final String TAG_WEB = "web";
    private static final String TAG_SETTINGS = "settings";

    private ActivityMainBinding binding;
    private AppPrefs prefs;
    private String currentTag = "";
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable badgeTicker = new Runnable() {
        @Override
        public void run() {
            updateBadge();
            handler.postDelayed(this, 5000);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = new AppPrefs(this);
        if (!prefs.isConfigured()) {
            startActivity(new Intent(this, LoginActivity.class));
            finish();
            return;
        }
        binding = ActivityMainBinding.inflate(getLayoutInflater());
        setContentView(binding.getRoot());

        binding.bottomNav.setOnItemSelectedListener(item -> {
            int id = item.getItemId();
            if (id == R.id.nav_record) {
                showTab(TAG_RECORD);
            } else if (id == R.id.nav_meetings) {
                showTab(TAG_MEETINGS);
            } else if (id == R.id.nav_web) {
                showTab(TAG_WEB);
            } else if (id == R.id.nav_settings) {
                showTab(TAG_SETTINGS);
            }
            return true;
        });

        String initial = TAG_RECORD;
        if (savedInstanceState != null) {
            initial = savedInstanceState.getString("current_tab", TAG_RECORD);
        }
        String requested = getIntent().getStringExtra("tab");
        if ("meetings".equals(requested)) {
            initial = TAG_MEETINGS;
        } else if ("web".equals(requested)) {
            initial = TAG_WEB;
        } else if ("settings".equals(requested)) {
            initial = TAG_SETTINGS;
        }
        showTab(initial);
        if (TAG_MEETINGS.equals(initial)) {
            binding.bottomNav.setSelectedItemId(R.id.nav_meetings);
        } else if (TAG_WEB.equals(initial)) {
            binding.bottomNav.setSelectedItemId(R.id.nav_web);
        } else if (TAG_SETTINGS.equals(initial)) {
            binding.bottomNav.setSelectedItemId(R.id.nav_settings);
        } else {
            binding.bottomNav.setSelectedItemId(R.id.nav_record);
        }

        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                Fragment fragment = getSupportFragmentManager().findFragmentByTag(TAG_WEB);
                if (TAG_WEB.equals(currentTag) && fragment instanceof WebFragment
                        && ((WebFragment) fragment).canGoBack()) {
                    ((WebFragment) fragment).goBack();
                    return;
                }
                if (!TAG_RECORD.equals(currentTag)) {
                    showTab(TAG_RECORD);
                    binding.bottomNav.setSelectedItemId(R.id.nav_record);
                    return;
                }
                setEnabled(false);
                getOnBackPressedDispatcher().onBackPressed();
                setEnabled(true);
            }
        });

        UpdatePrompt.check(this, false);
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (!prefs.isConfigured()) {
            startActivity(new Intent(this, LoginActivity.class));
            finish();
            return;
        }
        handler.removeCallbacks(badgeTicker);
        handler.post(badgeTicker);
    }

    @Override
    protected void onPause() {
        handler.removeCallbacks(badgeTicker);
        super.onPause();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        String requested = intent.getStringExtra("tab");
        if ("meetings".equals(requested)) {
            showTab(TAG_MEETINGS);
            binding.bottomNav.setSelectedItemId(R.id.nav_meetings);
        } else if ("record".equals(requested)) {
            showTab(TAG_RECORD);
            binding.bottomNav.setSelectedItemId(R.id.nav_record);
        }
    }

    @Override
    protected void onSaveInstanceState(@NonNull android.os.Bundle outState) {
        super.onSaveInstanceState(outState);
        if (currentTag != null && !currentTag.isEmpty()) {
            outState.putString("current_tab", currentTag);
        }
    }

    private void showTab(String tag) {
        if (tag.equals(currentTag)) {
            return;
        }
        FragmentTransaction transaction = getSupportFragmentManager().beginTransaction();
        if (!currentTag.isEmpty()) {
            Fragment current = getSupportFragmentManager().findFragmentByTag(currentTag);
            if (current != null) {
                transaction.hide(current);
            }
        } else {
            for (Fragment fragment : getSupportFragmentManager().getFragments()) {
                if (fragment.getTag() != null && !tag.equals(fragment.getTag())) {
                    transaction.hide(fragment);
                }
            }
        }
        Fragment target = getSupportFragmentManager().findFragmentByTag(tag);
        if (target == null) {
            if (TAG_RECORD.equals(tag)) {
                target = new RecordFragment();
            } else if (TAG_MEETINGS.equals(tag)) {
                target = new MeetingsFragment();
            } else if (TAG_WEB.equals(tag)) {
                target = new WebFragment();
            } else {
                target = new SettingsFragment();
            }
            transaction.add(R.id.content_container, target, tag);
        } else {
            transaction.show(target);
        }
        transaction.commitNowAllowingStateLoss();
        currentTag = tag;
        InputMethodManager manager =
                (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        if (manager != null) {
            manager.hideSoftInputFromWindow(binding.getRoot().getWindowToken(), 0);
        }
    }

    private void updateBadge() {
        if (binding == null) {
            return;
        }
        try {
            int pending = LocalStore.get(this).countPending();
            BadgeDrawable badge = binding.bottomNav.getOrCreateBadge(R.id.nav_record);
            if (RecordingState.active) {
                badge.setVisible(true);
                badge.clearNumber();
                badge.setBackgroundColor(getColor(R.color.red));
            } else if (pending > 0) {
                badge.setVisible(true);
                badge.setNumber(pending);
                badge.setBackgroundColor(getColor(R.color.orange));
                badge.setBadgeTextColor(getColor(R.color.white));
            } else {
                badge.setVisible(false);
            }
        } catch (Exception ignored) {
        }
    }
}
