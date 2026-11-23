package com.zjh.meetingmemory.core;

import java.util.ArrayList;
import java.util.List;

/** 服务器不可达时也能开始录音的内置模板兜底。 */
public final class Defaults {

    private Defaults() {
    }

    public static List<Models.Template> templates() {
        List<Models.Template> items = new ArrayList<>();
        items.add(template("standard", "常规会议", "通用会议纪要，覆盖结论、待办与风险。"));
        items.add(template("discussion", "座谈交流", "适合座谈、研讨，保留观点与分歧。"));
        items.add(template("report", "工作汇报", "突出进展、数据与下一步安排。"));
        items.add(template("weekly", "周会", "突出本周进展、下周计划与阻塞。"));
        items.add(template("project_review", "项目复盘", "对照目标、结果、偏差与经验教训。"));
        items.add(template("decision_review", "决策评审", "还原方案对比、结论与保留意见。"));
        items.add(template("interview", "客户访谈", "保留客户原话、诉求与机会风险。"));
        items.add(template("training", "培训分享", "提炼知识点、问答与练习建议。"));
        return items;
    }

    private static Models.Template template(String key, String name, String description) {
        Models.Template item = new Models.Template();
        item.key = key;
        item.name = name;
        item.description = description;
        item.scene = name;
        return item;
    }
}
