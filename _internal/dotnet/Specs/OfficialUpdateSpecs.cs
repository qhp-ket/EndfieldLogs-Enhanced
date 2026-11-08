using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Protocol;
using Google.Protobuf;

internal static class OfficialUpdateSpecs
{
    public static void Run(Action<bool, string> check)
    {
        foreach (var name in new[] { "SC_ATTACH_SERVER_SKILL", "SC_UPDATE_SERVER_SKILL", "SC_DETACH_SERVER_SKILL" })
        {
            var body = name == "SC_DETACH_SERVER_SKILL"
                ? """{"inst_id":"18446744073709551615","generation":7,"del_inst_ids":["42"]}"""
                : """{"inst_id":"18446744073709551615","generation":7,"skills":[{"inst_id":"42"}]}""";
            var message = JsonParser.Default.Parse(body, ProtocolCatalog.Messages[name]);
            check(ProtocolCatalog.Parse(name, message.ToByteArray()).Equals(message), "New official skill wrapper round trips: " + name);
        }
        var folder = Directory.CreateTempSubdirectory("endfield-contract-text-");
        try
        {
            Directory.CreateDirectory(Path.Combine(folder.FullName, "data/public"));
            Directory.CreateDirectory(Path.Combine(folder.FullName, "data/local_tables"));
            File.WriteAllText(Path.Combine(folder.FullName, "data/local_tables/I18nTextTable_CN.json"), """{"1":"旧名称","2":"模板 {value}"}""");
            var server = Path.Combine(folder.FullName, "data/public/server_texts.json");
            File.WriteAllText(server, """{"source":"SC_SYNC_MULTI_LANG_CONFIG","language":"CN","texts":{"1":"新词条"}}""");
            File.WriteAllText(Path.Combine(folder.FullName, "data/public/contract_tags.json"), """{"tags":{"9":{"tagId":9,"nameTextId":1,"descTextId":2,"romanNumSuffix":"Ⅱ","descriptionTemplate":"模板 {value}","formattedDescription":"模板 30%"}}}""");
            var item = new ContractTagCatalog(new(folder.FullName)).Payload(9);
            check(item.Get("name") is EvidenceText { Value: "新词条Ⅱ" } && item.Get("description") is EvidenceText { Value: "模板 30%" }, "Chinese server text, roman suffix and formatted descriptions reach the report");
            File.WriteAllText(server, """{"source":"SC_SYNC_MULTI_LANG_CONFIG","language":"EN","texts":{"1":"foreign"}}""");
            check(new ContractTagCatalog(new(folder.FullName)).Payload(9).Get("name") is EvidenceText { Value: "旧名称Ⅱ" }, "Foreign server text never replaces the Chinese table");
        }
        finally { folder.Delete(recursive: true); }
    }
}
