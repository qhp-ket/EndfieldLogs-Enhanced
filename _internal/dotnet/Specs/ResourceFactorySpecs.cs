using System.IO.Compression;
using System.Text;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;

internal static class ResourceFactorySpecs
{
    public static void Run(Action<bool, string> check)
    {
        var root = Path.Combine(Path.GetTempPath(), "endfield-resource-factory-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        void Write(string name, string contents)
        {
            var path = Path.Combine(root, name);
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllText(path, contents);
        }
        try
        {
            CompressedEncoding(check, root);
            CompiledResourceSpecs.Run(check, root);
            var numberPath = Path.Combine(root, "data/local_tables/NumIdStrTable.json");
            Write("data/local_tables/NumIdStrTable.json", """{"skill_id":{"dic":{"1":"skill_a"}},"buff_id":{"dic":{"2":"buff_a"}}}""");
            ResourceFiles numberFiles = new(root);
            var numbersA = new SkillResourceCatalog(numberFiles); var numbersB = new SkillResourceCatalog(numberFiles);
            ((Dictionary<string, string>)numbersA.Skills)["1"] = "changed";
            check(numbersB.Skills["1"] == "skill_a" && numbersB.Buffs["2"] == "buff_a",
                "Catalogs sharing a parsed ID table retain independent projected mappings");
            Write("data/local_tables/NumIdStrTable.json", """{"skill_id":{"dic":{"1":"skill_replaced"}},"buff_id":{"dic":{"2":"buff_replaced"}}}""");
            var replacedNumbers = new SkillResourceCatalog(numberFiles);
            check(replacedNumbers.Skills["1"] == "skill_replaced" && replacedNumbers.Buffs["2"] == "buff_replaced"
                && numbersB.Skills["1"] == "skill_a", "Replacing a shared ID table refreshes new catalogs without changing existing mappings");
            File.WriteAllBytes(numberPath, [0xff]);
            var encodingRejected = false;
            try { _ = new SkillResourceCatalog(numberFiles).Skills; }
            catch (DecoderFallbackException) { encodingRejected = true; }
            check(encodingRejected, "Shared numeric catalogs preserve strict UTF-8 decoding failures");
            var compressedPath = Path.Combine(root, "shared.json.gz");
            void Compress(string text)
            {
                using FileStream file = File.Create(compressedPath);
                using GZipStream gzip = new(file, CompressionMode.Compress);
                gzip.Write(Encoding.UTF8.GetBytes(text));
            }
            Compress("{\"rows\":[{\"value\":1}]}"); ResourceFiles shared = new(root);
            var document = (EvidenceObject)shared.ReadGzipRelative("shared.json.gz")!;
            var reads = Enumerable.Range(0, 16).Select(_ => Task.Run(() => shared.ReadGzipRelative("shared.json.gz"))).ToArray();
            Task.WaitAll(reads);
            check(reads.All(task => ReferenceEquals(document, task.Result)), "Concurrent catalog loads reuse one parsed compressed resource");
            var rejected = false;
            try
            {
                if (document.Fields is IDictionary<string, EvidenceValue> editable) editable["rows"] = EvidenceNull.Value;
                else rejected = true;
            }
            catch (NotSupportedException) { rejected = true; }
            var children = (EvidenceArray)document.Get("rows"); var nestedRejected = false;
            try { ((IList<EvidenceValue>)children.Items)[0] = EvidenceNull.Value; }
            catch (NotSupportedException) { nestedRejected = true; }
            check(rejected && nestedRejected && ((EvidenceObject)children.Items[0]).Fields is not Dictionary<string, EvidenceValue>,
                "Shared resource objects, arrays and nested objects are immutable");
            var ordered = (EvidenceArray)EvidenceJson.ParseReadOnly("""[{"a":1,"A":2,"a":3,"nul\u0000key":-0.0},{"a":4,"A":5,"nul\u0000key":9007199254740993},{"A":6,"a":7}]""");
            var firstFields = (EvidenceObject)ordered.Items[0]; var secondFields = (EvidenceObject)ordered.Items[1];
            check(firstFields.Fields.Keys.SequenceEqual(["a", "A", "nul\0key"])
                && firstFields.Fields.Values.First() is EvidenceInteger { Value: var lastDuplicate } && lastDuplicate == 3
                && ((EvidenceObject)ordered.Items[2]).Fields.Keys.SequenceEqual(["A", "a"])
                && firstFields.Get("A") is EvidenceInteger { Value: var upper } && upper == 2,
                "Read-only resources preserve duplicate-key position, case and per-object field order");
            check(firstFields.Get("nul\0key") is EvidenceReal zero && BitConverter.DoubleToInt64Bits(zero.Value) == long.MinValue
                && secondFields.Get("nul\0key") is EvidenceInteger exact && exact.Value == 9007199254740993L
                && !firstFields.Fields.TryGetValue("missing", out _) && !firstFields.Fields.ContainsKey("missing"),
                "Read-only resources retain exact numeric types, signed zero and missing-field semantics");
            var cloned = (EvidenceObject)EvidenceJson.Clone(firstFields); ((Dictionary<string, EvidenceValue>)cloned.Fields)["a"] = EvidenceNull.Value;
            check(firstFields.Get("a") is EvidenceInteger && secondFields.Get("a") is EvidenceInteger { Value: var secondValue } && secondValue == 4,
                "Cloning or reading one resource object cannot mutate another object's values");
            SharedNumbers(check);
            List<EvidenceValue> emptyInput = [];
            var capturedEmpty = (EvidenceArray)FrozenEvidence.Capture(new EvidenceArray(emptyInput));
            Dictionary<System.Numerics.BigInteger, EvidenceValue> emptyAttributes = [];
            var capturedAttributes = FrozenEvidence.CaptureNumbers(emptyAttributes);
            emptyInput.Add(new EvidenceInteger(7)); emptyAttributes[2] = new EvidenceInteger(8);
            var parsedEmpty = (EvidenceArray)EvidenceJson.ParseReadOnly("[]");
            var copiedEmpty = (EvidenceArray)EvidenceJson.Clone(parsedEmpty);
            var writableEmpty = (EvidenceArray)EvidenceJson.Parse("[]");
            ((IList<EvidenceValue>)writableEmpty.Items).Add(new EvidenceInteger(9));
            var emptyRejected = false;
            try { ((IList<EvidenceValue>)parsedEmpty.Items).Add(EvidenceNull.Value); }
            catch (NotSupportedException) { emptyRejected = true; }
            check(emptyRejected && capturedEmpty.Items.Count == 0 && capturedAttributes.Count == 0
                && parsedEmpty.Items.Count == 0 && copiedEmpty.Items.Count == 0 && writableEmpty.Items.Count == 1
                && !ReferenceEquals(parsedEmpty, copiedEmpty),
                "Empty immutable resource arrays and numeric snapshots stay isolated from later input mutations and ordinary writable reports");
            var varied = (EvidenceArray)EvidenceJson.ParseReadOnly("[" + string.Join(',', Enumerable.Range(0, 1300).Select(index => $"{{\"field_{index}\":{index}}}")) + "]");
            var wide = (EvidenceObject)EvidenceJson.ParseReadOnly("{" + string.Join(',', Enumerable.Range(0, 150).Select(index => $"\"field_{index}\":{index}")) + "}");
            check(varied.Items.Select((row, index) => ((EvidenceObject)row).Get("field_" + index) is EvidenceInteger number && number.Value == index).All(value => value)
                && wide.Fields.Keys.SequenceEqual(Enumerable.Range(0, 150).Select(index => "field_" + index)) && wide.Fields.Count == 150,
                "Wide and varied resource objects keep every field and value after bounded shape reuse");
            Compress("{\"rows\":[{\"value\":23456}]}");
            var refreshed = shared.ReadGzipRelative("shared.json.gz");
            check(!ReferenceEquals(document, refreshed) && ((EvidenceInteger)((EvidenceObject)((EvidenceArray)((EvidenceObject)refreshed!).Get("rows")).Items[0]).Get("value")).Value == 23456,
                "Replacing a compressed resource refreshes the scoped cache");
            File.Delete(compressedPath);
            check(shared.ReadGzipRelative("shared.json.gz") is null, "A deleted resource cannot be served from the scoped cache");
            ReadOnlyJson(check, shared, root);
            CompactSnapshots(check);
            SharedBuffCatalogs(check, shared, root, Write);
            SharedChildCatalog(check, shared, Write);
            Write("data/local_tables/NumIdStrTable.json", """{"skill_id":{"dic":{"12":"chr_0001_test_combo_a"}}}""");
            Write("data/akedata/character/manifest.json", """[{"charId":"chr_0001_test","name":"上游角色"}]""");
            Write("data/local_tables/character/manifest.json", """{"entries":[{"charId":"chr_0001_test","name":"本地角色"}]}""");
            Write("data/akedata/character/items/test.json", """{"charId":"chr_0001_test","skills":[{"name":"连携","groupType":3,"skillIds":["chr_0001_test_combo_a","chr_0001_test_combo_b"]}]}""");
            Write("data/akedata/enemy/manifest.json", """[{"templateId":"eny_0001_test","name":"合成敌人"}]""");
            var resources = BattleIngestionResources.Load(new(root));
            check(resources.CharacterName("chr_0001_test") == "本地角色" && resources.EnemyName("eny_0001_test") == "合成敌人",
                "Resource-backed ingestion uses local name precedence and the enemy manifest");
            check(resources.SkillName("skill_12") == "连携" && resources.SkillProfile("skill_12") is { Group: var group, Family: "chr_0001_test_combo_a" } && group == 3,
                "Resource-backed numeric identities resolve both names and declared skill families");
            check(resources.CharacterName("unknown") == "unknown" && resources.SkillName("unknown") is null && resources.SkillProfile("unknown") is null,
                "Resource-backed unknown names and classifications preserve distinct fallback semantics");
            const string hit = "[00:00:01.000] HP_V2 #1 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_combo_b hit=20";
            BattleIngestionStream first = new(resources), second = new(resources);
            first.Accept(1, hit);
            var recorded = first.Hits.Hits.Single();
            check(recorded.Identity.CharacterName == "本地角色" && recorded.Identity.TargetName == "合成敌人"
                && recorded.Identity.SkillName == "连携" && recorded.Action.Group == 3 && recorded.Action.Family == "chr_0001_test_combo_a",
                "Resource-backed dispatch carries names and combo family into the real hit");
            check(second.Hits.Hits.Count == 0 && second.Party.Participants.Count == 0,
                "Shared immutable resource lookup does not share battle state");
            var approvalA = resources.EffectApprovalFactory!();
            var approvalB = resources.EffectApprovalFactory!();
            check(!ReferenceEquals(approvalA.Target, approvalB.Target), "Each stream receives an independent effect approval cache");
            var independent = Enumerable.Range(0, 24).Select(_ => Task.Run(() =>
            {
                BattleIngestionStream state = new(resources);
                state.Accept(1, hit);
                return state.Hits.Hits.Single().Action;
            })).ToArray();
            Task.WaitAll(independent);
            check(independent.All(task => task.Result.Family == "chr_0001_test_combo_a" && task.Result.Group == 3)
                && first.Hits.Hits.Count == 1 && second.Hits.Hits.Count == 0,
                "Concurrent analyses safely reuse resource caches and own independent ingestion state");
        }
        finally { Directory.Delete(root, recursive: true); }
    }

    private static void CompressedEncoding(Action<bool, string> check, string root)
    {
        static byte[] Compress(byte[] bytes)
        {
            using MemoryStream output = new();
            using (GZipStream gzip = new(output, CompressionMode.Compress, leaveOpen: true)) gzip.Write(bytes);
            return output.ToArray();
        }
        static bool Rejects(byte[] bytes)
        {
            try { GzipMembers.DecodeJson(bytes); return false; }
            catch (Exception error) when (error is IOException or InvalidDataException or DecoderFallbackException) { }
            try { GzipMembers.ParseJson(bytes); return false; }
            catch (Exception error) when (error is IOException or InvalidDataException or DecoderFallbackException) { return true; }
        }
        const string text = "{\"name\":\"角色😀\",\"value\":9007199254740993,\"zero\":-0.0}";
        var first = Compress(Encoding.UTF8.GetBytes(text[..16]));
        var second = Compress(Encoding.UTF8.GetBytes(text[16..]));
        byte[] joined = [.. first, 0, 0, .. second, 0];
        check(GzipMembers.DecodeJson(joined) == text
            && GzipMembers.Decompress(joined).SequenceEqual(Encoding.UTF8.GetBytes(text))
            && PythonDisplay.Repr(GzipMembers.ParseJson(joined)) == PythonDisplay.Repr(EvidenceJson.ParseReadOnly(text)),
            "Concatenated gzip members and zero padding preserve the exact JSON bytes and Unicode text");
        var large = Encoding.UTF8.GetBytes("[\"" + new string('x', 50000) + "\"]");
        check(GzipMembers.Decompress(Compress(large)).SequenceEqual(large)
            && GzipMembers.DecodeJson(Compress(large)) == Encoding.UTF8.GetString(large)
            && GzipMembers.ParseJson(Compress(large)) is EvidenceArray { Items: [EvidenceText { Value.Length: 50000 }] }
            && GzipMembers.Decompress(Compress([])).Length == 0,
            "Compressed resources spanning multiple inflate buffers and empty members retain every byte");
        byte[] random = new byte[100_000]; new Random(27).NextBytes(random);
        var varied = Encoding.UTF8.GetBytes("[\"" + Convert.ToBase64String(random) + "\"]");
        var compressed = Compress(varied);
        byte[] repeatedMembers = [.. compressed, 0, 0, .. Compress([]), .. compressed, 0];
        check(GzipMembers.Decompress(repeatedMembers).SequenceEqual(varied.Concat(varied))
            && GzipMembers.DecodeJson(compressed) == Encoding.UTF8.GetString(varied)
            && GzipMembers.ParseJson(compressed) is EvidenceArray { Items: [EvidenceText { Value.Length: 133336 }] },
            "Bulk inflate retains identical-CRC members, empty members, padding and JSON spanning compressed input blocks");
        var corruptLarge = compressed.ToArray(); corruptLarge[^8] ^= 1;
        var wrongLargeSize = compressed.ToArray(); wrongLargeSize[^4] ^= 1;
        check(Rejects(corruptLarge) && Rejects(wrongLargeSize) && Rejects(compressed[..^12])
            && Rejects([.. compressed, 1]) && Rejects([.. compressed, .. corruptLarge]),
            "Bulk inflate still rejects corrupt trailers, truncation and trailing invalid members before returning JSON");
        var brokenCrc = second.ToArray(); brokenCrc[^8] ^= 1;
        var brokenSize = second.ToArray(); brokenSize[^4] ^= 1;
        check(Rejects([.. first, .. brokenCrc]) && Rejects([.. first, .. brokenSize])
            && Rejects(joined[..^5]) && Rejects([.. first, 1]) && Rejects([31, 139, 8]),
            "Every gzip member validates its CRC, size, trailer and header before returning resource text");
        var encodings = new Encoding[] { new UTF8Encoding(true), new UnicodeEncoding(false, true),
            new UnicodeEncoding(true, true), new UTF32Encoding(false, true), new UTF32Encoding(true, true) };
        check(encodings.All(encoding => GzipMembers.DecodeJson(Compress(
            [.. encoding.GetPreamble(), .. encoding.GetBytes(text)])) == text)
            && encodings.All(encoding => PythonDisplay.Repr(GzipMembers.ParseJson(Compress(
                [.. encoding.GetPreamble(), .. encoding.GetBytes(text)]))) == PythonDisplay.Repr(EvidenceJson.ParseReadOnly(text)))
            && encodings.Skip(1).All(encoding => GzipMembers.DecodeJson(Compress(encoding.GetBytes(text))) == text),
            "Compressed JSON retains UTF-8/16/32 BOM detection and BOM-less wide encoding detection");
        byte[] surrogate = [34, 0xed, 0xa0, 0x80, 34];
        check(JsonByteEncoding.Decode(surrogate) == "\"\ud800\""
            && GzipMembers.DecodeJson(Compress(surrogate)) == "\"\ud800\""
            && GzipMembers.ParseJson(Compress(surrogate)) is EvidenceText { Value: "\ud800" }
            && Rejects(Compress([34, 0xc0, 0x80, 34])) && Rejects(Compress([34, 0xf4, 0x90, 0x80, 0x80, 34]))
            && Rejects(Compress([34, 0xe2, 0x82])),
            "UTF-8 fast decoding retains encoded surrogates and rejects overlong, out-of-range and truncated sequences");
        var path = Path.Combine(root, "encoding.json.gz");
        File.WriteAllBytes(path, Compress(Encoding.UTF8.GetBytes(text)));
        ResourceFiles resources = new(root);
        var valid = (EvidenceObject)resources.ReadGzipRelative("encoding.json.gz")!;
        File.WriteAllBytes(path, [.. first, .. brokenCrc]);
        check(resources.ReadGzipRelative("encoding.json.gz") is null
            && valid.Get("name") is EvidenceText { Value: "角色😀" },
            "An invalid replacement member is rejected without returning stale data or changing prior readers");
        const string extensions = """{"a":NaN,"A":Infinity,"a":-Infinity,"wide":9007199254740993,"zero":-0.0,"surrogate":"\ud800","nil\u0000key":true}""";
        var parsed = (EvidenceObject)GzipMembers.ParseJson(Compress(Encoding.UTF8.GetBytes(extensions)));
        check(PythonDisplay.Repr(parsed) == PythonDisplay.Repr(EvidenceJson.ParseReadOnly(extensions))
            && parsed.Fields.Keys.SequenceEqual(["a", "A", "wide", "zero", "surrogate", "nil\0key"]),
            "Resource UTF-8 parsing preserves Python extensions, duplicate-key order, exact types and unpaired escape values");
        var nested = new string('[', 100) + "0" + new string(']', 100);
        var deeper = new string('[', 150) + "0" + new string(']', 150);
        check(EvidenceJson.ParseReadOnlyUtf8(Encoding.UTF8.GetBytes(nested)) is EvidenceArray
            && EvidenceJson.ParseReadOnlyUtf8(Encoding.UTF8.GetBytes(deeper)) is EvidenceArray,
            "Nested resource documents preserve acceptance through the shared text and UTF-8 reader");
    }

    private static void SharedNumbers(Action<bool, string> check)
    {
        const string text = "[-1,0,1,255,256,-2,0.0,-0.0,1.0,1e0,9007199254740993,1e999,-1e999,NaN]";
        var first = (EvidenceArray)EvidenceJson.ParseReadOnly(text);
        var second = (EvidenceArray)EvidenceJson.ParseReadOnly(text);
        var ordinary = (EvidenceArray)EvidenceJson.Parse(text);
        check(first.Items.Select((value, index) => EvidenceJson.PythonEquals(value, ordinary.Items[index])
            || value is EvidenceReal nan && double.IsNaN(nan.Value) && ordinary.Items[index] is EvidenceReal other && double.IsNaN(other.Value)).All(value => value),
            "Shared read-only numeric constants preserve integer precision, float overflow and named NaN values");
        check(Enumerable.Range(0, 4).All(index => ReferenceEquals(first.Items[index], second.Items[index]))
            && !ReferenceEquals(first.Items[4], second.Items[4]) && !ReferenceEquals(first.Items[5], second.Items[5]),
            "Read-only integer sharing is bounded to -1 through 255 rather than retaining arbitrary observations");
        check(first.Items[1] is EvidenceInteger && first.Items[6] is EvidenceReal positive && first.Items[7] is EvidenceReal negative
            && BitConverter.DoubleToInt64Bits(positive.Value) == 0 && BitConverter.DoubleToInt64Bits(negative.Value) == long.MinValue
            && ReferenceEquals(first.Items[6], second.Items[6]) && ReferenceEquals(first.Items[8], first.Items[9])
            && !ReferenceEquals(first.Items[6], first.Items[7]) && !ReferenceEquals(first.Items[1], first.Items[6]),
            "Numeric sharing keeps signed zero, integer/float distinctions and equivalent finite float syntax");
        var clone = (EvidenceArray)EvidenceJson.Clone(first);
        ((EvidenceValue[])clone.Items)[0] = new EvidenceInteger(99);
        check(first.Items[0] is EvidenceInteger original && original.Value == -1
            && second.Items[0] is EvidenceInteger unchanged && unchanged.Value == -1,
            "Replacing a cloned report value cannot alter shared immutable numeric constants");
        var concurrent = Enumerable.Range(0, 16).Select(_ => Task.Run(() => (EvidenceArray)EvidenceJson.ParseReadOnly(text))).ToArray();
        Task.WaitAll(concurrent);
        check(concurrent.All(task => ReferenceEquals(task.Result.Items[0], first.Items[0])
            && ReferenceEquals(task.Result.Items[7], first.Items[7])), "Independent readers safely reuse fixed immutable numeric constants");
    }

    private static void SharedBuffCatalogs(Action<bool, string> check, ResourceFiles resources, string root,
        Action<string, string> write)
    {
        const string details = "data/local_semantics/buff/details.json";
        const string contents = """{"entries":{"buff_test":{"stacking":{"maxStackCnt":3},"actionTypes":["VulnerableAction"]}}}""";
        write(details, contents);
        write("data/local_semantics/classifier_hints.json", """{"buffHints":{"buff_test":{"classification":"wrapper","createdBuffIds":["buff_common_vfx_test"]}}}""");
        PacketBuffCatalog packets = new(new Dictionary<string, EvidenceObject>(),
            new Dictionary<string, IReadOnlyList<EvidenceObject>>(), new Dictionary<string, string>());
        var stacks = EffectStackPolicy.Load(resources, new Dictionary<string, EvidenceObject>());
        var labels = BuffDisplayClassification.Load(resources, packets);
        var record = (EvidenceObject)EvidenceJson.Parse("""{"event_key":"buff_test"}""");
        var editable = (EvidenceObject)resources.ReadRelative(details)!;
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)editable.Get("entries")).Fields).Clear();
        check(stacks.Limit("buff_test") == 3 && !labels.IsEffectlessWrapper(record),
            "Read-only BUFF semantics keep stack limits and wrapper classification independent of ordinary mutable resource reads");
        write(details, contents.Replace("3", "7").Replace("VulnerableAction", "UnrelatedAction"));
        var path = Path.Combine(root, details);
        File.SetLastWriteTimeUtc(path, File.GetLastWriteTimeUtc(path).AddSeconds(1));
        var refreshedStacks = EffectStackPolicy.Load(resources, new Dictionary<string, EvidenceObject>());
        var refreshedLabels = BuffDisplayClassification.Load(resources, packets);
        check(stacks.Limit("buff_test") == 3 && !labels.IsEffectlessWrapper(record)
            && refreshedStacks.Limit("buff_test") == 7 && refreshedLabels.IsEffectlessWrapper(record),
            "New BUFF catalog owners observe changed resource files while previous analyses retain their original rules");
    }

    private static void SharedChildCatalog(Action<bool, string> check, ResourceFiles resources, Action<string, string> write)
    {
        const string details = "data/local_semantics/buff/details.json";
        const string parent = "data/akedata/buff/items/parent.json";
        const string contents = """{"entries":{"parent":{"referencedBuffIds":["child"],"source":{"decodedDetailPath":"data/akedata/buff/items/parent.json"}}}}""";
        const string action = """{"$type":"EnhancedAction+Data","subType":"Fire","asChildBuff":true,"childBuffId":{"value":"child"},"rate":{"blackboardKey":"damage"}}""";
        write(details, contents);
        write(parent, action);
        var catalog = EnhancedChildEffectCatalog.Load(resources);
        var editable = (EvidenceObject)resources.ReadRelative(details)!;
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)editable.Get("entries")).Fields).Clear();
        var observed = catalog.For("child").Single();
        ((Dictionary<string, EvidenceValue>)observed.Fields)["bb_key"] = new EvidenceText("consumer edit");
        check(catalog.For("child").Single().Get("bb_key") is EvidenceText { Value: "damage" }
            && observed.Get("element") is EvidenceText { Value: "fire" },
            "Shared child BUFF semantics retain the exact decoded effect and return independent editable display rows");
        write(details, contents.Replace("\"child\"", "\"replacement\""));
        write(parent, action.Replace("\"child\"", "\"replacement\""));
        var refreshed = EnhancedChildEffectCatalog.Load(resources);
        check(catalog.For("child").Count == 1 && catalog.For("replacement").Count == 0
            && refreshed.For("child").Count == 0 && refreshed.For("replacement").Single().Get("bb_key") is EvidenceText { Value: "damage" },
            "A new child BUFF catalog refreshes source rules without changing a prior catalog or its cached effects");
    }

    private static void CompactSnapshots(Action<bool, string> check)
    {
        FrozenEvidence.Context context = new();
        var source = (EvidenceObject)EvidenceJson.ParseWithPairs("""{"a":1,"a":2,"items":[{"value":-0.0}],"wide":9007199254740993}""");
        var first = (EvidenceObject)context.Capture(source);
        ((IDictionary<string, EvidenceValue>)((EvidenceObject)((EvidenceArray)source.Get("items")).Items[0]).Fields)["value"] = new EvidenceInteger(9);
        ((IDictionary<string, EvidenceValue>)source.Fields)["a"] = EvidenceNull.Value;
        var next = (EvidenceObject)context.Capture(source);
        check(first.Fields.Keys.SequenceEqual(new[] { "a", "items", "wide" }) && first.Get("a") is EvidenceInteger { Value: var original } && original == 2
            && first.Get("wide") is EvidenceInteger { Value: var wide } && wide == 9007199254740993L
            && ((EvidenceObject)((EvidenceArray)first.Get("items")).Items[0]).Get("value") is EvidenceReal { Value: var zero }
            && BitConverter.DoubleToInt64Bits(zero) == long.MinValue && next.Get("a") is EvidenceNull
            && first.SourcePairs is { Count: 4 } pairs && pairs[0].Value is EvidenceInteger { Value: var duplicate } && duplicate == 1,
            "Compact snapshots preserve exact values, duplicate-pair order and independent history after producer mutations");
        var rejected = false;
        try { ((IDictionary<string, EvidenceValue>)first.Fields)["a"] = EvidenceNull.Value; }
        catch (NotSupportedException) { rejected = true; }
        var clone = (EvidenceObject)EvidenceJson.Clone(first);
        ((IList<EvidenceValue>)((EvidenceArray)clone.Get("items")).Items)[0] = EvidenceNull.Value;
        check(rejected && ((EvidenceArray)first.Get("items")).Items[0] is EvidenceObject && ((EvidenceArray)next.Get("items")).Items[0] is EvidenceObject,
            "Compact read-only dictionary operations reject edits while ordinary clones remain writable and isolated");
        context.Clear();
        var reordered = (EvidenceObject)context.Capture(EvidenceJson.Parse("""{"items":null,"a":3}"""));
        check(reordered.Fields.Keys.SequenceEqual(new[] { "items", "a" }) && first.Get("a") is EvidenceInteger && first.SourcePairs is { Count: 4 },
            "Clearing cache metadata and capturing another field order does not invalidate previously returned snapshots");
        EvidenceObject? last = null;
        for (var index = 0; index < 1100; index++)
            last = (EvidenceObject)context.Capture(new EvidenceObject(new Dictionary<string, EvidenceValue> { ["key_" + index] = new EvidenceInteger(index) }));
        var broad = (EvidenceObject)context.Capture(new EvidenceObject(Enumerable.Range(0, 150)
            .ToDictionary(index => "field_" + index, index => (EvidenceValue)new EvidenceInteger(index))));
        context.Clear();
        check(last!.Get("key_1099") is EvidenceInteger { Value: var tail } && tail == 1099 && broad.Fields.Count == 150
            && broad.Get("field_149") is EvidenceInteger { Value: var end } && end == 149 && FrozenEvidence.IsFrozenRoot(broad),
            "Wide and exhausted metadata pools retain all immutable snapshot evidence without expanding the metadata limit");
    }

    private static void ReadOnlyJson(Action<bool, string> check, ResourceFiles resources, string root)
    {
        var path = Path.Combine(root, "shared.json");
        const string contents = """{"rows":[{"a":1,"A":9007199254740993,"a":3,"zero":-0.0}]}""";
        File.WriteAllText(path, contents);
        var document = (EvidenceObject)resources.ReadOnlyRelative("shared.json")!;
        var reads = Enumerable.Range(0, 16).Select(_ => Task.Run(() => resources.ReadOnlyRelative("shared.json"))).ToArray();
        Task.WaitAll(reads);
        var row = (EvidenceObject)((EvidenceArray)document.Get("rows")).Items[0];
        check(reads.All(task => ReferenceEquals(document, task.Result))
            && row.Fields.Keys.SequenceEqual(["a", "A", "zero"])
            && row.Get("a") is EvidenceInteger { Value: var a } && a == 3
            && row.Get("A") is EvidenceInteger { Value: var wide } && wide == 9007199254740993L
            && row.Get("zero") is EvidenceReal zero && BitConverter.DoubleToInt64Bits(zero.Value) == long.MinValue,
            "Concurrent uncompressed catalog reads share exact values, field order and numeric categories");
        var rejected = false;
        try
        {
            if (row.Fields is IDictionary<string, EvidenceValue> editable) editable["a"] = EvidenceNull.Value;
            else rejected = true;
        }
        catch (NotSupportedException) { rejected = true; }
        var mutable = (EvidenceObject)resources.ReadRelative("shared.json")!;
        ((Dictionary<string, EvidenceValue>)((EvidenceObject)((EvidenceArray)mutable.Get("rows")).Items[0]).Fields)["a"] = EvidenceNull.Value;
        check(rejected && row.Get("a") is EvidenceInteger && !ReferenceEquals(mutable, document),
            "Shared plain resources reject mutation while ordinary readers retain independent mutable results");
        File.WriteAllText(path, contents.Replace("9007199254740993", "9007199254740994"));
        File.SetLastWriteTimeUtc(path, File.GetLastWriteTimeUtc(path).AddSeconds(1));
        var refreshed = (EvidenceObject)resources.ReadOnlyRelative("shared.json")!;
        check(!ReferenceEquals(document, refreshed)
            && ((EvidenceObject)((EvidenceArray)refreshed.Get("rows")).Items[0]).Get("A") is EvidenceInteger { Value: var next } && next == 9007199254740994L,
            "A same-size changed catalog refreshes the cache without changing earlier readers");
        File.WriteAllText(path, "{invalid");
        check(resources.ReadOnlyRelative("shared.json") is null, "Malformed replacement cannot return a stale parsed catalog");
        File.WriteAllBytes(path, [0xef, 0xbb, 0xbf, .. Encoding.UTF8.GetBytes(contents)]);
        check(resources.ReadOnlyRelative("shared.json") is null, "Read-only plain JSON preserves strict UTF-8 BOM rejection");
        File.WriteAllBytes(path, [0xff]);
        check(resources.ReadOnlyRelative("shared.json") is null, "Invalid UTF-8 is rejected by shared plain JSON loading");
        File.WriteAllText(path, contents);
        check(resources.ReadOnlyRelative("shared.json") is EvidenceObject && row.Get("A") is EvidenceInteger { Value: var old } && old == 9007199254740993L,
            "Catalog recovery creates a valid new view and leaves previous evidence intact");
        File.Delete(path);
        check(resources.ReadOnlyRelative("shared.json") is null, "A deleted plain resource cannot survive through the cache");
    }
}
