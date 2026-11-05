using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

internal static class BuffSpecs
{
    public static void Run(Action<bool, string> check)
    {
        const string duplicate = """{"x":1,"x":2,"nested":{"a":1,"a":2}}""";
        var regular = (EvidenceObject)EvidenceJson.Parse(duplicate);
        var paired = (EvidenceObject)EvidenceJson.ParseWithPairs(duplicate);
        check(regular.SourcePairs is null && regular.Get("x") is EvidenceInteger { Value: var last } && last == 2, "Regular evidence retains last-wins contract");
        check(paired.SourcePairs?.Count == 3 && paired.Fields.Count == 2
            && paired.Get("nested") is EvidenceObject { SourcePairs.Count: 2, Fields.Count: 1 }, "Strict packet observations can detect nested duplicate fields");
        var pairedCopy = (EvidenceObject)EvidenceJson.Clone(paired);
        check(pairedCopy.Fields.Keys.SequenceEqual(paired.Fields.Keys) && pairedCopy.SourcePairs?.Select(pair => pair.Key).SequenceEqual(["x", "x", "nested"]) == true
            && pairedCopy.SourcePairs[0].Value is EvidenceInteger { Value: var earlier } && earlier == 1
            && pairedCopy.Get("nested") is EvidenceObject { SourcePairs.Count: 2 },
            "Cloned packet evidence preserves original duplicate fields and their order independently of last-wins lookup");
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)pairedCopy.Get("nested")).Fields)["a"] = EvidenceNull.Value;
        check(((EvidenceObject)paired.Get("nested")).Get("a") is EvidenceInteger { Value: var originalNested } && originalNested == 2
            && ((EvidenceObject)pairedCopy.SourcePairs![2].Value).Get("a") is EvidenceInteger { Value: var pairNested } && pairNested == 2,
            "Changing cloned nested lookup data cannot change the original or separately captured source-pair evidence");
        var numeric = (EvidenceObject)EvidenceJson.ParseReadOnly("""{"values":[9223372036854775809,-0.0,NaN,Infinity],"empty":{}}""");
        var numericCopy = (EvidenceObject)EvidenceJson.Clone(numeric);
        var numbersCopy = (EvidenceArray)numericCopy.Get("values");
        check(numbersCopy.Items[0] is EvidenceInteger { Value: var exactWide } && exactWide == System.Numerics.BigInteger.Parse("9223372036854775809")
            && numbersCopy.Items[1] is EvidenceReal zero && BitConverter.DoubleToInt64Bits(zero.Value) == long.MinValue
            && numbersCopy.Items[2] is EvidenceReal nan && double.IsNaN(nan.Value)
            && numbersCopy.Items[3] is EvidenceReal { Value: double.PositiveInfinity },
            "Cloning immutable resource evidence retains wide integers, signed zero and named floating-point constants");
        ((EvidenceValue[])numbersCopy.Items)[0] = EvidenceNull.Value;
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)numericCopy.Get("empty")).Fields)["new"] = EvidenceNull.Value;
        check(((EvidenceArray)numeric.Get("values")).Items[0] is EvidenceInteger
            && ((EvidenceObject)numeric.Get("empty")).Fields.Count == 0,
            "Cloned immutable arrays and empty objects become independent mutable report containers");
        Dictionary<string, string> numbers = [];
        Dictionary<string, EvidenceObject> roots = [];
        var catalog = new PacketBuffCatalog(new Dictionary<string, EvidenceObject>(), new Dictionary<string, IReadOnlyList<EvidenceObject>>(), numbers);
        var first = new BuffInstanceState(catalog, roots, numbers, key => key, key => key);
        var second = new BuffInstanceState(catalog, roots, numbers, key => key, key => key);
        first.ObserveLifecycle(" BUFF_START uid=7 id=buff_test owner=eny_0001_target ownerId=22 src=chr_0001_alpha srcId=11", 1, 100);
        first.ObserveBlackboard(" BB[ resistance=-0.2 ]");
        check(first.ActiveByUid.Count == 1 && second.ActiveByUid.Count == 0 && second.PendingRecord is null && second.Records.Count == 0, "BUFF streams isolate pending and live instance state");
        var root = EvidenceJson.Parse("""{"serverActionIndex":1,"isEnable":true}""");
        check(!ReferenceEquals(first.ActionIndices.For(root), second.ActionIndices.For(root)), "Typed action proof caches are owned by each ingestion stream");
        var record = first.ActiveByUid["7"];
        record.CreationObservations.Add(new((EvidenceObject)EvidenceJson.Parse("""{"sessionId":"s","operationSeq":1,"line_no":1}""")));
        new BuffPacketObservations(first).Observe(""" BUFF_KEYWORD_UPDATE {"schemaVersion":1,"operationPayloadCase":"trigger_keyword_op_data","buffUid":"7","ownerId":"22","sessionId":"s","operationSeq":2,"generation":0,"addedBuffNumId":1,"modify":[{"configIndex":0,"rateAfter":0.2}]}""", 2, 101);
        check(record.KeywordRateSnapshots is null && record.KeywordSeenUpdates is null
            && first.UnresolvedActions.Last().Get("reason") is EvidenceText { Value: "keyword_update_without_approved_origin" },
            "Keyword updates without an approval provider cannot grant a rate or consume a signature");

        var directory = Path.Combine(Path.GetTempPath(), "endfield-skill-metadata-spec-"+Guid.NewGuid().ToString("N"));
        var internalRoot = Path.Combine(directory, "_internal");
        var file = Path.Combine(internalRoot, "data/akedata/skill/items/synthetic.json");
        Directory.CreateDirectory(Path.GetDirectoryName(file)!);
        try
        {
            File.WriteAllText(file, """{"castType":"before"}""");
            var metadata = new SkillItemMetadataCatalog(new ResourceFiles(internalRoot));
            var original = metadata.For("synthetic");
            File.WriteAllText(file, """{"castType":"after"}""");
            check(ReferenceEquals(original, metadata.For("synthetic")) && original.CastType == "before", "Metadata cache reuses its resource observation");
            for (var index = 0; index < 4096; index++) metadata.For("missing_"+index);
            check(metadata.For("synthetic").CastType == "after", "Metadata cache evicts beyond the reference 4096-key bound");
            check(!metadata.For("missing").Available, "Missing skill metadata is distinct from a present empty document");
        }
        finally { Directory.Delete(directory, recursive: true); }
    }
}
