using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Catalog;

namespace EndfieldLogs.Core.Ingestion;

internal static class BuffCreationRuntimeProof
{
    internal static bool IsCorrosionPath(string template) => template is "buff_common_natural_natural_corrupt_do"
        or "buff_common_natural_cryst_triggered" or "buff_common_natural_fire_triggered";

    public static void Update(BuffInstanceState state, BoundDynamicIdentity bound, EvidenceObject root)
    {
        var record = bound.Record;
        state.MarkProjectionChanged(record);
        foreach (var anchor in record.CreationObservations)
        {
            anchor.Set("bb_observation_source", new EvidenceText("unverified_creation_bb"));
            if (!IsCorrosionPath(bound.Template) || root.Get("stackingSettings") is not EvidenceObject stacking
                || stacking.Get("stackingType") is not EvidenceText { Value: "Stack" }
                || anchor.Get("sourceEvent") is not EvidenceText { Value: "BattleOpTriggerAction" }
                || anchor.Get("creationActionType") is not EvidenceText { Value: "BattleActionCreateBuff" }
                || anchor.Get("creationActionRuntimeCase") is not EvidenceText { Value: "create_buff_action" }
                || anchor.Get("assignedItems") is not EvidenceArray) continue;
            var origins = (record.OriginObservations ?? []).Where(origin => origin.Get("_boundCreateRecord") is EvidenceBoolean { Value: true }
                && EvidenceJson.PythonEquals(origin.Get("operationSeq"), anchor.Get("operationSeq"))
                && BuffEvidence.String(origin.Get("buffUid")) == bound.Uid
                && EvidenceJson.PythonEquals(origin.Get("sourceActorId"), anchor.Get("sourceActorId"))
                && EvidenceJson.PythonEquals(origin.Get("targetActorId"), anchor.Get("targetActorId"))).ToArray();
            HashSet<string> signatures = new(StringComparer.Ordinal);
            var valid = origins.Length > 0;
            foreach (var origin in origins)
            {
                if (PacketBuffCatalog.Text(origin.Get("environmentType")).ToLowerInvariant() != "buff"
                    || PythonDisplay.String(origin.Get("ownerType")) != "1"
                    || origin.Get("environmentInstId") is EvidenceNull or EvidenceText { Value: "" or "0" or "4294967295" }) { valid = false; break; }
                string? parent;
                if (origin.Get("templateStrId") is EvidenceText { Value.Length: > 0 } text && origin.Get("templateIntId") is EvidenceNull) parent = text.Value;
                else if (origin.Get("templateStrId") is EvidenceNull or EvidenceText { Value: "" }
                    && origin.Get("templateIntId") is EvidenceInteger number && number.Value >= 0) parent = state.Numbers.GetValueOrDefault(PythonDisplay.String(number));
                else { valid = false; break; }
                var action = BuffEvidence.Integer(origin.Get("actionId"));
                var index = state.ActionIndices.For(parent is not null && state.Roots.TryGetValue(parent, out var creator) ? creator : EvidenceNull.Value);
                var rows = action is not null ? index.Actions.GetValueOrDefault(action.Value) : null;
                if (rows is not { Count: 1 } || !rows[0].Enabled || rows[0].Definition.Get("$type") is not EvidenceText { Value: "Beyond.Gameplay.Core.CreateBuffAction.Data" }) { valid = false; break; }
                signatures.Add(EvidenceJsonSignature.Sorted(new EvidenceArray([BuffEvidence.Text(parent), origin.Get("actionId"), origin.Get("environmentInstId")])));
            }
            if (!valid || signatures.Count != 1) continue;
            anchor.Set("bb_observation_source", new EvidenceText("typed_post_create_runtime_bb"));
            anchor.Set("bb_observation_scope", new EvidenceText("current_default_corrosion_stack_path"));
            var key = new BuffCreationKey(new(BuffEvidence.String(anchor.Get("sessionId"))!, BuffEvidence.String(anchor.Get("operationOwnerId"))!,
                anchor.Get("operationGeneration")), BuffEvidence.Integer(anchor.Get("operationSeq"))!.Value, bound.Uid);
            if (!state.CreationHistory.TryGetValue(key, out var history)) continue;
            state.MarkProjectionChanged(history.Record);
            history.Observation.Set("bb_observation_source", anchor.Get("bb_observation_source"));
            history.Observation.Set("bb_observation_scope", anchor.Get("bb_observation_scope"));
        }
    }
}
