using System.Text.Json;
using System.Text.Json.Nodes;
using EndfieldLogs.Capture.Cryptography;
using EndfieldLogs.Capture.Transport;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Integrity;

using EndfieldLogs.Protocol;
using Google.Protobuf;

try
{
    if (args is ["check-release", var installedVersion])
    {
        var update = await EndfieldLogs.Runtime.Updates.ReleaseUpdates.CheckAsync(installedVersion);
        Console.WriteLine(JsonSerializer.Serialize(new { current = installedVersion, update })); return 0;
    }
    return Run(args);
}
catch (Exception error)
{
    Console.Error.WriteLine(error);
    return 1;
}

static int Run(string[] args)
{
if (args is ["trace-jsonl-roundtrip", var jsonlInput, var jsonlOutput]) return TraceJsonlCases.RoundTrip(jsonlInput, jsonlOutput);
if (args is ["trace-historical-events", var historicalInput, var historicalOutput]) return TraceJsonlCases.HistoricalEvents(historicalInput, historicalOutput);
if (args is ["trace-damage-export", var damageJsonlInput, var damageLogOutput]) return TraceJsonlCases.ExportDamage(damageJsonlInput, damageLogOutput);
if (args is ["trace-damage-events", var structuredDamageInput, var structuredDamageOutput]) return TraceBridgeCases.StructuredDamage(structuredDamageInput, structuredDamageOutput);
if (args is ["trace-observation-events", var structuredObservationInput, var structuredObservationOutput]) return TraceBridgeCases.StructuredDamage(structuredObservationInput, structuredObservationOutput, includeEntities: true);
if (args is ["trace-observation-export", var observationJsonl, var observationLog]) return TraceJsonlCases.ExportDamage(observationJsonl, observationLog, includeEntities: true);
if (args is ["benchmark-runtime", var runtimeRoot, var runtimeInput, var runtimeOutput])
    return RuntimeBenchmark.RunAsync(runtimeRoot, runtimeInput, runtimeOutput).GetAwaiter().GetResult();
if (args is ["benchmark-session", var benchmarkRoot, var benchmarkInput, var benchmarkOutput])
    return SessionBenchmark.Run(benchmarkRoot, benchmarkInput, benchmarkOutput);
if (args is ["compare-release-updates", var releaseInput, var releaseOutput]) return ReleaseUpdateCases.Run(releaseInput, releaseOutput);
if (args is ["compare-trace-bridge", var traceInput, var traceOutput]) return TraceBridgeCases.Run(traceInput, traceOutput);
if (args is ["compare-app-settings", var settingsInput, var settingsOutput]) return SettingsCases.Run(settingsInput, settingsOutput);
if (args is ["compare-native-skins", var skinInput, var skinOutput]) return SettingsCases.Run(skinInput, skinOutput, skins: true);
if (args is ["compare-raw-log-proofs", var proofInput, var proofOutput]) return RawLogProofCases.Run(proofInput, proofOutput);
if (args is ["compare-history-index", var historyInput, var historyOutput]) return HistoryCases.Run(historyInput, historyOutput);
if (args is ["compare-damage-series", var curveInput, var curveOutput]) return DamageSeriesCases.Run(curveInput, curveOutput);
if (args is ["compare-timeline-skills", var skillTracksInput, var skillTracksOutput]) return TimelineSkillCases.Run(skillTracksInput, skillTracksOutput);
if (args is ["compare-energy-observations", var energyInput, var energyOutput]) return EnergyObservationCases.Run(energyInput, energyOutput);
if (args is ["compare-enemy-observations", var enemyInput, var enemyOutput]) return EnemyObservationCases.Run(enemyInput, enemyOutput);
if (args is ["compare-buff-display", var buffDisplayInput, var buffDisplayOutput]) return BuffDisplayCases.Run(buffDisplayInput, buffDisplayOutput);
if (args is ["compare-battle-evidence", var battleEvidenceInput, var battleEvidenceOutput]) return BattleEvidenceCases.Run(battleEvidenceInput, battleEvidenceOutput);
if (args is ["compare-battle-presentation", var battlePresentationInput, var battlePresentationOutput]) return BattlePresentationCases.Run(battlePresentationInput, battlePresentationOutput);
if (args is ["compare-input-interpretation", var inputIntentions, var outputIntentions]) return InputInterpretationCases.Run(inputIntentions, outputIntentions);
if (args is ["compare-input-evidence", var inputEvidence, var outputEvidence]) return InputEvidenceCases.Run(inputEvidence, outputEvidence);
if (args is ["compare-input-backends", var inputBackends, var outputBackends]) return InputBackendCases.Run(inputBackends, outputBackends);
if (args is ["compare-vision", var visionInput, var visionOutput]) return VisionCases.Run(visionInput, visionOutput);
if (args is ["probe-input-worker", var inputExecutable, var inputNativeDirectory, var inputProbeOutput])
    return InputNativeProbe.Run(inputExecutable, inputNativeDirectory, inputProbeOutput);
if (args is ["export-trace", var rawSource, var exportDestination])
{
    EndfieldLogs.Runtime.History.TraceExportService.Export(rawSource, exportDestination);
    Console.WriteLine("Trace snapshot exported with local integrity proof"); return 0;
}
if (args is ["compare-live-projection", var liveInput, var liveOutput]) return LiveProjectionCases.Run(liveInput, liveOutput);
if (args is ["compare-live-engine", var engineInput, var engineOutput]) return LiveEngineCases.Run(engineInput, engineOutput);
if (args is ["compare-live-session", var liveSessionInput, var liveSessionOutput]) return LiveSessionCases.Run(liveSessionInput, liveSessionOutput);
if (args is ["compare-live-publication", var publicationInput, var publicationOutput]) return LivePublicationCases.Run(publicationInput, publicationOutput);
if (args is ["compare-session-business", var businessInput, var businessOutput]) return SessionBusinessCases.Run(businessInput, businessOutput);
if (args is ["compare-session-scene", var sceneInput, var sceneOutput]) return SessionBusinessCases.Run(sceneInput, sceneOutput);
if (args is ["compare-session-inventory", var inventoryInput, var inventoryOutput]) return SessionBusinessCases.Run(inventoryInput, inventoryOutput);
if (args is ["compare-live-allocation", var cacheInput, var cacheOutput]) return LiveAllocationCases.Run(cacheInput, cacheOutput);
if (args is ["compare-report-lifecycle", var lifecycleInput, var lifecycleOutput]) return ReportLifecycleCases.Run(lifecycleInput, lifecycleOutput);
if (args is ["compare-report-projection", var projectionInput, var projectionOutput]) return ReportProjectionCases.Run(projectionInput, projectionOutput);
if (args is ["compare-critical-evidence", var criticalInput, var criticalOutput]) return CriticalEvidenceCases.Run(criticalInput, criticalOutput);
if (args is ["compare-report-timeline", var timelineInput, var timelineOutput]) return ReportTimelineCases.Run(timelineInput, timelineOutput);
if (args is ["compare-report-buffs", var buffReportInput, var buffReportOutput]) return ReportBuffEventCases.Run(buffReportInput, buffReportOutput);
if (args is ["compare-report-export", var reportInput, var reportOutput]) return ReportExportCases.Run(reportInput, reportOutput);
if (args is ["compare-allocation-preflight", var preflightInput, var preflightOutput]) return AllocationPreflightCases.Run(preflightInput, preflightOutput);
if (args is ["compare-report-accounting", var accountingInput, var accountingOutput]) return ReportAccountingCases.Run(accountingInput, accountingOutput);
if (args is ["compare-damage-ledger", var ledgerInput, var ledgerOutput]) return DamageLedgerCases.Run(ledgerInput, ledgerOutput);
if (args is ["compare-ink-provenance", var inkInput, var inkOutput]) return InkProvenanceCases.Run(inkInput, inkOutput);
if (args is ["compare-allocation-phases", var phasesInput, var phasesOutput]) return AllocationPhaseCases.Run(phasesInput, phasesOutput);
if (args is ["compare-attack-dependence", var attackInput, var attackOutput]) return AttackDependenceCases.Run(attackInput,attackOutput);
if (args is ["compare-packet-allocation", var allocationInput, var allocationOutput]) return PacketAllocationCases.Run(allocationInput,allocationOutput);
if (args is ["compare-allocation-context", var contextInput, var contextOutput]) return AllocationContextCases.Run(contextInput,contextOutput);
if (args is ["compare-report-loadouts", var loadoutsInput, var loadoutsOutput]) return ReportLoadoutCases.Run(loadoutsInput,loadoutsOutput);
if (args is ["compare-baseline-evidence", var baselineInput, var baselineOutput]) return BaselineEvidenceCases.Run(baselineInput,baselineOutput);
if (args is ["compare-static-arts-strength", var artsInput, var artsOutput]) return StaticArtsStrengthCases.Run(artsInput,artsOutput);
if (args is ["compare-static-multipliers", var multipliersInput, var multipliersOutput]) return StaticMultiplierCases.Run(multipliersInput,multipliersOutput);
if (args is ["compare-static-applicability", var applicabilityInput, var applicabilityOutput]) return StaticApplicabilityCases.Run(applicabilityInput,applicabilityOutput);
if (args is ["compare-report-baseline", var reportBaselineInput, var reportBaselineOutput]) return ReportBaselineCases.Run(reportBaselineInput,reportBaselineOutput);
if (args is ["compare-combo-windows", var comboInput, var comboOutput]) return ComboWindowCases.Run(comboInput, comboOutput);
if (args is ["compare-packet-effect-display", var displayInput, var displayOutput]) return PacketEffectDisplayCases.Run(displayInput, displayOutput);
if (args is ["compare-buff-classification", var classificationInput, var classificationOutput]) return BuffClassificationCases.Run(classificationInput, classificationOutput);
if (args is ["compare-buff-labels", var labelsInput, var labelsOutput]) return PacketEffectDisplayCases.Run(labelsInput,labelsOutput,labels:true);
if (args is ["compare-report-effect-windows", var reportWindowsInput, var reportWindowsOutput]) return ReportEffectWindowCases.Run(reportWindowsInput,reportWindowsOutput);
if (args is ["compare-effect-registry", var registryInput, var registryOutput]) return EffectRegistryCases.Run(registryInput, registryOutput);
if (args is ["compare-effect-stacks", var stackInput, var stackOutput]) return EffectStackCases.Run(stackInput, stackOutput);
if (args is ["compare-effect-windows", var windowInput, var windowOutput]) return EffectWindowCases.Run(windowInput, windowOutput);
if (args is ["compare-effect-conditions", var conditionInput, var conditionOutput]) return EffectConditionCases.Run(conditionInput, conditionOutput);
if (args is ["compare-battle-ingestion", var ingestionInput, var ingestionOutput]) return BattleIngestionCases.Run(ingestionInput, ingestionOutput);
if (args is ["compare-loadout-state", var loadoutStateInput, var loadoutStateOutput]) return LoadoutStateCases.Run(loadoutStateInput, loadoutStateOutput);
if (args is ["compare-loadout-snapshots", var loadoutInput, var loadoutOutput]) return LoadoutSnapshotCases.Run(loadoutInput, loadoutOutput);
if (args is ["compare-weapon-refinement", var refineInput, var refineOutput]) return WeaponRefinementCases.Run(refineInput, refineOutput);
if (args is ["compare-effect-approval", var approvalInput, var approvalOutput]) return EffectApprovalCases.Run(approvalInput, approvalOutput);
if (args is ["compare-hit-observations", var hitInput, var hitOutput]) return HitObservationCases.Run(hitInput, hitOutput);
if (args is ["compare-skill-damage", var damageInput, var damageOutput]) return SkillDamageCases.Run(damageInput, damageOutput);
if (args is ["compare-buff-instances", var buffInput, var buffOutput]) return BuffInstanceCases.Run(buffInput, buffOutput);
if (args is ["compare-catalogs", var catalogInput, var catalogOutput]) return CatalogCases.Run(catalogInput, catalogOutput);
if (args is ["compare-action-indices", var actionInput, var actionOutput]) return ActionIndexCases.Run(actionInput, actionOutput);
if (args is ["compare-fields", var fieldInput, var fieldOutput]) return FieldCases.Run(fieldInput, fieldOutput);
if (args is ["compare-observations", var observationInput, var observationOutput]) return ObservationCases.Run(observationInput, observationOutput);
if (args is ["compare-timers", var timerInput, var timerOutput]) return TimerCases.Run(timerInput, timerOutput);
if (args is ["compare-skill-identities", var identityInput, var identityOutput]) return SkillIdentityCases.Run(identityInput, identityOutput);
if (args is ["compare-packet-evidence", var evidenceInput, var evidenceOutput]) return PacketEvidenceCases.Run(evidenceInput, evidenceOutput);
if (args is ["compare-evidence-json", var jsonInput, var jsonOutput]) return EvidenceJsonCases.Run(jsonInput,jsonOutput);
if (args is ["compare-official-timers", var officialInput, var officialOutput]) return OfficialTimerCases.Run(officialInput,officialOutput);
if (args is ["compare-framing", var framingInput, var framingOutput]) return FramingCases.Run(framingInput, framingOutput);
if (args is ["compare-session", var sessionInput, var sessionOutput]) return SessionCases.Run(sessionInput, sessionOutput);
if (args is ["compare-packets", var packetInput, var packetOutput]) return PacketCases.Run(packetInput, packetOutput);
if (args is ["compare-transport", var transportInput, var transportOutput]) return TransportCases.Run(transportInput, transportOutput);

if (args is ["export-schema", var schemaOutput])
{
    var files = ProtocolCatalog.Files.ToDictionary(row => row.Key,
        row => Convert.ToHexStringLower(row.Value.ToProto().ToByteArray()));
    Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(schemaOutput))!);
    File.WriteAllText(schemaOutput, JsonSerializer.Serialize(files));
    Console.WriteLine($"Generated schema: {files.Count} files, {ProtocolCatalog.Messages.Count} message types");
    return 0;
}

if (args is ["compare-protocol", var wireInput, var wireOutput])
    return ProtocolCases.Run(wireInput,wireOutput);

if (args is not ["compare-foundations", var inputPath, var outputPath]) return 2;
var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
JsonArray outcomes = [];
foreach (var item in cases)
{
    var row = item!.AsObject();
    JsonNode? actual = null;
    switch (row["kind"]!.GetValue<string>())
    {
        case "xxe1":
        {
            var cipher = new Xxe1(Convert.FromHexString(row["key"]!.GetValue<string>()),
                Convert.FromHexString(row["nonce"]!.GetValue<string>()), row["counter"]!.GetValue<uint>());
            JsonArray blocks = [];
            foreach (var block in row["blocks"]!.AsArray())
                blocks.Add(Convert.ToHexStringLower(cipher.Process(Convert.FromHexString(block!.GetValue<string>()))));
            actual = blocks;
            break;
        }
        case "tcp":
        {
            var stream = new TcpStreamReassembler();
            JsonArray steps = [];
            foreach (var operation in row["operations"]!.AsArray())
            {
                JsonArray chunks = [];
                if (operation!["reset"]?.GetValue<bool>() == true) stream.Reset();
                else foreach (var chunk in stream.Accept(operation["seq"]!.GetValue<long>(),
                             Convert.FromHexString(operation["data"]!.GetValue<string>())))
                    chunks.Add(Convert.ToHexStringLower(chunk));
                var gap = stream.GapState();
                steps.Add(new JsonObject { ["chunks"] = chunks,
                    ["gap"] = gap is null ? null : new JsonArray(gap.Value.Expected, gap.Value.Lowest, gap.Value.Missing) });
            }
            actual = steps;
            break;
        }
        case "hashes":
            actual = JsonSerializer.SerializeToNode(RawLogHashes.Compute(Convert.FromHexString(row["data"]!.GetValue<string>())), JsonContract.Options);
            break;
        default: throw new InvalidDataException("Unknown foundation case");
    }
    outcomes.Add(new JsonObject { ["name"] = row["name"]!.GetValue<string>(),
        ["passed"] = JsonNode.DeepEquals(actual, row["expected"]), ["actual"] = actual });
}
Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
File.WriteAllText(outputPath, outcomes.ToJsonString(new() { WriteIndented=true }));
var failures = outcomes.Count(row => !row!["passed"]!.GetValue<bool>());
Console.WriteLine($"Foundation differential: {cases.Count} cases, {failures} differences");
return failures == 0 ? 0 : 1;
}
