using System.Globalization;
using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Timing;

namespace EndfieldLogs.Core.Reporting;

/// <summary>Complete existing report contract for Runtime, history, analysis and uploader compatibility.</summary>
public sealed class ReportExport(BattleLoadoutResolver loadouts, Func<string, string?> enemyName,
    Func<BigInteger, EvidenceObject> contractTag, TimeZoneInfo? timeZone = null)
{
    public const string ParserVersion = "raw-log-parser-v60";
    public const string RulesVersion = "raw-log-parser-v45";
    private static EvidenceText Text(string value) => new(value);
    private static EvidenceValue Optional(string? value) => value is null ? EvidenceNull.Value : Text(value);
    private static EvidenceValue Optional(BigInteger? value) => value is { } number ? new EvidenceInteger(number) : EvidenceNull.Value;
    private static BigInteger Int(EvidenceValue value) => EffectIdentity.Integer(CatalogValues.Or(value, new EvidenceInteger(0)));
    private static string String(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, Text("")));
    private static EvidenceArray Array(IEnumerable<EvidenceValue> values) => new(values.ToArray());
    private static IReadOnlyList<EvidenceObject> SortedLoadout(IReadOnlyDictionary<string, EvidenceObject> rows) => rows.Values
        .OrderBy(row => Int(row.Get("slot"))).ThenBy(row => String(row.Get("character_key")), PythonDisplay.CodePointComparer).ToArray();

    public static string LocalIso(DateOnly referenceDate, BigInteger timestampMs, TimeZoneInfo? timeZone = null)
    {
        var date = referenceDate.ToDateTime(TimeOnly.MinValue).AddTicks(checked((long)timestampMs * TimeSpan.TicksPerMillisecond));
        return new DateTimeOffset(date, (timeZone ?? TimeZoneInfo.Local).GetUtcOffset(date)).ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz", CultureInfo.InvariantCulture);
    }

    public EvidenceObject? Build(BattleReportAnalysisResult analysis, string traceText, string? fileName = null,
        bool includeDebug = false, bool allowEmpty = false)
        => BuildCore(analysis, traceText, fileName, includeDebug, allowEmpty, ownsInput: false);

    internal EvidenceObject? BuildOwned(BattleReportAnalysisResult analysis, string traceText, string? fileName = null)
        => BuildCore(analysis, traceText, fileName, includeDebug: false, allowEmpty: false, ownsInput: true);

    private EvidenceObject? BuildCore(BattleReportAnalysisResult analysis, string traceText, string? fileName,
        bool includeDebug, bool allowEmpty, bool ownsInput)
    {
        var lifecycle = analysis.Lifecycle;
        if (analysis.Calculation is null)
        {
            var input = lifecycle.Input;
            if (input.Baseline.Loadouts.Fallback.Count > 0 || !string.IsNullOrEmpty(lifecycle.Timing.DungeonId)
                || input.UnresolvedHits.Count > 0 || input.UnresolvedBuffActions.Count > 0)
                return Empty(analysis, fileName);
            if (allowEmpty) return null;
            throw new InvalidOperationException("未在日志中解析到任何 HP_V2 伤害事件。");
        }
        var metadata = analysis.Metadata ?? throw new InvalidOperationException("A reference date is required for report export");
        var calculated = analysis.Calculation;
        var window = lifecycle.Window ?? throw new InvalidOperationException("A damage report requires its selected window");
        var timeline = analysis.Timeline ?? throw new InvalidOperationException("A complete report requires timeline projection");
        var timer = lifecycle.Timing;
        var hits = calculated.Hits;
        var enemies = lifecycle.RebuildTotals ? CountEnemies(hits) : timer.EnemyCounts;
        var boss = enemies.OrderByDescending(pair => pair.Value).FirstOrDefault().Key ?? "unknown_boss";
        var total = PythonNumericSum.Sum(hits.Select(hit => hit.Evidence.Get("hit_value")));
        var fingerprint = BuffEvidence.Object(("rules_version", Text(RulesVersion)), ("boss_key", Text(boss)),
            ("first_hit_ms", new EvidenceInteger(window.StartMs)), ("last_hit_ms", new EvidenceInteger(window.EndMs)),
            ("hits", Array(hits.Select(hit => (EvidenceValue)new EvidenceObject(new[] { "ts_ms", "character_key", "skill_key", "hit_value", "crit_flag", "target_enemy_key" }
                .ToDictionary(key => key, hit.Evidence.Get, StringComparer.Ordinal))))));
        var tags = metadata.ContractTagIds.Select(contractTag).ToArray();
        var score = metadata.ContractTagScore;
        if (tags.Length > 0)
        {
            var computed = tags.Aggregate(BigInteger.Zero, (sum, tag) => sum + (TraceFields.OptionalInteger(String(tag.Get("score"))) ?? 0));
            if (computed > 0 || score is null) score = computed;
        }
        var battle = CalculatedBattle(analysis, boss, total, fileName);
        battle["boss_identity_source"] = Text((metadata.HasIdentityInference ?? traceText.Contains(" IDENTITY_INFERENCE ", StringComparison.Ordinal))
            ? "trace_inference" : "damage_target");
        battle["battle_fingerprint"] = Text(ReportIntegrity.Sha256(fingerprint));
        battle["loadout_stale"] = new EvidenceBoolean(calculated.Baseline.LoadoutStale);
        battle["rdps_damage_basis"] = calculated.DamageBasis;
        battle["contract_tag_score"] = Optional(score);
        battle["contract_tags"] = Array(tags);
        Dictionary<string, EvidenceValue> report = new(StringComparer.Ordinal)
        {
            ["battle"] = new EvidenceObject(battle), ["participants"] = Array(analysis.Participants.Participants),
            ["loadout"] = Array(SortedLoadout(calculated.Baseline.Loadouts)), ["buff_events"] = Array(calculated.BuffEvents ?? []),
            ["timeline_events"] = Array(timeline.Events), ["dynamic_bb_events"] = Array(analysis.Sources.DynamicEvents),
            ["buff_attribute_refresh_events"] = Array(analysis.Sources.RefreshEvents), ["role_skill_stats"] = Array(timeline.RoleSkillStats),
            ["debug_hits"] = Array(calculated.DebugHits), ["rdps_damage_basis"] = calculated.DamageBasis, ["rdps_preflight"] = calculated.Preflight,
            ["unresolved_hits"] = Array(lifecycle.Input.UnresolvedHits), ["unresolved_buff_actions"] = Array(lifecycle.Input.UnresolvedBuffActions),
            ["casts"] = Array(timeline.Casts), ["atb_events"] = Array(timeline.AtbEvents),
            ["char_skills"] = new EvidenceObject(metadata.CharacterSkills.ToDictionary(pair => pair.Key, pair => (EvidenceValue)Array(pair.Value
                .OrderBy(skill => skill.Key, PythonDisplay.CodePointComparer).Select(skill => (EvidenceValue)BuffEvidence.Object(
                    ("skill_key", Text(skill.Key)), ("level", new EvidenceInteger(skill.Value))))), StringComparer.Ordinal)),
        };
        if (includeDebug) report["debug_context"] = BuffEvidence.Object(("start_ts_ms", new EvidenceInteger(window.StartMs)),
            ("end_ts_ms", new EvidenceInteger(window.EndMs)), ("buff_windows", Array(calculated.Windows)));
        var result = new EvidenceObject(report);
        return SnapshotQuality.Attach(ownsInput ? result : (EvidenceObject)BuffEvidence.Clone(result));
    }

    public EvidenceObject? BuildSummary(BattleReportAnalysisResult analysis, IReadOnlyDictionary<string, double> maxima)
    {
        if (analysis.Calculation is not { } calculated)
        {
            var empty = Build(analysis, "", "live-overlay.log", allowEmpty: true);
            return empty is null ? null : Realtime.LiveReportProjection.Summary(empty, maxima);
        }
        var enemies = analysis.Lifecycle.RebuildTotals ? CountEnemies(calculated.Hits) : analysis.Lifecycle.Timing.EnemyCounts;
        var boss = enemies.OrderByDescending(pair => pair.Value).FirstOrDefault().Key ?? "unknown_boss";
        var total = PythonNumericSum.Sum(calculated.Hits.Select(hit => hit.Evidence.Get("hit_value")));
        var report = BuffEvidence.Object(("battle", new EvidenceObject(CalculatedBattle(analysis, boss, total, "live-overlay.log"))),
            ("participants", Array(analysis.Participants.Participants)), ("loadout", Array(SortedLoadout(calculated.Baseline.Loadouts))),
            ("rdps_preflight", calculated.Preflight), ("rdps_damage_basis", calculated.DamageBasis));
        return Realtime.LiveReportProjection.Summary(report, maxima);
    }

    private Dictionary<string, EvidenceValue> CalculatedBattle(BattleReportAnalysisResult analysis, string boss, EvidenceValue total, string? fileName)
    {
        var lifecycle = analysis.Lifecycle;
        var timer = lifecycle.Timing;
        var metadata = analysis.Metadata ?? throw new InvalidOperationException("A reference date is required for report export");
        var window = lifecycle.Window ?? throw new InvalidOperationException("A damage report requires its selected window");
        var hits = analysis.Calculation!.Hits;
        var official = lifecycle.OfficialEvidence?.ToEvidence() ?? (EvidenceValue)EvidenceNull.Value;
        var reasons = timer.OfficialPassConfirmed ? TimerEvidenceValidator.Validate(official, new EvidenceInteger(lifecycle.DurationMs), timer.DungeonId) : [];
        var clear = lifecycle.OfficialEvidence is not null || timer.Dungeon?.Key.StartsWith("indie_battletower", StringComparison.Ordinal) == true
            ? timer.OfficialPassConfirmed : timer.ChallengePassConfirmed || hits.Any(hit => String(hit.Evidence.Get("target_enemy_key")) == boss
                && (hit.Evidence.Fields.TryGetValue("enemy_hp_after", out var hp) ? EffectIdentity.Float(hp) : 1) <= 0);
        if (!timer.WindowValid) clear = false;
        var battle = CommonBattle(metadata, timer, lifecycle.ObservedOfficialElapsedMs, window.StartMs, window.EndMs, fileName);
        battle["boss_key"] = Text(boss);
        battle["boss_name"] = Text(enemyName(boss) is { Length: > 0 } name ? name : boss);
        battle["duration_ms"] = new EvidenceInteger(lifecycle.DurationMs);
        battle["time_source"] = Text(window.HasGameTimer ? "game_timer" : window.TimeSource);
        battle["timeline_zero_source"] = Text(window.ZeroSource);
        battle["timer_integrity_ok"] = timer.OfficialPassConfirmed ? new EvidenceBoolean(reasons.Count == 0) : EvidenceNull.Value;
        battle["timer_integrity_reasons"] = Array(reasons.Select(Text));
        battle["timer_evidence"] = official;
        battle["timer_start_inferred"] = new EvidenceBoolean(window.ZeroSource is "timer_end_inferred" or "timer_elapsed_first_hit_inferred");
        battle["timer_window_valid"] = new EvidenceBoolean(timer.WindowValid);
        battle["clear_flag"] = new EvidenceBoolean(clear);
        battle["challenge_pass_confirmed"] = new EvidenceBoolean(timer.ChallengePassConfirmed);
        battle["official_pass_confirmed"] = new EvidenceBoolean(timer.OfficialPassConfirmed);
        battle["completion_source"] = Text(timer.CompletionSource);
        battle["total_damage"] = total;
        battle["total_dps"] = new EvidenceReal(PythonDecimalRounding.Round(EffectIdentity.Float(total) / PythonIntegerDivision.Divide(lifecycle.DurationMs, 1000), 2));
        battle["roster"] = Array(analysis.Participants.Roster);
        return battle;
    }

    private static IReadOnlyList<KeyValuePair<string, BigInteger>> CountEnemies(IReadOnlyList<ReportHitInput> hits)
    {
        Dictionary<string, BigInteger> counts = new(StringComparer.Ordinal);
        foreach (var hit in hits)
        {
            var key = String(hit.Evidence.Get("target_enemy_key"));
            if (key.Length > 0) counts[key] = counts.GetValueOrDefault(key) + 1;
        }
        return counts.ToArray();
    }

    private Dictionary<string, EvidenceValue> CommonBattle(ReportMetadataInput metadata, ReportTimingInput timer,
        BigInteger? observedElapsed, BigInteger start, BigInteger end, string? fileName) => new(StringComparer.Ordinal)
    {
        ["dungeon_key"] = Text(timer.Dungeon?.Key ?? "unknown_dungeon"), ["dungeon_name"] = Text(timer.Dungeon?.Name ?? DungeonCatalog.UnknownName),
        ["dungeon_context_id"] = Optional(timer.DungeonId),
        ["dungeon_identity_source"] = Text(timer.Dungeon is not null ? "dungeon_context" : !string.IsNullOrEmpty(timer.DungeonId) ? "unmapped_dungeon_context" : "missing_dungeon_context"),
        ["battle_start_at"] = Text(LocalIso(metadata.ReferenceDate, start, timeZone)), ["battle_end_at"] = Text(LocalIso(metadata.ReferenceDate, end, timeZone)),
        ["timer_start_seen"] = new EvidenceBoolean(timer.StartSeen), ["timer_end_seen"] = new EvidenceBoolean(timer.EndSeen),
        ["official_timer_start_seen"] = new EvidenceBoolean(timer.OfficialStartMs is not null), ["official_timer_end_seen"] = new EvidenceBoolean(timer.OfficialEndMs is not null),
        ["official_timer_observed_elapsed_ms"] = Optional(observedElapsed), ["packet_timer_elapsed_ms"] = Optional(timer.PacketElapsedMs),
        ["parser_version"] = Text(ParserVersion), ["rules_version"] = Text(RulesVersion), ["source_file_name"] = Optional(fileName),
    };

    private EvidenceObject Empty(BattleReportAnalysisResult analysis, string? fileName)
    {
        var lifecycle = analysis.Lifecycle;
        var timer = lifecycle.Timing;
        var metadata = analysis.Metadata ?? throw new InvalidOperationException("A reference date is required for report export");
        var anchor = timer.OfficialStartMs ?? timer.FirstPartyActionMs ?? timer.GameStartMs ?? metadata.FirstContextMs ?? 0;
        var input = lifecycle.Input;
        var selected = loadouts.Select(input.Baseline.Loadouts.Groups, input.Baseline.Loadouts.Fallback, anchor);
        var loadout = SortedLoadout(selected);
        var roster = loadout.Select((row, index) => (row, index)).Where(pair => CatalogValues.Truth(pair.row.Get("character_key")))
            .Select(pair => (EvidenceValue)BuffEvidence.Object(("slot", new EvidenceInteger(Int(CatalogValues.Or(pair.row.Get("slot"), new EvidenceInteger(pair.index + 1))))),
                ("character_key", Text(String(pair.row.Get("character_key")))),
                ("character_name", Text(String(CatalogValues.Or(pair.row.Get("character_name"), pair.row.Get("character_key"))))))).ToArray();
        var source = timer.FirstPartyActionMs is not null ? "party_action_window" : "battle_ready";
        var fingerprint = BuffEvidence.Object(("rules_version", Text(RulesVersion)), ("time_source", Text(source)),
            ("loadout", Array(roster.Cast<EvidenceObject>().Select(row => row.Get("character_key")))), ("anchor_ms", new EvidenceInteger(anchor)));
        var battle = CommonBattle(metadata, timer, lifecycle.ObservedOfficialElapsedMs, anchor, metadata.LastContextMs ?? anchor, fileName);
        battle["boss_key"] = Text("unknown_boss");
        battle["boss_name"] = Text("未知对象");
        battle["boss_identity_source"] = Text("missing_damage_target");
        battle["duration_ms"] = new EvidenceInteger(0);
        battle["time_source"] = Text(source);
        battle["timeline_zero_source"] = Text(source);
        battle["timer_integrity_ok"] = timer.OfficialPassConfirmed ? new EvidenceBoolean(false) : EvidenceNull.Value;
        battle["timer_integrity_reasons"] = Array(timer.OfficialPassConfirmed ? [Text("missing_damage_events")] : []);
        battle["timer_start_inferred"] = new EvidenceBoolean(false);
        battle["clear_flag"] = new EvidenceBoolean(false);
        battle["total_damage"] = new EvidenceInteger(0);
        battle["total_dps"] = new EvidenceReal(0);
        battle["roster"] = new EvidenceArray(roster);
        battle["battle_fingerprint"] = Text(ReportIntegrity.Sha256(fingerprint));
        var unresolved = input.UnresolvedHits.Concat(input.UnresolvedBuffActions).ToArray();
        var blockers = unresolved.Length > 0 ? unresolved.Take(100).ToArray() : [BuffEvidence.Object(("reason", Text("missing_damage_events")))];
        var counts = (unresolved.Length > 0 ? unresolved : blockers).GroupBy(row => String(row.Get("reason")))
            .ToDictionary(group => group.Key, group => (EvidenceValue)new EvidenceInteger(group.Count()), StringComparer.Ordinal);
        Dictionary<string, EvidenceValue> report = new(StringComparer.Ordinal)
        {
            ["battle"] = new EvidenceObject(battle), ["participants"] = new EvidenceArray([]), ["loadout"] = Array(loadout),
            ["buff_events"] = new EvidenceArray([]), ["timeline_events"] = new EvidenceArray([]), ["role_skill_stats"] = new EvidenceArray([]),
            ["debug_hits"] = new EvidenceArray([]), ["unresolved_hits"] = Array(input.UnresolvedHits), ["unresolved_buff_actions"] = Array(input.UnresolvedBuffActions),
            ["rdps_preflight"] = BuffEvidence.Object(("ok", new EvidenceBoolean(false)), ("blocker_count", new EvidenceInteger(Math.Max(1, unresolved.Length))),
                ("blocker_reason_counts", new EvidenceObject(counts)), ("blockers", Array(blockers))),
            ["rdps_damage_basis"] = BuffEvidence.Object(("rdps_preflight_ok", new EvidenceBoolean(false)), ("rdps_strict_ok", new EvidenceBoolean(false)),
                ("rdps_conservation_ok", new EvidenceBoolean(false)), ("hit_count", new EvidenceInteger(0)), ("unresolved_damage_actor_count", new EvidenceInteger(input.UnresolvedHits.Count))),
            ["casts"] = new EvidenceArray([]), ["atb_events"] = new EvidenceArray([]), ["char_skills"] = new EvidenceObject(new Dictionary<string, EvidenceValue>()),
        };
        return SnapshotQuality.Attach((EvidenceObject)BuffEvidence.Clone(new EvidenceObject(report)));
    }
}
