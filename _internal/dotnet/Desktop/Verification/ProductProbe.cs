using System.Diagnostics;
using System.ComponentModel;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Data;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Presentation;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.History;
using EndfieldLogs.Runtime.Input;
using EndfieldLogs.Runtime.Services;
using EndfieldLogs.Runtime.Vision;

namespace EndfieldLogs.Desktop.Verification;

/// <summary>Actual WPF dispatcher and report pipeline, replacing only hardware-dependent independent services.</summary>
internal static partial class ProductProbe
{
    private sealed class Recorder : IInputRecordingService
    {
        public bool Running { get; private set; }
        public bool Disposed { get; private set; }
        public TaskCompletionSource? DisposeGate { get; init; }
        public EvidenceObject Status => (EvidenceObject)EvidenceJson.Parse(Running ? "{\"status\":\"recording\",\"count\":0}" : "{\"status\":\"stopped\",\"count\":0}");
        public Task StartAsync(InputRecordingOptions options, bool elevate = true, CancellationToken token = default) { Running = true; return Task.CompletedTask; }
        public Task SetTraceAsync(string? trace, CancellationToken token = default) => Task.CompletedTask;
        public Task StopAsync() { Running = false; return Task.CompletedTask; }
        public async ValueTask DisposeAsync()
        { if (DisposeGate is not null) await DisposeGate.Task.ConfigureAwait(false); Running = false; Disposed = true; }
    }
    private sealed class Capture : IVisionCaptureBackend
    {
        public VisionTargets Discover(string executable) => new([], null);
        public void SetTarget(long? window) { }
        public VisionCaptureFrame? AcquireLatest() => null;
        public void Dispose() { }
    }
    private static async Task Until(Func<bool> condition)
    { var watch = Stopwatch.StartNew(); while (!condition()) { if (watch.Elapsed.TotalSeconds > 15) throw new TimeoutException("WPF product operation timed out"); await Task.Delay(20); } }
    private static T[] Descendants<T>(DependencyObject root) where T : DependencyObject
    {
        List<T> result = []; if (root is T match) result.Add(match);
        for (var index = 0; index < VisualTreeHelper.GetChildrenCount(root); index++) result.AddRange(Descendants<T>(VisualTreeHelper.GetChild(root, index)));
        return result.ToArray();
    }
    private static void Screenshot(Window window, string path)
    {
        var bitmap = new RenderTargetBitmap((int)Math.Ceiling(window.ActualWidth), (int)Math.Ceiling(window.ActualHeight), 96, 96, PixelFormats.Pbgra32);
        bitmap.Render(window); PngBitmapEncoder png = new(); png.Frames.Add(BitmapFrame.Create(bitmap)); using var stream = File.Create(path); png.Save(stream);
    }
    internal static int Run(string output)
    {
        output = Path.GetFullPath(output); Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        var temporary = Directory.CreateTempSubdirectory("endfield-wpf-product-");
        Application application = new() { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        SettingsContext context = new(temporary.FullName); SettingsCodec codec = new(context);
        var portraitDirectory = Path.Combine(temporary.FullName, "_internal", "data", "ui", "characters"); Directory.CreateDirectory(portraitDirectory);
        byte[] portraitPixels = new byte[16 * 16 * 4]; for (var pixel = 0; pixel < portraitPixels.Length; pixel += 4) { portraitPixels[pixel] = 170; portraitPixels[pixel + 1] = 100; portraitPixels[pixel + 3] = 255; }
        PngBitmapEncoder portraitEncoder = new(); portraitEncoder.Frames.Add(BitmapFrame.Create(BitmapSource.Create(16, 16, 96, 96, PixelFormats.Bgra32, null, portraitPixels, 64)));
        using (var imageFile = File.Create(Path.Combine(portraitDirectory, "portrait.png"))) portraitEncoder.Save(imageFile);
        File.WriteAllText(Path.Combine(portraitDirectory, "manifest.json"), """{"portraits":{"chr_0001_test":{"path":"portrait.png"}},"aliases":{}}""");
        var config = codec.Decode((EvidenceObject)EvidenceJson.Parse("{}")) with { CheckUpdatesOnStart = false };
        SettingsStore settings = new(config, codec); Recorder recorder = new();
        MainWindow window = new(settings, new ResourceFiles(Path.Combine(temporary.FullName, "internal")), independentFactory: (store, streams, diagnostic) =>
            new IndependentServiceController(recorder, new(() => new Capture(), "missing-game.exe"), streams, store, temporary.FullName, diagnostic));
        Dictionary<string, object?> result = []; int code = 1;
        void Check(string name, bool passed) { result[name] = passed; if (!passed) throw new InvalidOperationException(name); }
        window.Loaded += async (_, _) =>
        {
            try
            {
                VerifyHistoryInteractions(Check);
                VerifyNavigation(Check);
                VerifyImages(temporary.FullName, Check);
                await Until(() => !window.History.Busy); window.Poll();
                Check("normal_main_window_visible", window.IsVisible && window.ActualWidth >= 780 && window.ActualHeight >= 500);
                var installRoot = ProductApplication.ResolveRoot();
                var previousDirectory = Environment.CurrentDirectory;
                try
                {
                    Environment.CurrentDirectory = temporary.FullName;
                    Check("root_independent_of_cwd", ProductApplication.ResolveRoot() == installRoot
                        && File.Exists(Path.Combine(installRoot, "_internal", "data", "resource-manifest.json"))
                        && ProductApplication.ResolveRoot(temporary.FullName) == temporary.FullName);
                }
                finally { Environment.CurrentDirectory = previousDirectory; }
                var source = Path.Combine(temporary.FullName, "trace_20261029.log");
                const string first = "[00:00:01.100] HP_V2 #1 src=chr_0001_test atk=chr_0001_test tgt=eny_0001_test skill=chr_0001_test_normal_skill hit=100";
                string Context(string time) => $"[{time}] LOADOUT reason=squad\n[{time}] LOADOUT slot=0 char=chr_0001_test\n";
                File.WriteAllText(source, Context("00:00:00.000") + first.Replace("hit=100", "hit=80", StringComparison.Ordinal) + "\n"
                    + first.Replace("00:00:01.100", "00:00:01.500", StringComparison.Ordinal).Replace("hit=100", "hit=20", StringComparison.Ordinal) + "\n"
                    + Context("00:01:00.000") + first.Replace("00:00:01.100", "00:01:01.100", StringComparison.Ordinal).Replace("hit=100", "hit=150", StringComparison.Ordinal) + "\n"
                    + first.Replace("00:00:01.100", "00:01:01.500", StringComparison.Ordinal).Replace("hit=100", "hit=50", StringComparison.Ordinal) + "\n", new UTF8Encoding(false));
                var original = File.ReadAllBytes(source);
                await window.History.ImportFilesAsync([source]); window.Poll();
                Check("history_import_indexes_two_battles", window.History.Records.Count == 2 && window.History.Records.All(row => !row.AnalysisLoaded));
                var records = window.History.Records.OrderBy(row => row.StartedAtMs).ToArray();
                window.History.Select(records.Select(row => row.Key), records[^1].Key);
                await window.History.LoadAsync(window.History.SelectedRecords.Select(row => row.Key), openDetails: true); window.Poll();
                Check("batch_last_selected_report_displayed", window.History.DisplayedKey == records[^1].Key
                    && EvidenceView.Number((window.Summary.Snapshot?.Get("battle") as EvidenceObject)?.Get("total_damage")) == 200);
                Check("home_keeps_summary_without_detail_evidence", window.Summary.Snapshot!.Get("timeline_events") is EvidenceNull
                    && window.History.ReadSnapshot()!.Get("timeline_events") is EvidenceArray);
                var analysis = application.Windows.OfType<BattleAnalysisWindow>().Single(); analysis.UpdateLayout();
                Check("analysis_uses_actual_timeline_evidence", analysis.Timeline.Marks.Any(mark => mark.Lane == "命中" && mark.Evidence.Count > 0));
                Check("damage_curve_defaults_rdmg", analysis.Plot.Series.Metric == "rdmg");
                Check("analysis_header_preserves_duration", analysis.SummaryHeader.Text.EndsWith("0.40 秒", StringComparison.CurrentCulture));
                var originalPositions = analysis.Timeline.Marks.Select(mark => (mark.Start, mark.End)).ToArray();
                analysis.Timeline.Configure("", false, 2, 1.5, true); analysis.UpdateLayout();
                Check("zoom_units_keep_evidence_coordinates", originalPositions.SequenceEqual(analysis.Timeline.Marks.Select(mark => (mark.Start, mark.End))));
                Check("role_settings_drawn_in_character_cell", analysis.Timeline.SettingsAreas.Count == 1 && analysis.Timeline.SettingsAreas[0].Owner == "chr_0001_test");
                var owner = "chr_0001_test";
                var trackOptions = analysis.Timeline.SkillOptions(owner);
                Check("role_options_only_evidenced_skills", trackOptions.Count == 1 && trackOptions[0].Category == "战技" && analysis.Timeline.VisibleRows.SequenceEqual([(owner, "战技")]));
                var oldTracks = settings.Current.BattleLaneConfigs;
                _ = analysis.Dispatcher.BeginInvoke(new Action(() =>
                {
                    var dialog = application.Windows.OfType<RoleLanesWindow>().Single();
                    Descendants<Button>(dialog).Single(button => Equals(button.Content, "添加轨道")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                    Descendants<TextBox>(dialog).Single().Text = "自选技能";
                    Descendants<CheckBox>(dialog).Single().IsChecked = true;
                    Descendants<Button>(dialog).Single(button => Equals(button.Content, "上移")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                    Descendants<Button>(dialog).Single(button => Equals(button.Content, "保存")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                }));
                analysis.EditRoleLanes(owner); analysis.UpdateLayout();
                Check("role_dialog_assign_reorder_and_persist", EvidenceJson.PythonEquals(codec.Load().BattleLaneConfigs, settings.Current.BattleLaneConfigs)
                    && analysis.Timeline.RoleLanes(owner)[0].Name == "自选技能" && analysis.Timeline.RoleLanes(owner)[0].Skills.SequenceEqual([trackOptions[0].Key])
                    && analysis.Timeline.VisibleRows.Count == 1);
                var custom = (EvidenceObject)EvidenceJson.Parse("""{"chr_0001_test":[]}""");
                analysis.Timeline.SetLaneConfigs(custom); analysis.UpdateLayout();
                Check("unassigned_skill_uses_other_track", analysis.Timeline.VisibleRows.SequenceEqual([(owner, "其他")])
                    && originalPositions.SequenceEqual(analysis.Timeline.Marks.Select(mark => (mark.Start, mark.End))));
                var beforeExpansion = analysis.Timeline.VisibleRows.Count; analysis.Timeline.ToggleLane(owner, "其他"); analysis.UpdateLayout();
                Check("expansion_keeps_input_role_identity", analysis.Timeline.VisibleRows.Count >= beforeExpansion && analysis.Timeline.VisibleRows.All(row => row.Owner == owner));
                settings.Update(current => current with { BattleLaneConfigs = oldTracks }); analysis.Timeline.SetLaneConfigs(oldTracks); analysis.UpdateLayout();
                var observedFields = window.History.ReadSnapshot()!.Fields.ToDictionary();
                observedFields["atb_events"] = EvidenceJson.Parse("""[{"character_key":"chr_0001_test","ts_ms_from_start":100,"value":80,"recovery_speed":8},{"character_key":"chr_0001_test","ts_ms_from_start":250,"value":100}]""");
                var example = EvidenceView.Rows(observedFields["timeline_events"]).First(row => EvidenceView.Text(row.Get("event_type")) == "damage");
                EvidenceObject EnemyHit(string actor, int time, int poise, bool conflict)
                {
                    var values = example.Fields.ToDictionary(); values["target_character_key"] = new EvidenceText("foe"); values["target_actor_id"] = new EvidenceText(actor);
                    values["ts_ms_from_start"] = new EvidenceInteger(time); values["target_character_name"] = new EvidenceText("测试目标");
                    values["poise_damage"] = EvidenceJson.Parse($$"""{"current_value":{{poise}},"value":5,"source":"synthetic","source_int":1,"orig_source_int":1}""");
                    values["packet_attr_conflict"] = new EvidenceBoolean(conflict); values["damage_element"] = new EvidenceText("physical");
                    values["packet_attr_details"] = EvidenceJson.Parse("""{"defender":["94:15,15"]}""");
                    values["target_entity"] = EvidenceJson.Parse("""{"target_stats_snapshot_ts_ms":100,"target_stats_snapshot_line_no":2,"target_defense":50,"target_resistance_points":{"physical":10},"target_resistance_points_source":"ENTITY_STATS"}""");
                    values["value"] = new EvidenceInteger(time == 300 ? 10 : actor == "1" ? 90 : 2);
                    values["rdps_contributions"] = EvidenceJson.Parse("""[{"character_key":"support","character_name":"辅助","value":5}]""");
                    return new(values);
                }
                var buffs = ((EvidenceArray)EvidenceJson.Parse("""
                    [{"event_type":"buff","lane_type":"buff","event_key":"buff_test","buff_name":"观测增益","source_character_key":"chr_0001_test","source_actor_id":"1","target_character_key":"chr_0001_test","target_actor_id":"2","ts_ms_from_start":20,"duration_ms":180,"buff_uid":"a","stacking_type":"Stack","buff_lifetime":{"expiry_ms_from_start":200}},
                    {"event_type":"buff","lane_type":"buff","event_key":"buff_test","buff_name":"观测增益","source_character_key":"chr_0001_test","source_actor_id":"1","target_character_key":"chr_0001_test","target_actor_id":"2","ts_ms_from_start":60,"duration_ms":160,"buff_uid":"b","stacking_type":"Stack","buff_lifetime":{"expiry_ms_from_start":220}},
                    {"event_type":"buff","lane_type":"buff","event_key":"buff_test","buff_name":"观测增益","source_character_key":"chr_0001_test","source_actor_id":"another","target_character_key":"chr_0001_test","target_actor_id":"2","ts_ms_from_start":25,"duration_ms":100,"buff_uid":"a","stacking_type":"Refresh","buff_lifetime":{}}]
                    """)).Items;
                observedFields["timeline_events"] = new EvidenceArray([EnemyHit("1", 100, 80, false), EnemyHit("2", 100, 80, true), EnemyHit("1", 300, 0, false), .. buffs]);
                var observedBefore = PythonSortedJson.Serialize(new EvidenceObject(observedFields));
                BattleAnalysisWindow observed = new(new EvidenceObject(observedFields), settings) { Owner = window }; observed.Show(); observed.UpdateLayout();
                var buffToggle = Descendants<CheckBox>(observed).Single(box => Equals(box.Content, "BUFF"));
                Check("buff_tracks_default_hidden", buffToggle.IsChecked == false && observed.Timeline.VisibleRows.All(row => !row.Lane.StartsWith("buff:", StringComparison.Ordinal)));
                buffToggle.IsChecked = true;
                await observed.Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.ContextIdle); observed.UpdateLayout();
                Check("buff_tracks_keep_actor_identity_and_merge_windows", observed.Timeline.Marks.Count(mark => mark.Buff is not null) == 2
                    && observed.Timeline.VisibleRows.Count(row => row.Lane.StartsWith("buff:", StringComparison.Ordinal)) == 2 && observed.Timeline.BuffChangeMarkers == 4);
                var buff = observed.Timeline.Marks.First(mark => mark.Buff is not null && mark.Buff.States.Count > 1);
                Check("buff_hover_keeps_source_layers_and_expiry", BattleDetails.Description(buff, false).Contains("峰值 2 层", StringComparison.Ordinal)
                    && BattleDetails.Description(buff, false).Contains("观测增益", StringComparison.Ordinal) && buff.Evidence.Count == 2);
                observed.Timeline.SelectMarks([buff]); observed.UpdateLayout();
                Check("selection_updates_collapsed_details_without_opening", !observed.DetailsExpanded && observed.OverviewEvidence.Contains("峰值 2 层", StringComparison.Ordinal));
                observed.SetDetails(true); observed.UpdateLayout(); var detailSize = observed.DetailsHeight;
                var splitter = Descendants<GridSplitter>(observed).Single();
                splitter.RaiseEvent(new DragStartedEventArgs(0, 0) { RoutedEvent = Thumb.DragStartedEvent });
                splitter.RaiseEvent(new DragDeltaEventArgs(0, -40) { RoutedEvent = Thumb.DragDeltaEvent });
                splitter.RaiseEvent(new DragCompletedEventArgs(0, -40, false) { RoutedEvent = Thumb.DragCompletedEvent }); observed.UpdateLayout();
                Check("detail_splitter_changes_panel_height", observed.DetailsHeight > detailSize + 30); detailSize = observed.DetailsHeight;
                observed.SetDetails(false); observed.SetDetails(true); observed.UpdateLayout();
                Check("detail_height_restores_after_collapse", Math.Abs(detailSize - observed.DetailsHeight) <= 1 && detailSize >= 100);
                observed.MaximizeDetails(true); observed.UpdateLayout(); var maximizedHeight = observed.DetailsHeight;
                observed.MaximizeDetails(false); observed.UpdateLayout();
                Check("details_maximize_and_restore", maximizedHeight > detailSize && Math.Abs(detailSize - observed.DetailsHeight) <= 1);
                observed.Timeline.SelectMarks(observed.Timeline.Marks.Where(mark => mark.Skill is not null).ToArray()); observed.UpdateLayout();
                Check("inspector_shows_canonical_splits_resistance_and_poise", observed.HitTable.Items.Count == 3 && observed.ContributionTable.Items.Count == 1
                    && observed.ContributionTable.Items[0] is ContributionShare { Value: 15, Percent: 100 }
                    && observed.HitTable.Items.OfType<BattleAnalysisWindow.HitRow>().Any(row => row.Resistance == 15 && row.Poise == 80 && row.Target.Contains("#1", StringComparison.Ordinal)));
                var sortedHits = CollectionViewSource.GetDefaultView(observed.HitTable.ItemsSource); sortedHits.SortDescriptions.Add(new(nameof(BattleAnalysisWindow.HitRow.Damage), ListSortDirection.Ascending));
                var firstHit = sortedHits.Cast<BattleAnalysisWindow.HitRow>().First(); observed.HitTable.SelectedItem = firstHit;
                Check("numeric_hit_sort_retains_original_raw_evidence", firstHit.Damage == 2 && observed.RawEvidence == PythonSortedJson.Serialize(firstHit.Evidence));
                observed.DetailsPages.SelectedIndex = 2; observed.UpdateLayout(); Screenshot(observed, Path.ChangeExtension(output, ".inspector.png"));
                var unit = Descendants<CheckBox>(observed).Single(box => Equals(box.Content, "帧（30F/s）")); unit.IsChecked = true; observed.UpdateLayout();
                Check("inspector_time_units_follow_frame_toggle", observed.HitTable.Columns[0].Header.Equals("时间／F（30F/s）")
                    && observed.HitTable.Items.OfType<BattleAnalysisWindow.HitRow>().Max(row => row.Time) == 9);
                observed.Timeline.Configure(owner, false, 1, 1, false); observed.UpdateLayout();
                Check("buff_visibility_does_not_change_report", observed.Timeline.BuffChangeMarkers == 0 && observedBefore == PythonSortedJson.Serialize(new EvidenceObject(observedFields)));
                observed.SetDetails(false); observed.Timeline.Configure(owner, true, 1, 1, false); observed.UpdateLayout();
                Check("shared_energy_control_tracks_are_drawn", observed.Timeline.EnergyRows == 4 && !observed.Timeline.EnergyArea.IsEmpty
                    && observed.Timeline.Control[0].Character.Length == 0 && observed.Timeline.Energy.Samples.Count == 2 && observed.Timeline.Energy.Capacity is null);
                var energyRect = observed.Timeline.EnergyArea;
                var unknownTip = observed.Timeline.ObservationTooltip(new(energyRect.Left + 1, energyRect.Top + 20));
                var estimatedTip = observed.Timeline.ObservationTooltip(new(energyRect.Left + energyRect.Width * .5, energyRect.Top + 20));
                Check("energy_hover_distinguishes_unknown_and_estimate", unknownTip.Contains("首次技力观测之前", StringComparison.Ordinal) && estimatedTip.Contains("估算", StringComparison.Ordinal));
                observed.Timeline.SetInputEvidence((EvidenceObject)EvidenceJson.Parse("""{"settings":{"show_other":true},"actions":[{"action":"combo","start_ms":10,"end_ms":300},{"action":"other","start_ms":20,"end_ms":200}],"raw":[{"time_ms":50,"value":10}]}""")); observed.UpdateLayout();
                var comboSpan = observed.Timeline.InputSpans.Single(span => EvidenceView.Text(span.Span.Evidence.Get("action")) == "combo");
                observed.DiagramScroll.ScrollToBottom();
                await System.Windows.Threading.Dispatcher.Yield(System.Windows.Threading.DispatcherPriority.ContextIdle);
                observed.UpdateLayout();
                var otherSpan = observed.Timeline.InputSpans.Single(span => EvidenceView.Text(span.Span.Evidence.Get("action")) == "other");
                Check("input_spans_exclude_observation_tracks", comboSpan.Bounds.Bottom <= energyRect.Top && otherSpan.Bounds.Top >= energyRect.Bottom);
                observed.DiagramScroll.ScrollToTop();
                await System.Windows.Threading.Dispatcher.Yield(System.Windows.Threading.DispatcherPriority.ContextIdle);
                var observedSamples = observed.Timeline.Energy.Samples;
                observed.Timeline.Configure(owner, true, 2, 1.5, false); observed.UpdateLayout();
                Check("role_filter_preserves_shared_energy", ReferenceEquals(observedSamples, observed.Timeline.Energy.Samples) && observed.Timeline.EnergyRows == 4);
                var ambiguous = observed.Timeline.Enemies.Tracks.Single(track => track.Key.Actor == "unbound");
                Check("poise_multi_target_evidence_remains_unbound", ambiguous.Samples.Single().Ambiguous && observed.Timeline.PoiseAreas.Count == 3
                    && observed.Timeline.Enemies.Tracks.Single(track => track.Key.Actor == "2").Samples.Count == 0);
                Check("entity_and_hit_resistance_are_separate", observed.EnemyPage.Stats.Items.Count == 3 && observed.EnemyPage.HitResistance.Items.Count == 3
                    && ((Dictionary<string, object?>)observed.EnemyPage.HitResistance.Items[0])["resistance"] is double resistance && resistance == 15
                    && ((Dictionary<string, object?>)observed.EnemyPage.HitResistance.Items[1])["resistance"] is null);
                Screenshot(observed, Path.ChangeExtension(output, ".observations.png"));
                observed.HitTable.Columns[0].Width = 173; observed.Close();
                BattleAnalysisWindow reopened = new(new EvidenceObject(observedFields), settings) { Owner = window }; reopened.Show(); reopened.UpdateLayout();
                Check("resized_table_columns_persist_in_codec", reopened.HitTable.Columns[0].Width.Value == 173 && EvidenceView.Number(((EvidenceArray)codec.Load().BattleTableWidths.Get("hits")).Items[0]) == 173);
                reopened.Close();
                var longFields = observedFields.ToDictionary(); var longBattle = ((EvidenceObject)longFields["battle"]).Fields.ToDictionary(); longBattle["duration_ms"] = new EvidenceInteger(120000); longFields["battle"] = new EvidenceObject(longBattle);
                BattleAnalysisWindow longView = new(new EvidenceObject(longFields), settings) { Owner = window }; longView.Show(); longView.UpdateLayout();
                longView.Timeline.Configure("", true, 2, 2, false); longView.UpdateLayout();
                var longCoordinates = longView.Timeline.Marks.Select(mark => (mark.Start, mark.End)).ToArray();
                longView.DiagramScroll.ScrollToHorizontalOffset(500); longView.DiagramScroll.ScrollToVerticalOffset(230); longView.UpdateLayout();
                await Until(() => longView.DiagramScroll.HorizontalOffset == 500 && longView.Timeline.PinnedLabelLeft == 500
                    && longView.Timeline.SettingsAreas.All(area => area.Bounds.X >= 500));
                Check("timeline_labels_and_ruler_follow_scrolled_viewport", longView.Timeline.StickyHeaderTop > 0
                    && longView.Timeline.SettingsAreas.All(area => area.Bounds.X >= 500));
                longView.Timeline.ResizeLabels(260); longView.UpdateLayout();
                Check("timeline_label_resize_preserves_coordinates", longView.Timeline.LabelWidth == 260 && longCoordinates.SequenceEqual(longView.Timeline.Marks.Select(mark => (mark.Start, mark.End))));
                Screenshot(longView, Path.ChangeExtension(output, ".scrolled.png"));
                Descendants<Button>(longView).Single(button => Equals(button.Content, "适合窗口")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); longView.UpdateLayout();
                await Until(() => longView.DiagramScroll.HorizontalOffset == 0 && longView.DiagramScroll.ExtentWidth <= longView.DiagramScroll.ViewportWidth + 1);
                Check("fit_window_uses_available_width_without_moving_evidence", longCoordinates.SequenceEqual(longView.Timeline.Marks.Select(mark => (mark.Start, mark.End))) && longView.Timeline.ActualWidth > 700);
                var appearance = settings.Current;
                settings.Update(current => current with { FontPercent = 160, ThemeMode = "dark", ShowCharacterAvatars = true, CharacterAvatarPercent = 150 }); longView.ApplyAppearance(); longView.UpdateLayout();
                await longView.Dispatcher.InvokeAsync(() => { }, System.Windows.Threading.DispatcherPriority.ContextIdle); longView.UpdateLayout();
                var themeButton = Descendants<Button>(longView).First();
                result["appearance_diagnostics"] = new { highContrast = SystemParameters.HighContrast, systemWindow = SystemColors.WindowColor.ToString(), windowBackground = longView.Background?.ToString(), windowForeground = longView.Foreground?.ToString(), buttonBackground = themeButton.Background?.ToString(), buttonForeground = themeButton.Foreground?.ToString(), buttonSource = DependencyPropertyHelper.GetValueSource(themeButton, Control.ForegroundProperty).BaseValueSource.ToString(), implicitStyle = themeButton.TryFindResource(typeof(Button)) is Style };
                Check("analysis_theme_background_is_opaque", longView.Background is SolidColorBrush { Color.A: 255 } background && background.Color.R < 64
                    && longView.Foreground is SolidColorBrush foreground && foreground.Color.R > 200);
                await Until(() => longView.Timeline.AvatarCount == 1);
                Check("analysis_uses_global_font_and_cached_portraits", longView.Timeline.FontScale == 1.6 && longView.FontSize == 20.8 && longCoordinates.SequenceEqual(longView.Timeline.Marks.Select(mark => (mark.Start, mark.End))));
                Screenshot(longView, Path.ChangeExtension(output, ".appearance.png"));
                System.Windows.Threading.DispatcherTimer appearanceTimer = new() { Interval = TimeSpan.FromMilliseconds(20) };
                appearanceTimer.Tick += (_, _) =>
                {
                    var dialog = application.Windows.OfType<Window>().FirstOrDefault(candidate => candidate.Title == "显示设置"); if (dialog is null) return;
                    appearanceTimer.Stop(); Descendants<CheckBox>(dialog).Single(box => Equals(box.Content, "显示角色头像")).IsChecked = false; Descendants<Slider>(dialog).Single().Value = 180;
                    Descendants<Button>(dialog).Single(button => Equals(button.Content, "保存")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                };
                appearanceTimer.Start();
                try { Descendants<Button>(longView).Single(button => Equals(button.Content, "显示设置")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); }
                finally { appearanceTimer.Stop(); }
                await Until(() => longView.Timeline.AvatarCount == 0);
                Check("display_panel_persists_avatar_visibility_and_scale", !codec.Load().ShowCharacterAvatars && codec.Load().CharacterAvatarPercent == 180);
                settings.Update(current => current with { FontPercent = appearance.FontPercent, ThemeMode = appearance.ThemeMode, ShowCharacterAvatars = appearance.ShowCharacterAvatars, CharacterAvatarPercent = appearance.CharacterAvatarPercent });
                longView.Close();
                await VerifyBattlePresentation(application, window, settings, output, Check);
                var canonical = PythonSortedJson.Serialize(window.Summary.Snapshot!);
                var inputPath = Path.ChangeExtension(source, ".input.jsonl");
                var midnight = new DateTime(2026, 10, 29); var baseNs = new DateTimeOffset(midnight, TimeZoneInfo.Local.GetUtcOffset(midnight)).ToUnixTimeMilliseconds() * 1_000_000L;
                string Event(int ms, string key, string phase, int seq) => JsonSerializer.Serialize(new { type = "input", kind = "key", wall_ns = baseNs + ms * 1_000_000L, mono_ns = ms * 1_000_000L, device = "keyboard", code = key, phase, seq });
                File.WriteAllText(inputPath, JsonSerializer.Serialize(new { type = "session", schema_version = 1, wall_ns = baseNs }) + "\n"
                    + Event(61200, "K:49", "down", 1) + "\n" + Event(61300, "K:49", "up", 2) + "\n" + Event(61350, "K:69", "down", 3) + "\n" + Event(61400, "K:69", "up", 4) + "\n"
                    + JsonSerializer.Serialize(new { type = "end", wall_ns = baseNs + 61500_000_000L }) + "\n", new UTF8Encoding(false));
                await analysis.InputPanel.BindAsync(inputPath); analysis.UpdateLayout();
                Check("input_binding_keeps_display_toggle_independent", analysis.InputPanel.State.Paths.SequenceEqual([inputPath]) && !analysis.InputPanel.State.Visible && analysis.Timeline.InputSpans.Count == 0);
                Descendants<CheckBox>(analysis).Single(box => Equals(box.Content, "显示输入")).IsChecked = true; analysis.UpdateLayout();
                analysis.Timeline.FitToWindow(analysis.DiagramScroll.ViewportWidth);
                analysis.DiagramScroll.ScrollToHome();
                await System.Windows.Threading.Dispatcher.Yield(System.Windows.Threading.DispatcherPriority.ContextIdle);
                analysis.UpdateLayout();
                Check("input_evidence_reaches_actual_role_timeline", analysis.InputPanel.State.Visible && analysis.Timeline.InputSpans.Count == 2
                    && analysis.Timeline.InputSpans.Any(span => EvidenceView.Text(span.Span.Evidence.Get("action")) == "skill" && EvidenceView.Text(span.Span.Evidence.Get("character_key")) == "chr_0001_test"));
                await analysis.InputPanel.ConfigureAsync((EvidenceObject)EvidenceJson.Parse("""{"show_other":true}""")); analysis.UpdateLayout();
                Check("combo_excludes_raw_input_track", analysis.Timeline.InputLayout.ExtraRow
                    && analysis.Timeline.InputSpans.Single(span => EvidenceView.Text(span.Span.Evidence.Get("action")) == "combo").Span.RowCount
                        == analysis.Timeline.InputLayout.Spans.Where(span => EvidenceView.Text(span.Evidence.Get("action")) == "skill").Max(span => span.FirstRow + span.RowCount)
                    && analysis.Timeline.InputLayout.Raw.Count == 4);
                Screenshot(analysis, Path.ChangeExtension(output, ".input.png"));
                var actionStart = EvidenceView.Number(EvidenceView.Rows(analysis.InputPanel.State.Evidence.Get("actions")).First().Get("start_ms"));
                await analysis.InputPanel.AlignAsync(125, null, new Dictionary<int, string>()); analysis.UpdateLayout();
                Check("input_offset_preserves_combat_report", EvidenceView.Number(EvidenceView.Rows(analysis.InputPanel.State.Evidence.Get("actions")).First().Get("start_ms")) == actionStart + 125
                    && PythonSortedJson.Serialize(window.Summary.Snapshot!) == canonical && originalPositions.SequenceEqual(analysis.Timeline.Marks.Select(mark => (mark.Start, mark.End))));
                var layoutEvidence = (EvidenceObject)EvidenceJson.Parse("""{"actions":[{"action":"combo","start_ms":-10,"end_ms":20},{"action":"skill","character_key":"b"},{"action":"skill"}],"raw":[{}]}""");
                var layout = TimelineInputs.Layout(layoutEvidence, [("a", "战技"), ("a", "连携终结"), ("b", "战技")], "");
                Check("combo_covers_all_visible_roles_only", layout.ExtraRow && layout.Spans[0].FirstRow == 0 && layout.Spans[0].RowCount == 3
                    && layout.Spans[1].FirstRow == 2 && layout.Spans[2].FirstRow == 3);
                var filteredLayout = TimelineInputs.Layout(layoutEvidence, [("a", "战技"), ("a", "连携终结")], "a");
                Check("input_character_filter_retains_unowned_evidence", filteredLayout.Spans.Count == 2 && filteredLayout.Spans[0].RowCount == 2 && filteredLayout.Spans[1].FirstRow == 2);
                InputSettingsWindow editor = new(analysis.InputPanel.State.Settings) { Owner = analysis };
                var previousRules = InputInterpretationSettings.Normalize(analysis.InputPanel.State.Settings).Bindings.Count;
                editor.Loaded += (_, _) =>
                {
                    Descendants<Button>(editor).Single(button => Equals(button.Content, "增加绑定")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                    Descendants<DataGrid>(editor).Single().Items.OfType<InputRuleRow>().Last().Keys = "K:82";
                    Descendants<Button>(editor).Single(button => Equals(button.Content, "保存")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                };
                Check("input_settings_dialog_accepts_native_rules", Ui.ShowDialog(editor) == true && InputInterpretationSettings.Normalize(editor.Value).Bindings.Count == previousRules + 1);
                await analysis.InputPanel.ConfigureAsync(editor.Value);
                Check("input_settings_persist_shared_configuration", EvidenceJson.PythonEquals(codec.Load().InputSettings, editor.Value));
                InputAlignmentWindow alignment = new(window.Summary.Snapshot!, analysis.InputPanel.State) { Owner = analysis };
                alignment.Loaded += (_, _) =>
                {
                    Descendants<TextBox>(alignment)[1].Text = "250.5";
                    Descendants<ComboBox>(alignment)[0].SelectedValue = "chr_0001_test";
                    Descendants<Button>(alignment).Single(button => Equals(button.Content, "应用")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                };
                Check("alignment_dialog_preserves_auto_anchor", Ui.ShowDialog(alignment) == true && alignment.OffsetMs == 250.5 && alignment.StartOverride is null && alignment.ManualSlots[0] == "chr_0001_test");
                await analysis.InputPanel.AlignAsync(alignment.OffsetMs, alignment.StartOverride, alignment.ManualSlots);
                Check("alignment_dialog_values_reach_binding", analysis.InputPanel.State.OffsetMs == 250.5 && analysis.InputPanel.State.ManualSlots[0] == "chr_0001_test" && analysis.InputPanel.State.Visible);
                await VerifyAppearance(application, window, analysis, settings, output, Check);
                OverlayProductProbe.VerifyAppearance(temporary.FullName, output, Check);

                window.Navigation.Select(MainPage.History); window.UpdateLayout();
                System.Windows.Threading.DispatcherTimer renameTimer = new() { Interval = TimeSpan.FromMilliseconds(20) };
                renameTimer.Tick += (_, _) =>
                {
                    var rename = application.Windows.OfType<Window>().FirstOrDefault(candidate => candidate.Title == "重命名日志");
                    if (rename is null) return; renameTimer.Stop();
                    Descendants<TextBox>(rename).Single().Text = "输入联动";
                    Descendants<Button>(rename).Single(button => Equals(button.Content, "确定")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                };
                renameTimer.Start();
                try { Descendants<Button>(window).Single(button => Equals(button.Content, "重命名文件…")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); }
                finally { renameTimer.Stop(); }
                await Until(() => analysis.InputPanel.State.TracePath != source && !analysis.InputPanel.State.Pending);
                source = analysis.InputPanel.State.TracePath!; inputPath = Path.ChangeExtension(source, ".input.jsonl");
                records = window.History.Records.OrderBy(row => row.StartedAtMs).ToArray();
                Check("history_rename_rebinds_open_analysis", analysis.InputPanel.State.Paths.SequenceEqual([inputPath]) && File.Exists(inputPath) && File.ReadAllBytes(source).SequenceEqual(original));
                Check("history_rename_updates_current_summary", EvidenceView.Text((window.Summary.Snapshot?.Get("battle") as EvidenceObject)?.Get("source_file_name")) == Path.GetFileName(source));
                var inputMenu = Descendants<Button>(analysis).Single(button => Equals(button.Content, "输入 ▾")); inputMenu.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                inputMenu.ContextMenu!.Items.OfType<MenuItem>().Single(item => Equals(item.Header, "解除绑定")).RaiseEvent(new RoutedEventArgs(MenuItem.ClickEvent)); inputMenu.ContextMenu.IsOpen = false;
                await Until(() => analysis.InputPanel.State.Paths.Count == 0); analysis.UpdateLayout();
                Check("input_menu_unbind_clears_persisted_source", analysis.Timeline.InputSpans.Count == 0 && settings.Current.InputLogBindings.Fields.ContainsKey(records[^1].Key));
                Screenshot(analysis, Path.ChangeExtension(output, ".png"));
                window.Navigation.Select(MainPage.Settings); window.UpdateLayout();
                Descendants<Button>(window).Single(button => Equals(button.Content, "保存设置")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                Check("settings_save_uses_portable_codec", File.Exists(context.DefaultPath) && codec.Load().Service.LogDirectory == settings.Current.Service.LogDirectory);
                window.Navigation.Select(MainPage.Home); window.UpdateLayout();
                await VerifyVisionSettings(application, window, settings, output, Check);
                Descendants<Button>(window).Single(button => Equals(button.Content, "开始记录输入")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                await Until(() => recorder.Running); window.Poll(); Check("input_button_starts_independent_service", recorder.Running);
                var pending = window.History.LoadAsync([records[0].Key]); window.ReturnLive(); await pending; window.Poll();
                Check("return_live_rejects_late_history", window.History.DisplayedKey is null && window.Summary.Snapshot is null);
                Check("source_bytes_preserved", File.ReadAllBytes(source).SequenceEqual(original));
                await VerifyShell(window, analysis, settings, recorder, Check);
                result["shell_diagnostics"] = new { trayRegistered = window.Shell?.TrayAvailable, hotkeys = window.Shell?.HotkeyCount };
                window.Close(); await Until(() => window.ServicesDisposed && !window.IsVisible);
                Check("window_close_awaits_service_cleanup", recorder.Disposed && !recorder.Running && !window.IsVisible && !analysis.IsVisible);
                Check("window_close_removes_tray_and_hotkeys", window.Shell is { TrayAvailable: false, HotkeyCount: 0 });
                TaskCompletionSource cleanup = new(TaskCreationOptions.RunContinuationsAsynchronously); Recorder delayed = new() { DisposeGate = cleanup };
                MainWindow second = new(settings, new ResourceFiles(Path.Combine(temporary.FullName, "internal")), independentFactory: (store, streams, diagnostic) =>
                    new IndependentServiceController(delayed, new(() => new Capture(), "missing-game.exe"), streams, store, temporary.FullName, diagnostic));
                try
                {
                    second.Show(); second.Close(); await Task.Delay(40);
                    Check("async_cleanup_defers_actual_window_close", second.IsVisible && !second.ServicesDisposed && !second.IsEnabled);
                }
                finally { cleanup.TrySetResult(); await Until(() => second.ServicesDisposed && !second.IsVisible); }
                Check("async_cleanup_finishes_before_close", delayed.Disposed);
                Check("browser_not_loaded", !Process.GetCurrentProcess().Modules.Cast<ProcessModule>().Any(module => module.ModuleName.Contains("WebView", StringComparison.OrdinalIgnoreCase) || module.ModuleName.Contains("WebEngine", StringComparison.OrdinalIgnoreCase)));
                code = 0;
            }
            catch (Exception error) { result["error"] = error.ToString(); }
            finally
            {
                if (window.IsVisible) { window.Close(); await Until(() => window.ServicesDisposed && !window.IsVisible); }
                result["passed"] = code == 0; File.WriteAllText(output, JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true })); application.Shutdown(code);
            }
        };
        try { window.Show(); return application.Run(); }
        finally { temporary.Delete(true); }
    }
}
