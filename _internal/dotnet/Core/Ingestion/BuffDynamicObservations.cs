using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Post-assignment runtime values remain pending until an explicit attribute refresh.</summary>
public sealed class BuffDynamicObservations(BuffInstanceState state, Func<string, SkillItemMetadata> skillMetadata)
{
    private const string ModifyType = "Beyond.Gameplay.Core.ModifyDynamicBlackboard.Data";
    private const string RefreshType = "Beyond.Gameplay.Core.RefreshBuffAttrModifierValue.Data";

    public bool Observe(string line, int lineNumber, long timestampMs)
    {
        var refreshTag = line.Contains(" BUFF_ATTR_REFRESH_UNRESOLVED ", StringComparison.Ordinal) ? " BUFF_ATTR_REFRESH_UNRESOLVED " : " BUFF_ATTR_REFRESH ";
        var refresh = line.Contains(refreshTag, StringComparison.Ordinal);
        if (!refresh && !line.Contains(" BB_MODIFY_DYNAMIC ", StringComparison.Ordinal)) return false;
        var identitySeparator = line.IndexOf(" identity=", StringComparison.Ordinal);
        var fields = refresh ? new Dictionary<string, string>() : TraceFields.Extract(identitySeparator < 0 ? line : line[..identitySeparator]);
        var identityText = refresh ? line[(line.IndexOf(refreshTag, StringComparison.Ordinal)+refreshTag.Length)..]
            : identitySeparator >= 0 ? line[(identitySeparator+" identity=".Length)..] : null;
        (EvidenceObject Identity, bool Duplicate) ReadIdentity()
        {
            if (identityText is null) throw new FormatException("missing_dynamic_identity");
            var identity = BuffDynamicIdentity.Parse(identityText, out var duplicateFields);
            return (identity, duplicateFields);
        }
        return Observe(refresh, fields, ReadIdentity,
            (skill, action, value) => LegacyBuffResistance.Observe(state, identityText, refresh, fields, skill, action, value, lineNumber, timestampMs), lineNumber, timestampMs);
    }

    public bool Observe(bool refresh, IReadOnlyDictionary<string, string> fields, EvidenceObject observation, int lineNumber, long timestampMs)
        => Observe(refresh, fields, () => (new EvidenceObject(BuffPacketWire.WithPairs(observation).Fields), false),
            (skill, action, value) => LegacyBuffResistance.Observe(state, observation, refresh, fields, skill, action, value, lineNumber, timestampMs), lineNumber, timestampMs);

    private bool Observe(bool refresh, IReadOnlyDictionary<string, string> fields, Func<(EvidenceObject Identity, bool Duplicate)> readIdentity,
        Action<string?, BigInteger?, double?> observeLegacy, int lineNumber, long timestampMs)
    {
        var value = TraceFields.OptionalFloat(fields.GetValueOrDefault("value"));
        var skill = fields.GetValueOrDefault("skill");
        var action = TraceFields.OptionalInteger(fields.GetValueOrDefault("actionId"));
        string? blackboardKey = null;
        var observed = new BuffObservation(BuffEvidence.Object(
            ("line_no", new EvidenceInteger(lineNumber)), ("ts_ms", new EvidenceInteger(timestampMs)),
            ("seq", BuffEvidence.Number(TraceFields.OptionalInteger(fields.GetValueOrDefault("seq")))),
            ("tick", BuffEvidence.Number(TraceFields.OptionalInteger(fields.GetValueOrDefault("tick")))),
            ("instance_id", BuffEvidence.Text(fields.GetValueOrDefault("inst"))), ("owner_id", BuffEvidence.Text(fields.GetValueOrDefault("ownerId"))),
            ("owner", BuffEvidence.Text(fields.GetValueOrDefault("owner"))), ("skill_key", BuffEvidence.Text(skill)),
            ("action_id", BuffEvidence.Number(action)), ("blackboard_key", EvidenceNull.Value),
            ("value", value is double number ? new EvidenceReal(number) : EvidenceNull.Value)));
        if (state.Roots.TryGetValue(skill ?? "", out var initialRoot) && action is BigInteger initialAction)
        {
            var matches = (state.ActionIndices.For(initialRoot).Actions.GetValueOrDefault(initialAction) ?? [])
                .Where(row => PacketBuffCatalog.Text(row.Definition.Get("$type")).Replace('+', '.') == ModifyType).ToArray();
            if (matches.Length == 1)
            {
                var node = matches[0].Definition;
                var key = PacketBuffCatalog.Text(node.Get("key"));
                blackboardKey = key.Length > 0 ? key : null;
                var operand = node.Get("value") as EvidenceObject;
                observed.Set("blackboard_key_source", new EvidenceText("typed_current_buff_action"));
                observed.Set("operand_blackboard_key", operand?.Get("useBlackboardKey") is EvidenceBoolean { Value: true } ? operand.Get("blackboardKey") : EvidenceNull.Value);
                observed.Set("operation", node.Get("operation"));
            }
            else observed.Set("mapping_error", new EvidenceText(matches.Length > 1 ? "ambiguous_dynamic_action" : "missing_dynamic_action"));
        }
        else if (action is BigInteger actionId && skillMetadata(skill ?? "").DynamicActionKeys.TryGetValue(actionId, out var key))
        {
            blackboardKey = key;
            observed.Set("blackboard_key_source", new EvidenceText("unversioned_skill_observation"));
        }
        observed.Set("blackboard_key", BuffEvidence.Text(blackboardKey));
        (refresh ? state.AttributeRefreshEvents : state.DynamicEvents).Add(observed);
        observeLegacy(skill, action, value);
        EvidenceObject? identity = null;
        var identityBound = false;
        try
        {
            var parsed = readIdentity();
            identity = parsed.Identity;
            if (parsed.Duplicate) throw new FormatException("duplicate_dynamic_identity_fields");
            observed.Set("identity", identity);
            var bound = BuffDynamicIdentity.Bind(state, identity, refresh, fields, skill, action, value);
            state.MarkProjectionChanged(bound.Record);
            identityBound = true;
            var root = state.Roots.GetValueOrDefault(bound.Template);
            var matches = state.ActionIndices.For(root ?? (EvidenceValue)EvidenceNull.Value).Actions.GetValueOrDefault(bound.ActionId);
            if (matches is not { Count: 1 } || !matches[0].Enabled || BuffEvidence.String(matches[0].Definition.Get("$type")) != (refresh ? RefreshType : ModifyType))
                throw new FormatException("dynamic_action_not_in_current_template");
            var node = matches[0].Definition;
            BuffCreationRuntimeProof.Update(state, bound, root!);
            var pending = Pending(bound);
            var key = refresh ? "" : PacketBuffCatalog.Text(node.Get("key"));
            var signature = new BuffDynamicOperation(refresh ? 31 : 7, bound.ActionId, key, value, (EvidenceObject)BuffEvidence.Hook(identity));
            if (pending.Operations.TryGetValue(bound.Sequence, out var previous) && previous.SameAs(signature))
            {
                observed.Set("state_status", new EvidenceText("duplicate_dynamic_observation"));
                return true;
            }
            if (bound.Sequence < pending.LastSequence || previous is not null && !previous.SameAs(signature))
            {
                if (key.Length > 0) { pending.Values.Remove(key); pending.InvalidKeys.Add(key); }
                else pending.InvalidKeys.Add("*");
                foreach (var snapshot in bound.Record.AttributeRefreshSnapshots)
                {
                    if (snapshot.Get("identity") is not EvidenceObject snapshotIdentity || Context(snapshotIdentity) != bound.Context
                        || BuffEvidence.Integer(snapshot.Get("operation_seq")) < bound.Sequence) continue;
                    snapshot.Set("status", new EvidenceText("conflicting_dynamic_operation"));
                    var conflicts = snapshot.Get("conflicting_operation_seqs") is EvidenceArray array ? array.Items.ToList() : [];
                    conflicts.Add(new EvidenceInteger(bound.Sequence));
                    snapshot.Set("conflicting_operation_seqs", new EvidenceArray(conflicts));
                }
                throw new FormatException("conflicting_dynamic_operation_order");
            }
            pending.Operations[bound.Sequence] = signature;
            pending.LastSequence = bound.Sequence;
            if (!refresh)
            {
                if (key.Length == 0) throw new FormatException("missing_dynamic_target_key");
                pending.Values[key] = value!.Value;
                pending.ValueSources[key] = BuffEvidence.Object(("kind", new EvidenceText("typed_runtime_post_assignment")),
                    ("operation_seq", new EvidenceInteger(bound.Sequence)), ("session_id", new EvidenceText(bound.Context.SessionId)),
                    ("operation_owner_id", new EvidenceText(bound.Context.OwnerId)), ("generation", bound.Context.Generation));
                pending.InvalidKeys.Remove(key);
                bound.Record.DynamicUnresolvedKeys.Remove(key);
                observed.Set("blackboard_key", new EvidenceText(key));
                observed.Set("blackboard_key_source", new EvidenceText("typed_current_buff_action"));
                observed.Set("operation", node.Get("operation"));
                observed.Set("state_status", new EvidenceText("pending_attribute_refresh"));
                observed.Set("instance_start_line_no", new EvidenceInteger(bound.Record.InstanceStartLineNumber));
            }
            else
            {
                observed.Set("instance_id", new EvidenceText(bound.Uid));
                observed.Set("owner_id", identity.Get("ownerId"));
                observed.Set("skill_key", new EvidenceText(bound.Template));
                observed.Set("action_id", new EvidenceInteger(bound.ActionId));
                observed.Set("seq", new EvidenceInteger(bound.Sequence));
                observed.Set("state_status", new EvidenceText("attribute_refresh_observed"));
                var snapshot = BuffAttributeParameters.Build(state, bound, root!, pending, lineNumber, timestampMs);
                bound.Record.AttributeRefreshSnapshots.Add(snapshot);
                observed.Set("snapshot_status", snapshot.Get("status"));
                observed.Set("snapshot", snapshot.Evidence);
            }
        }
        catch (FormatException error)
        {
            observed.Set("state_error", new EvidenceText(error.Message));
            if (!refresh && (identityBound || identity is null) && state.ActiveByUid.TryGetValue(fields.GetValueOrDefault("inst") ?? "", out var affected)
                && fields.GetValueOrDefault("ownerId") == affected.TargetActorId && skill == affected.EventKey)
            {
                var unknown = string.IsNullOrEmpty(blackboardKey) ? "*" : blackboardKey;
                state.MarkProjectionChanged(affected);
                affected.DynamicUnresolvedKeys.Add(unknown);
                affected.DynamicState?.InvalidKeys.Add(unknown);
            }
            if (refresh)
            {
                state.UnresolvedActions.Add(new(BuffEvidence.Object(("ts_ms", new EvidenceInteger(timestampMs)), ("line_no", new EvidenceInteger(lineNumber)),
                    ("uid", observed.Get("instance_id")), ("reason", new EvidenceText("unbound_buff_attribute_refresh")), ("detail", new EvidenceText(error.Message)))));
            }
        }
        return true;
    }

    private static BuffOperationContext Context(EvidenceObject identity) => new(BuffEvidence.String(identity.Get("sessionId"))!,
        BuffEvidence.String(identity.Get("operationOwnerId"))!, identity.Get("generation"));

    private static BuffDynamicState Pending(BoundDynamicIdentity bound)
    {
        var record = bound.Record;
        var pending = record.DynamicState;
        if (pending is null)
        {
            var seeds = record.CreationObservations.Where(row => BuffEvidence.Integer(row.Get("operationSeq")) <= bound.Sequence
                && row.Get("bb_values") is EvidenceObject { Fields.Count: > 0 }).ToArray();
            var latest = seeds.Select(row => BuffEvidence.Integer(row.Get("operationSeq"))!.Value).DefaultIfEmpty(-1).Max();
            seeds = seeds.Where(row => BuffEvidence.Integer(row.Get("operationSeq")) == latest).ToArray();
            pending = new(bound.Context);
            if (seeds.Length > 0 && seeds.Select(row => EvidenceJsonSignature.Sorted(row.Get("bb_values"))).Distinct(StringComparer.Ordinal).Count() == 1
                && seeds.All(row => BuffEvidence.String(row.Get("operationOwnerId")) != bound.Context.OwnerId
                    || EvidenceJson.PythonEquals(row.Get("operationGeneration"), bound.Context.Generation)))
            {
                var seed = seeds[0];
                foreach (var (key, number) in ((EvidenceObject)seed.Get("bb_values")).Fields)
                {
                    pending.Values[key] = BuffEvidence.FiniteNumber(number)!.Value;
                    pending.ValueSources[key] = BuffEvidence.Object(("kind", new EvidenceText("creation_observation")),
                        ("creation_key", new EvidenceArray([seed.Get("sessionId"), seed.Get("operationOwnerId"), seed.Get("operationGeneration"), seed.Get("operationSeq"), new EvidenceText(bound.Uid)])));
                }
            }
            pending.InvalidKeys.UnionWith(record.DynamicUnresolvedKeys);
            foreach (var seed in seeds)
                if (seed.Get("bb_conflicts") is EvidenceArray conflicts) pending.InvalidKeys.UnionWith(conflicts.Items.OfType<EvidenceText>().Select(text => text.Value));
            record.DynamicState = pending;
        }
        else if (pending.Context != bound.Context)
        {
            if (record.DynamicSeenContexts.Contains(bound.Context)) throw new FormatException("dynamic_context_reused_out_of_order");
            record.DynamicState = pending = new(bound.Context);
        }
        record.DynamicSeenContexts.Add(bound.Context);
        return pending;
    }
}
