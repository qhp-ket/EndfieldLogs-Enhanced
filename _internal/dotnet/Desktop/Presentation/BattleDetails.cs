using System.Globalization;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;

namespace EndfieldLogs.Desktop.Presentation;

internal static class BattleDetails
{
    internal static string Time(double stamp, bool frames, bool suffix = true) => (frames ? stamp / 1000 * 30 : stamp / 1000).ToString(frames ? "F1" : "F3", CultureInfo.CurrentCulture) + (suffix ? frames ? "F" : "s" : "");
    internal static string Number(double? value) => value is { } number ? number.ToString("N2", CultureInfo.CurrentCulture) : "未知";
    internal static string Description(TimelineMark mark, bool frames, bool compact = false)
    {
        var first = mark.Evidence[0]; var summary = BattleEvidence.Summary(mark.Evidence);
        List<string> lines = [mark.Name, $"{Time(mark.Start, frames)}–{Time(mark.End, frames)}" + (frames ? "（30F/s）" : ""), "来源：" + (mark.Buff is not null ? BuffDisplay.Source(first)
            : TimelineSkills.CharacterName(EvidenceView.Text(first.Get("source_character_key"), mark.Owner), EvidenceView.Text(first.Get("source_character_name"))))];
        var targets = mark.Evidence.Select(row => EvidenceView.Text(row.Get("target_character_name"), EvidenceView.Text(row.Get("target_character_key")))).Where(name => name.Length > 0).Distinct().Order(PythonDisplay.CodePointComparer).ToArray();
        if (targets.Length > 0) lines.Add("目标：" + string.Join("、", targets));
        if (mark.Skill is { } skill)
        {
            if (!compact) lines.Add(skill.Cast is { } cast ? BattleEvidence.Number(cast.Get("end_ms_from_start")) is not null ? "时间依据：SKILL_CAST_START → SKILL_CAST_END（协议施放生命周期）" : "时间依据：仅有 SKILL_CAST_START；结束未知，显示起点标记"
                : mark.Evidence.Any(row => row.Get("actual_start_ms_from_start") is not EvidenceNull) ? "时间依据：核心匹配的施放起止" : "时间依据：首末命中分组");
            if (summary.Hits == 0) lines.Add("施放记录（无伤害补录）");
            if (!compact && mark.FrameReference is { } rule)
            {
                lines.Add($"AKEData 配置：{PythonDisplay.String(rule.Get("duration_frames"))}F 总时长；exclusiveFrame={PythonDisplay.String(rule.Get("exclusive_frames"))}F（配置参考）");
                lines.Add(BattleEvidence.Number(rule.Get("anchor_ms")) is { } anchor ? "固定显示区间：" + Time(anchor, frames) + " 起，首个实际命中点 + 配置时长；保留日志原区间" : "没有实际命中点，保留日志施放区间或起点");
                foreach (var window in EvidenceView.Rows(rule.Get("damage_windows")))
                    lines.Add($"相对配置伤害窗口：{PythonDisplay.String(window.Get("start_frame"))}–{PythonDisplay.String(window.Get("end_frame"))}F · {(window.Get("conditional") is EvidenceBoolean { Value: true } ? "条件分支" : "直接动作")} · {EvidenceView.Text(window.Get("action"))}（未对齐实战时间）");
                if (rule.Get("unplaced_damage_actions") is EvidenceArray { Items.Count: > 0 }) lines.Add("另有回调／异步伤害动作，没有直接可放置的相对帧");
                if (!EvidenceView.Rows(rule.Get("damage_windows")).Any()) lines.Add("该技能没有可直接放置的 Hp 伤害窗口");
            }
        }
        if (summary.Hits > 0)
        {
            lines.Add($"伤害：{summary.Damage:N2}（{summary.Hits} 次命中）");
            if (!compact) lines.Add($"rD 基数：{Number(summary.Basis)}；已分配：{summary.Allocated:N2}；有分配证据 {summary.Covered}/{summary.Hits} 击");
            lines.Add("rDMG 分配：" + string.Join("；", summary.Contributions.Select(share => $"{share.Name} {share.Value:N2}")));
        }
        if (mark.Buff is { } buff)
        {
            lines.Add(BuffDisplay.StateText(buff.States)); lines.Add($"{buff.Evidence.Count} 次状态观测");
            foreach (var state in buff.States) lines.Add($"{Time(state.Start, frames)}–{Time(state.End, frames)}：" + BuffDisplay.StateText([state], state.Start));
            if (BattleEvidence.Number(first.Get("actual_duration_ms")) is { } duration) lines.Add($"实际持续时间：{Time(duration, frames)}（图中显示战斗内区间）");
            if (first.Get("effects") is EvidenceArray { Items.Count: > 0 } effects) lines.Add("效果：" + PythonSortedJson.Serialize(effects));
        }
        lines.Add("代码：" + EvidenceView.Text(first.Get("event_key"), mark.Skill?.RawSkill ?? ""));
        return string.Join("\n", lines);
    }
}
