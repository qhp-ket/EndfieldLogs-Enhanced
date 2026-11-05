using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Runtime.History;

internal static class BuffDisplaySpecs
{
    public static void Run(Action<bool, string> check)
    {
        static EvidenceObject Row(string json) => (EvidenceObject)EvidenceJson.Parse(json);
        var old = Row("""{"event_key":"buff_a","source_actor_id":"1","ts_ms_from_start":0,"duration_ms":1000,"buff_uid":"a","stacking_type":"Refresh"}""");
        var refresh = Row("""{"event_key":"buff_a","source_actor_id":"1","ts_ms_from_start":100,"duration_ms":100,"buff_uid":"b","stacking_type":"Refresh"}""");
        var before = PythonSortedJson.Serialize(old); var episodes = BuffDisplay.Build([old, refresh]);
        check(episodes.Count == 1 && episodes[0].End == 200 && episodes[0].States.Count == 2, "A shorter refresh replaces old expiry permanently; old windows do not revive");
        var disabled = Row("""{"event_key":"buff_a","ts_ms_from_start":0,"duration_ms":1000,"buff_uid":"a","stacking_type":"Stack","buff_enable_observations":[{"at_ms":100,"enabled":false},{"at_ms":200,"enabled":true}]}""");
        var split = BuffDisplay.Build([disabled]);
        check(split.Count == 2 && split[0].End == 100 && split[1].Start == 200 && split[0].Key == split[1].Key, "A disabled interval remains a real gap within the same exact track");
        var first = Row("""{"event_key":"buff_a","ts_ms_from_start":0,"duration_ms":100,"buff_uid":"a","buff_uid_aliases":["b"],"stacking_type":"Stack"}""");
        var second = Row("""{"event_key":"buff_a","ts_ms_from_start":10,"duration_ms":100,"buff_uid":"b","stacking_type":"Stack"}""");
        check(BuffDisplay.Build([first, second]).Single().States.All(state => state.Stacks == 1), "Aliased packet UIDs never invent layers");
        var unknown = Row("""{"event_key":"buff_a","ts_ms_from_start":0,"duration_ms":100,"stacking_type":"Stack","buff_lifetime":{}}""");
        var unproven = BuffDisplay.Build([unknown]).Single();
        check(unproven.States[0].Boundary && BuffDisplay.StateText(unproven.States, 50).Contains("持续时间未知", StringComparison.Ordinal)
            && BuffDisplay.StateText(unproven.States, 100) == "未生效", "Observation boundaries retain unknown lifetime and half-open intervals");
        check(BuffDisplay.Name(Row("""{"event_key":"buff_a","event_name":"增伤","source_character_name":"甲"}""")) == "甲 · 增伤"
            && BuffDisplay.Name(Row("""{"event_key":"buff_a","buff_name":"internal_code_name"}""")) == "未知来源", "Generic effects use recorded source; code names are never invented localized names");
        check(before == PythonSortedJson.Serialize(old) && ReferenceEquals(episodes[0].Evidence[0], old), "Display construction preserves original evidence and coordinates");
        var directory = Directory.CreateTempSubdirectory("endfield-buff-labels-");
        try
        {
            var path = Path.Combine(directory.FullName, "data", "akedata", "buff"); Directory.CreateDirectory(path);
            File.WriteAllText(Path.Combine(path, "manifest.json"), """[{"id":"buff_a","name":"本地效果"},{"id":"buff_code","name":"code_name"}]""", new System.Text.UTF8Encoding(true));
            var names = BuffDisplay.Names(new ResourceFiles(directory.FullName));
            check(names.Count == 1 && names["buff_a"] == "本地效果", "UTF-8 BOM manifests retain human names while rejecting code identifiers");
        }
        finally { directory.Delete(true); }
    }
}
