using System.IO.Compression;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;

internal static class MingheResourceSpecs
{
    public static void Run(Action<bool, string> check)
    {
        var root = new DirectoryInfo(AppContext.BaseDirectory);
        while (root is not null && !File.Exists(Path.Combine(root.FullName, "_internal/data/runtime-data.zip"))) root = root.Parent;
        if (root is null) throw new FileNotFoundException("缺少源码离线资源包");
        var temporary = Path.Combine(Path.GetTempPath(), "endfield-minghe-" + Guid.NewGuid().ToString("N"));
        const string character = "chr_0037_minghe";
        try
        {
            ZipFile.ExtractToDirectory(Path.Combine(root.FullName, "_internal/data/runtime-data.zip"), temporary);
            ResourceFiles files = new(temporary);
            CharacterResourceCatalog characters = new(files);
            var identity = new SkillResourceCatalog(files).CreateIdentityCatalog();
            DisplayNameCatalog names = new(files, characters, identity);
            SkillProfileCatalog profiles = new(files, characters, identity);
            check(characters.Name(character) == "明河" && TimelineSkills.CharacterName(character) == "明河",
                "The restored runtime bundle and embedded native view both name Minghe");
            foreach (var (suffix, name, category, group) in new[] {
                ("attack1", "曜尘", "普攻", 0), ("normalskill_1", "镇影", "战技", 1),
                ("normalskill_2", "奔霆", "战技", 1), ("combo_skill", "星移", "连携", 3),
                ("ultimate_skill", "裂天", "大招", 2) })
            {
                var key = character + "_" + suffix; var label = TimelineSkills.Label(key);
                check(names.Skill(key) == name && label.Name.StartsWith(name, StringComparison.Ordinal)
                    && label.Category == category && profiles.ForHit(key)?.Group == group,
                    "Restored skill identity and native timeline agree: " + suffix);
            }
            check(names.Skill("skill_3680") == "镇影" && names.Skill("skill_3681") == "奔霆",
                "Existing numeric IDs resolve both normal skill variants");
            var attributes = new CharacterBaseStatCatalog(files).Get(character, 1);
            check(attributes?.Get("atk") is EvidenceReal { Value: 30 }
                && new CharacterBaseStatCatalog(files).Get(character, 90) is not null,
                "The restored bundle includes Minghe's exact level attributes");
            var item = characters.Items.Single(row => row.Get("charId") is EvidenceText { Value: character });
            check(item.Get("potentials") is EvidenceArray { Items.Count: 5 }, "Five potential definitions survive offline restoration");
        }
        finally { if (Directory.Exists(temporary)) Directory.Delete(temporary, true); }
    }
}
