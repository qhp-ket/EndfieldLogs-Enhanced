using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

public sealed partial class TraceBridge
{
    private void WriteSquad(long ts, IEnumerable<(string Template, EvidenceValue Id)> members, EvidenceObject origin)
    {
        var rows = members.ToArray();
        if (eventOutput is not null)
            EmitStructured(ts, "squad", new(new Dictionary<string, EvidenceValue> { ["members"] = new EvidenceArray(rows.Select(row =>
                (EvidenceValue)new EvidenceObject(new Dictionary<string, EvidenceValue> { ["template"] = new EvidenceText(row.Template), ["entity_id"] = row.Id })).ToArray()) }), origin);
        else Line(ts, $"SQUAD size={rows.Length} members=[{string.Join(' ', rows.Select(row => row.Template + "_" + S(row.Id)))}]");
    }
    private void WriteActorMapping(long ts, BigInteger id, string template, string source, string? skill, EvidenceObject origin)
    {
        if (eventOutput is not null)
            EmitStructured(ts, "actor_mapping", Make(("entity_id", id), ("template", template), ("mapping_source", source), ("skill", skill)), origin);
        else Line(ts, $"ACTOR_MAP id={id} template={template} source={source} skill={skill ?? "None"}");
    }
    private void Scene(EvidenceObject e, long ts)
    {
        List<(string Template, EvidenceValue Id)> members = [];
        foreach (var row in Rows(e.Get("char_list")))
        {
            var battle = Id(row.Get("battle_inst_id")); var obj = Id(row.Get("id")); var template = Text(row.Get("templateid"));
            if (battle is { } bid && template.Length > 0) { names[bid] = template; aliases[bid] = template; }
            if (obj is { } oid && template.Length > 0) { names[oid] = template; aliases[oid] = template; members.Add((template, battle is { } value ? new EvidenceInteger(value) : EvidenceNull.Value)); }
            if (battle is not null && template.Length > 0) WriteStats(row, ts, battle.Value, template, "character", e);
        }
        if (members.Count > 0) { hasSceneSquad = true; WriteSquad(ts, members, e); }
    }
    private static bool HasAttributes(EvidenceValue value) => Rows(value).Any(row => Int(row.Get("attr_type")) is not null);
    private void WriteStats(EvidenceObject row, long ts, BigInteger id, string template, string kind, EvidenceObject origin)
    {
        if (!HasAttributes(row.Get("attrs")) && row.Get("level") is EvidenceNull && row.Get("hp") is EvidenceNull) return;
        if (eventOutput is not null)
        {
            Dictionary<string, EvidenceValue> data = new() { ["entity_id"] = new EvidenceInteger(id), ["template"] = new EvidenceText(template), ["kind"] = new EvidenceText(kind) };
            foreach (var (input, output) in new[] { ("attrs", "attributes"), ("level", "level"), ("hp", "hp") })
                if (row.Fields.TryGetValue(input, out var value)) data[output] = value;
            EmitStructured(ts, "entity_stats", new(data), origin); return;
        }
        var attrs = EntityLegacyExporter.AttributeTokens(row.Get("attrs"));
        Line(ts, $"ENTITY_STATS id={id} template={template} kind={kind} level={Present(row.Get("level"))} hp={Present(row.Get("hp"))} attrs=[{attrs}]");
    }
    private void Objects(EvidenceObject e, long ts)
    {
        foreach (var row in Rows(e.Get("objects")))
        {
            var battle = Id(row.Get("battle_inst_id")); var obj = Id(row.Get("obj_id")); var template = Text(row.Get("templateid"));
            if (battle is { } bid && template.Length > 0) names[bid] = template;
            if (obj is { } oid && template.Length > 0) names[oid] = template;
            if (battle is not null && template.Length > 0) WriteStats(row, ts, battle.Value, template, Text(row.Get("kind"), "object"), e);
        }
    }
    private void Attributes(EvidenceObject e, long ts)
    {
        var battle = Id(e.Get("battle_inst_id")); var obj = Int(e.Get("obj_id")); var id = battle ?? Id(e.Get("obj_id"));
        if (id is null) return;
        var template = Text(e.Get("templateid"), names.GetValueOrDefault(id.Value) ?? (obj is null ? null : names.GetValueOrDefault(obj.Value)) ?? "unknown");
        if (template != "unknown")
        {
            if (battle is { } bid) { names[bid] = template; aliases[bid] = template; }
            if (obj is { IsZero: false } oid) names[oid] = template;
        }
        if (!HasAttributes(e.Get("attrs"))) return;
        if (eventOutput is not null)
        {
            EmitStructured(ts, "entity_attributes", new(new Dictionary<string, EvidenceValue> {
                ["entity_id"] = new EvidenceInteger(id.Value), ["object_id"] = obj is { } value ? new EvidenceInteger(value) : EvidenceNull.Value,
                ["template"] = new EvidenceText(template), ["attributes"] = e.Get("attrs") }), e);
            return;
        }
        var attrs = EntityLegacyExporter.AttributeTokens(e.Get("attrs"));
        Line(ts, $"ENTITY_ATTR_UPDATE id={id} obj={I(obj)} template={template} attrs=[{attrs}]");
    }
    private void SceneSkills(EvidenceObject e, long ts)
    {
        List<string> tokens = [];
        List<EvidenceValue> levels = [];
        foreach (var row in Rows(e.Get("skills")))
        {
            if (Id(row.Get("skill_inst_id")) is not { } id) continue;
            var resolved = skills.GetValueOrDefault(id) ?? ResolveSkill(row.Get("template_str_id"), row.Get("template_int_id"));
            if (resolved is not null) skills[id] = resolved;
            var source = Text(row.Get("skill_source"));
            if (source.Length > 0 && !skillSources.ContainsKey(id)) skillSources[id] = source;
            if (row.Get("level") is EvidenceNull) continue;
            var token = resolved ?? (row.Get("template_int_id") is EvidenceNull ? "" : S(row.Get("template_int_id")));
            if (token.Length > 0)
            {
                tokens.Add(token + ":" + S(row.Get("level")));
                levels.Add(Make(("skill", token), ("level", row.Get("level"))));
            }
        }
        var owner = Text(e.Get("owner_templateid"));
        var signature = Json(Make(("owner", owner), ("skills", tokens)));
        if (owner.Length > 0 && tokens.Count > 0 && emittedSkills.Add(signature))
        {
            if (eventOutput is not null)
                EmitStructured(ts, "character_skills", Make(("template", owner), ("entity_id", Id(e.Get("owner_inst_id"))), ("skills", new EvidenceArray(levels))), e);
            else
            Line(ts, $"CHAR_SKILLS owner={owner} ownerId={I(Id(e.Get("owner_inst_id")))} count={tokens.Count} skills=[{string.Join(' ', tokens)}]");
        }
    }
    private void Loadout(EvidenceObject e, long ts)
    {
        if (e.Get("rows") is not EvidenceArray { Items.Count: > 0 } input) return;
        var rows = input.Items.OfType<EvidenceObject>().ToArray();
        var members = rows.Where(row => Truth(row.Get("char")) && Truth(row.Get("char_inst_id"))).Select(row => (S(row.Get("char")), row.Get("char_inst_id"))).ToArray();
        if (members.Length > 0 && !hasSceneSquad) WriteSquad(ts, members, e);
        var roster = rows.Where(row => Truth(row.Get("char_inst_id"))).Select(row => S(row.Get("char_inst_id")));
        if (eventOutput is not null)
            EmitStructured(ts, "loadout_group", Make(("reason", Text(e.Get("reason"), "packet")), ("slot_count", input.Items.Count), ("member_count", input.Items.Count),
                ("roster", new EvidenceArray(rows.Where(row => Truth(row.Get("char_inst_id"))).Select(row => (EvidenceValue)Make(("entity_id", row.Get("char_inst_id")))).ToArray()))), e);
        else Line(ts, $"LOADOUT reason={Text(e.Get("reason"), "packet")} slotCount={input.Items.Count} memberCount={input.Items.Count} roster=[{string.Join(' ', roster)}]");
        foreach (var row in rows)
        {
            string T(string key, string fallback = "") => Text(row.Get(key), fallback);
            string N(string key) => I(Int(row.Get(key)) ?? 0);
            var charId = Id(row.Get("char_inst_id")); var character = T("char");
            if (charId is { } id && character.Length > 0) { names.TryAdd(id, character); aliases[id] = character; }
            if (eventOutput is not null)
            {
                EmitStructured(ts, "loadout_slot", LoadoutWire.Data(row), e);
                EmitStructured(ts, "loadout_stats", LoadoutWire.Data(row, stats: true), e);
                continue;
            }
            var complete = row.Get("equipment_snapshot_complete") is EvidenceBoolean flag ? "equipsComplete=" + (flag.Value ? 1 : 0) + " " : "";
            var unplaced = row.Get("unresolved_equip_inst_ids") is EvidenceArray array ? "unplacedEquipInstIds=[" + string.Join(',', array.Items.Select(S)) + "] " : "";
            Line(ts, $"LOADOUT slot={N("slot")} char={character} slotCharInstId={N("char_inst_id")} resolvedCharInstId={N("char_inst_id")} character=packet charInfo.instId={N("char_inst_id")} template={character} charLv={N("char_level")} potential={N("potential")} weaponInstId={N("weapon_inst_id")} weaponTemplate={T("weapon_template", "unknown_weapon")} weaponLv={N("weapon_lv")} refine={I(Int(row.Get("refine")))} break={N("breakthrough")} attachedGem={N("attached_gem")} equipInsts={T("equip_inst_ids", "{}")} equips={T("equips", "{}")} {complete}{unplaced}equipSuit={T("equip_suit", "{}")} skillIntIds=[{T("skill_int_ids")}]");
            Line(ts, $"LOADOUT_STATS slot={N("slot")} char={character} weaponInstId={N("weapon_inst_id")} weaponTemplate={T("weapon_template", "unknown_weapon")} weaponSync={T("weapon_sync_source", "missing")} weaponBaseAtk={Present(row.Get("weapon_base_atk"))} weaponBaseAtkLv1={Present(row.Get("weapon_base_atk_lv1"))} weaponBaseAtkMax={Present(row.Get("weapon_base_atk_max"))} weaponRefineStatsSource={T("weapon_refine_stats_source", "unknown")} weaponRefineStats={{{T("weapon_refine_stats")}}} weaponSourceSkills={{{T("weapon_source_skills")}}} gemInstId={N("attached_gem")} gemWeaponId={N("gem_weapon_id")} gemTemplate={N("gem_template")} gemTerms={{{T("gem_terms")}}}");
        }
    }
    private void Attach(EvidenceObject e, long ts)
    {
        var id = Id(e.Get("skill_inst_id")); var src = Id(e.Get("src_inst_id"));
        var source = src is null ? null : names.GetValueOrDefault(src.Value);
        var skill = ResolveSkill(e.Get("template_str_id"), e.Get("template_int_id"));
        var character = Character(skill);
        if (character is null && src is not null)
        {
            character = Character(source);
            if (character is not null && skill?.StartsWith("skill_", StringComparison.Ordinal) == true) skill = character + "_" + skill;
        }
        if (id is not null && !string.IsNullOrEmpty(skill)) skills[id.Value] = skill;
        if (id is not null && Truth(e.Get("skill_source"))) skillSources[id.Value] = Text(e.Get("skill_source"));
        if (src is not null && character is not null && names.TryAdd(src.Value, character))
            WriteActorMapping(ts, src.Value, character, "skill_attach", skill, e);
    }
    private void Cast(EvidenceObject e, long ts, bool start)
    {
        if (Id(e.Get("skill_inst_id")) is not { } id) return;
        var ownerId = Int(e.Get("owner_id")); var owner = Name(ownerId);
        var skill = skills.GetValueOrDefault(id) ?? ResolveSkill(EvidenceNull.Value, new EvidenceInteger(id));
        if (start && Id(e.Get("owner_id")) is { } oid && (Character(skill) ?? Character(owner)) is { } character && names.TryAdd(oid, character)) owner = character;
        if (eventOutput is not null)
        {
            var fields = SkillWire.Data("skill_cast", e).Fields.ToDictionary(); fields["phase"] = new EvidenceText(start ? "start" : "end");
            fields["owner"] = Value(owner == "?" ? null : owner); fields["skill"] = Value(skill); fields["skill_source"] = Value(skillSources.GetValueOrDefault(id));
            EmitStructured(ts, "skill_cast", new(fields), e); return;
        }
        var label = start ? "START" : "END"; var timing = start ? "startMs" : "endMs";
        Line(ts, $"SKILL_CAST_{label} seq={I(Int(e.Get("seq_id")) ?? 0)} {timing}={I(Int(e.Get("client_tick_tms")) ?? 0)} inst={id} owner={owner} ownerId={(start ? I(ownerId) : Present(e.Get("owner_id")))} skill={skill ?? "unknown_skill"} skillSource={skillSources.GetValueOrDefault(id) ?? "unknown"}" + (start ? $" captureMs={ts}" : ""));
    }
}
