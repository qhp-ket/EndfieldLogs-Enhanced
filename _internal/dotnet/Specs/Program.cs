using System.Runtime.InteropServices;
using EndfieldLogs.Capture.Cryptography;
using EndfieldLogs.Capture.Transport;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Native.Capture;

if (args is ["--input-worker", var pipeName, var parentPid, var pipeSecret] && int.TryParse(parentPid, out var inputParent))
    return await InputRecordingSpecs.Worker(pipeName, inputParent, pipeSecret);

if (args is ["--native-capture"] && OperatingSystem.IsWindows())
{
    using var api = new PcapLibrary();
    var devices = api.ListDevices();
    Console.WriteLine($"Native Npcap enumeration: {devices.Count} devices; capture not started");
    api.Dispose();
    try { api.ListDevices(); throw new InvalidOperationException("Disposed library was callable"); }
    catch (ObjectDisposedException) { }
    return 0;
}

var passed = 0;
void Check(bool condition, string description)
{
    if (!condition) throw new InvalidOperationException(description);
    passed++;
}

var groups = new Dictionary<string, Action>(StringComparer.Ordinal)
{
    ["foundations"] = Foundations,
    ["capture"] = () => CaptureSpecs.Run(Check),
    ["session"] = () => SessionSpecs.Run(Check),
    ["tools"] = () => ToolBoundarySpecs.Run(Check),
    ["buffs"] = () => BuffSpecs.Run(Check),
    ["hits"] = () => HitSpecs.Run(Check),
    ["loadout"] = () => LoadoutSpecs.Run(Check),
    ["ingestion"] = () => IngestionSpecs.Run(Check),
    ["resources"] = () => ResourceFactorySpecs.Run(Check),
    ["minghe-resources"] = () => MingheResourceSpecs.Run(Check),
    ["capture-session-options"] = () => CaptureSessionOptionsSpecs.Run(Check),
    ["effect-conditions"] = () => EffectConditionSpecs.Run(Check),
    ["effect-stacks"] = () => EffectStackSpecs.Run(Check),
    ["effect-specifications"] = () => EffectSpecificationSpecs.Run(Check),
    ["dynamic-effect-specifications"] = () => DynamicEffectSpecificationSpecs.Run(Check),
    ["combo-windows"] = () => ComboWindowSpecs.Run(Check),
    ["packet-effect-display"] = () => PacketEffectDisplaySpecs.Run(Check),
    ["buff-classification"] = () => BuffClassificationSpecs.Run(Check),
    ["buff-labels"] = () => BuffLabelSpecs.Run(Check),
    ["report-effect-windows"] = () => ReportEffectWindowSpecs.Run(Check),
    ["report-loadouts"] = () => ReportLoadoutSpecs.Run(Check),
    ["baseline-evidence"] = () => BaselineEvidenceSpecs.Run(Check),
    ["static-arts-strength"] = () => StaticArtsStrengthSpecs.Run(Check),
    ["static-multipliers"] = () => StaticMultiplierSpecs.Run(Check),
    ["static-applicability"] = () => StaticApplicabilitySpecs.Run(Check),
    ["report-baseline"] = () => StaticBaselineSpecs.Run(Check),
    ["attack-dependence"] = () => AttackDependenceSpecs.Run(Check),
    ["packet-allocation"] = () => PacketAllocationSpecs.Run(Check),
    ["allocation-context"] = () => AllocationContextSpecs.Run(Check),
    ["allocation-phases"] = () => AllocationPhaseSpecs.Run(Check),
    ["allocation-multipliers"] = () => AllocationMultiplierSpecs.Run(Check),
    ["allocation-contributors"] = () => EffectContributorSpecs.Run(Check),
    ["allocation-hit"] = () => HitAllocatorSpecs.Run(Check),
    ["ink-provenance"] = () => InkProvenanceSpecs.Run(Check),
    ["damage-ledger"] = () => DamageLedgerSpecs.Run(Check),
    ["report-accounting"] = () => ReportAccountingSpecs.Run(Check),
    ["allocation-preflight"] = () => AllocationPreflightSpecs.Run(Check),
    ["report-lifecycle"] = () => ReportLifecycleSpecs.Run(Check),
    ["report-projection"] = () => ReportProjectionSpecs.Run(Check),
    ["critical-evidence"] = () => CriticalEvidenceSpecs.Run(Check),
    ["report-timeline"] = () => ReportTimelineSpecs.Run(Check),
    ["report-buffs"] = () => ReportBuffEventSpecs.Run(Check),
    ["report-export"] = () => ReportExportSpecs.Run(Check),
    ["live-projection"] = () => LiveProjectionSpecs.Run(Check),
    ["live-engine"] = () => LiveEngineSpecs.Run(Check),
    ["live-hit-projection"] = () => LiveHitProjectionSpecs.Run(Check),
    ["live-hit-preparation"] = () => LiveHitPreparationSpecs.Run(Check),
    ["live-buff-projection"] = () => LiveBuffProjectionSpecs.Run(Check),
    ["live-events"] = () => LiveEventEngineSpecs.Run(Check),
    ["live-allocation"] = () => LiveAllocationSpecs.Run(Check),
    ["live-session"] = () => LiveSessionSpecs.Run(Check),
    ["live-event-session"] = () => LiveEventSessionSpecs.Run(Check),
    ["live-publisher"] = () => LivePublisherSpecs.Run(Check),
    ["session-business"] = () => SessionBusinessSpecs.Run(Check),
    ["session-scene"] = () => SessionSceneSpecs.Run(Check),
    ["session-inventory"] = () => SessionInventorySpecs.Run(Check),
    ["trace-bridge"] = () => TraceBridgeSpecs.Run(Check),
    ["trace-recording"] = () => TraceRecordingSpecs.Run(Check),
    ["recording-state"] = () => RecordingStateSpecs.Run(Check),
    ["trace-volumes"] = () => TraceVolumeSpecs.Run(Check),
    ["trace-event-history"] = () => TraceEventHistorySpecs.Run(Check),
    ["trace-jsonl"] = () => TraceJsonlSpecs.Run(Check),
    ["structured-historical"] = () => StructuredHistoricalSpecs.Run(Check),
    ["structured-damage"] = () => StructuredDamageSpecs.Run(Check),
    ["structured-entity"] = () => StructuredEntitySpecs.Run(Check),
    ["structured-identity"] = () => StructuredIdentitySpecs.Run(Check),
    ["structured-character-skills"] = () => StructuredCharacterSkillsSpecs.Run(Check),
    ["structured-loadout"] = () => StructuredLoadoutSpecs.Run(Check),
    ["structured-skill"] = () => StructuredSkillSpecs.Run(Check),
    ["structured-buff"] = () => StructuredBuffSpecs.Run(Check),
    ["capture-runtime"] = () => CaptureRuntimeSpecs.Run(Check),
    ["capture-service"] = () => GameCaptureServiceSpecs.Run(Check),
    ["analysis-streams"] = () => LiveAnalysisStreamsSpecs.Run(Check),
    ["loopback-websocket"] = () => LoopbackWebSocketSpecs.Run(Check),
    ["app-settings"] = () => SettingsSpecs.Run(Check),
    ["native-skins"] = () => SettingsSpecs.Skins(Check),
    ["overlay-transport"] = () => OverlaySpecs.Run(Check),
    ["trace-export"] = () => TraceExportSpecs.Run(Check),
    ["history-storage"] = () => HistorySpecs.Storage(Check),
    ["history-analysis"] = () => HistorySpecs.Analysis(Check),
    ["history-controller"] = () => HistorySpecs.Controller(Check),
    ["input-evidence"] = () => InputEvidenceSpecs.Run(Check),
    ["input-controller"] = () => InputEvidenceSpecs.Controller(Check),
    ["input-writer"] = () => InputRecordingSpecs.Writer(Check),
    ["input-recorder"] = () => InputRecordingSpecs.Recorder(Check),
    ["input-process"] = () => InputRecordingSpecs.Process(Check),
    ["input-pipe"] = () => InputRecordingSpecs.Pipe(Check),
    ["vision"] = () => VisionSpecs.Run(Check),
    ["vision-service"] = () => VisionSpecs.Service(Check),
    ["independent-services"] = () => IndependentServiceSpecs.Run(Check),
    ["capture-controller"] = () => ProductControllerSpecs.Capture(Check),
    ["damage-series"] = () => ProductControllerSpecs.Curves(Check),
    ["timeline-skills"] = () => TimelineSkillSpecs.Run(Check),
    ["buff-display"] = () => BuffDisplaySpecs.Run(Check),
    ["battle-evidence"] = () => BattleEvidenceSpecs.Run(Check),
    ["battle-presentation"] = () => BattlePresentationSpecs.Run(Check),
    ["release-updates"] = () => ReleaseUpdateSpecs.Run(Check),
};
if (args is ["--list-groups"])
{
    Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(groups.Keys));
    return 0;
}
string[] selected;
if (args.Length == 0) selected = groups.Keys.ToArray();
else if (args is ["--groups", var names]) selected = names.Split(',').Distinct(StringComparer.Ordinal).ToArray();
else
{
    Console.Error.WriteLine("Usage: Specs [--groups name,name | --list-groups | --native-capture]");
    return 2;
}
var unknown = selected.Where(name => !groups.ContainsKey(name)).ToArray();
if (unknown.Length > 0)
{
    Console.Error.WriteLine("Unknown spec groups: " + string.Join(", ", unknown));
    return 2;
}
var counts = new Dictionary<string, int>(StringComparer.Ordinal);
foreach (var name in selected)
{
    var before = passed;
    try { groups[name](); }
    catch (Exception error)
    {
        Console.Error.WriteLine($"Spec group failed: {name}\n{error}");
        return 1;
    }
    counts[name] = passed - before;
}
Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new
{
    groups = counts, not_selected = groups.Keys.Except(selected).ToArray(), assertions = passed,
}));
return 0;

void Foundations()
{
Check(Marshal.SizeOf<PcapPacketHeader>() == 16, "Npcap header ABI");
Check(Marshal.OffsetOf<PcapPacketHeader>(nameof(PcapPacketHeader.CapturedLength)).ToInt32() == 8, "Npcap capture-length offset");
Check(Marshal.SizeOf<PcapStatistics>() == 12, "Npcap stats ABI");
Check(Marshal.SizeOf<PcapDevice>() == (IntPtr.Size == 8 ? 40 : 20), "Npcap device ABI");
Check(Marshal.SizeOf<PcapAddress>() == IntPtr.Size*5, "Npcap address ABI");
Check(new PcapPacketHeader { Seconds=123, Microseconds=456789 }.TimestampMs == 123456, "Capture millisecond clock");
Check(JsonContract.Serialize(ServiceState.WaitingHandshake) == "\"waiting_handshake\"", "Service state spelling");
var eventData = new BattleLogEvent("s", 123, "BattleOpEntityDie", new Dictionary<string, object?> { ["entity_inst_id"]=42L });
Check(JsonContract.Serialize(eventData.ToPayload()) == "{\"type\":\"BattleOpEntityDie\",\"session_id\":\"s\",\"timestamp_ms\":123,\"entity_inst_id\":42}", "Event external shape");
try { _ = new Xxe1(new byte[31], new byte[12]); throw new InvalidOperationException("Invalid key accepted"); }
catch (ArgumentException) { passed++; }
try { _ = new Xxe1(new byte[32], new byte[11]); throw new InvalidOperationException("Invalid nonce accepted"); }
catch (ArgumentException) { passed++; }
var stream = new TcpStreamReassembler();
Check(stream.Accept(100, []).Count == 0 && stream.GapState() == null, "Empty TCP segment does not establish sequence");
Check(stream.Accept(100, [1,2]).Single().SequenceEqual(new byte[] { 1,2 }), "Initial TCP segment");
Check(stream.Accept(105, [5]).Count == 0 && stream.GapState() == (102,105,3), "TCP gap detection");
stream.Reset();
Check(stream.GapState() == null, "TCP reset clears gap");
}
