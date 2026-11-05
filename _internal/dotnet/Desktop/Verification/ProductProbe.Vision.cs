using System.Diagnostics;
using System.IO;
using System.Numerics;
using System.Windows;
using System.Windows.Controls;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Presentation;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Input;
using EndfieldLogs.Runtime.Services;
using EndfieldLogs.Runtime.Vision;

namespace EndfieldLogs.Desktop.Verification;

internal static partial class ProductProbe
{
    private sealed class CalibrationCapture : IVisionCaptureBackend
    {
        private long window, sequence;
        public volatile bool Disposed;
        public int Released;
        public VisionTargets Discover(string executable) => new([123, 456], 123);
        public void SetTarget(long? value) => Interlocked.Exchange(ref window, value ?? 0);
        public VisionCaptureFrame? AcquireLatest()
        {
            var selected = Interlocked.Read(ref window); if (selected == 0) return null;
            const int width = 512, height = 288; byte[] pixels = new byte[width * height * 4]; Array.Fill(pixels, (byte)30);
            foreach (var row in VisionLayout.Presets()[0].Regions)
            {
                void Fill(HudRegion rect, byte b, byte g, byte r)
                {
                    var left = (int)Math.Round(rect.X * width); var top = (int)Math.Round(rect.Y * height);
                    for (var y = top; y < Math.Max(top + 1, (int)Math.Round((rect.Y + rect.Height) * height)); y++)
                        for (var x = left; x < Math.Max(left + 1, (int)Math.Round((rect.X + rect.Width) * width)); x++)
                        { var offset = (y * width + x) * 4; pixels[offset] = b; pixels[offset + 1] = g; pixels[offset + 2] = r; pixels[offset + 3] = 255; }
                }
                Fill(row.Energy, 235, 235, 235); Fill(row.Hp, 30, 150, 210); Fill(row.Portrait, 40, 40, 40);
            }
            return new(new(pixels, width, height, width * 4), new(0, 0, width, height), Interlocked.Increment(ref sequence),
                Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency, selected, () => Interlocked.Increment(ref Released));
        }
        public void Dispose() => Disposed = true;
    }
    private static async Task VerifyVisionSettings(Application application, MainWindow owner, SettingsStore mainSettings, string output, Action<string, bool> check)
    {
        void OpenModal<T>(string button, Action<T> inspect) where T : Window
        {
            Exception? failure = null;
            _ = owner.Dispatcher.BeginInvoke(new Action(() =>
            {
                var dialog = application.Windows.OfType<T>().Single();
                try { inspect(dialog); }
                catch (Exception error) { failure = error; dialog.Close(); }
            }));
            Descendants<Button>(owner).Single(value => value.IsVisible && Equals(value.Content, button)).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            if (failure is not null) throw failure;
        }
        var oldInput = mainSettings.Current.InputSettings;
        OpenModal<InputSettingsWindow>("输入记录设置", dialog =>
        {
            check("home_input_settings_opens_native_editor", dialog.IsVisible && dialog.Owner == owner);
            Descendants<TextBox>(dialog).Single().Text = "410";
            Descendants<Button>(dialog).Single(value => Equals(value.Content, "保存")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        });
        check("home_input_settings_saves_existing_configuration", InputInterpretationSettings.Normalize(mainSettings.Current.InputSettings).HoldMs == 410);
        mainSettings.Update(current => current with { InputSettings = oldInput });
        owner.Navigation.Select(MainPage.Overlays); owner.UpdateLayout();
        OpenModal<VisionSettingsWindow>("连携识别设置", dialog =>
        {
            check("home_vision_settings_opens_calibration", dialog.IsVisible && dialog.Owner == owner);
            Descendants<Button>(dialog).Single(value => Equals(value.Content, "取消")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
        });
        owner.Navigation.Select(MainPage.Home); owner.UpdateLayout();

        var temporary = Directory.CreateTempSubdirectory("endfield-vision-settings-");
        SettingsCodec codec = new(new(temporary.FullName));
        SettingsStore settings = new(codec.Decode((EvidenceObject)EvidenceJson.Parse("{}")), codec);
        var original = settings.Current.VisionSettings; CalibrationCapture capture = new(); Recorder recorder = new();
        VisionService vision = new(() => capture, "synthetic-game.exe", original);
        IndependentServiceController controller = new(recorder, vision, _ => { }, settings, temporary.FullName);
        try
        {
            // A combo consumer retains recognition after the calibration window closes.
            controller.SetRequirements(["combo_snapshot"]);
            await Until(() => vision.State.Get("frame_valid") is EvidenceBoolean { Value: true });
            bool? Inspect(VisionSettingsWindow dialog, Func<Task> inspect)
            {
                Exception? failure = null;
                dialog.Loaded += async (_, _) =>
                {
                    try { await inspect(); }
                    catch (Exception error) { failure = error; }
                    finally { if (dialog.IsVisible) dialog.DialogResult = false; }
                };
                var accepted = dialog.ShowDialog(); if (failure is not null) throw failure; return accepted;
            }
            VisionSettingsWindow first = new(controller, settings) { Owner = owner };
            var accepted = Inspect(first, async () =>
            {
                await Until(() => { first.Refresh(); return first.Preview.Image is not null; }); first.UpdateLayout();
                check("vision_preview_contains_owned_cropped_frame", first.Preview.TargetWindow == 123 && first.Preview.Image is { PixelWidth: 960, PixelHeight: 540 });
                var sameBitmap = first.Preview.Image; await Task.Delay(300);
                await Until(() => { first.Refresh(); return capture.Released >= 5; });
                check("vision_preview_reuses_bitmap_for_same_dimensions", ReferenceEquals(sameBitmap, first.Preview.Image));
                var wide = VisionPreviewCanvas.Fit(new(960, 540), new(1000, 1000));
                check("vision_preview_letterbox_preserves_aspect", Math.Abs(wide.X) < 1e-9 && Math.Abs(wide.Y - 218.75) < 1e-9
                    && Math.Abs(wide.Width - 1000) < 1e-9 && Math.Abs(wide.Height - 562.5) < 1e-9);
                var area = first.Preview.ImageRect;
                check("vision_preview_rejects_letterbox_drag", !first.Preview.BeginSelection(new(-2, -2)));
                // Reverse drag and clipping use the same handlers as actual mouse input.
                check("vision_preview_accepts_image_drag", first.Preview.BeginSelection(new(area.X + area.Width * .4, area.Y + area.Height * .3)));
                first.Preview.FinishSelection(new(area.X - 50, area.Y + area.Height * .1));
                var configuration = VisionConfiguration.Normalize(first.Value); var selected = configuration.Regions[0].Energy;
                var baseline = VisionLayout.Presets()[0].Regions;
                check("vision_drag_switches_custom_and_clips_normalized_region", configuration.Layout == "custom" && selected.X == 0
                    && Math.Abs(selected.Y - .1) < 1e-12 && Math.Abs(selected.Width - .4) < 1e-12 && Math.Abs(selected.Height - .2) < 1e-12);
                check("vision_drag_changes_only_selected_region", configuration.Regions[0].Hp == baseline[0].Hp && configuration.Regions[0].Portrait == baseline[0].Portrait
                    && configuration.Regions.Skip(1).SequenceEqual(baseline.Skip(1)));
                var slot = Descendants<ComboBox>(first).Single(box => box.ItemsSource is KeyValuePair<int, string>[]);
                var region = Descendants<ComboBox>(first).Single(box => box.ItemsSource is KeyValuePair<string, string>[] options && options.Any(value => value.Key == "hp"));
                slot.SelectedValue = 2; region.SelectedValue = "hp";
                first.Preview.BeginSelection(new(area.X + area.Width * .1, area.Y + area.Height * .4));
                first.Preview.FinishSelection(new(area.X + area.Width * .3, area.Y + area.Height * .5));
                var another = VisionConfiguration.Normalize(first.Value);
                check("calibration_slot_and_region_controls_select_one_of_twelve_regions", first.Preview.SelectedSlot == 2 && first.Preview.SelectedRegion == "hp"
                    && another.Regions[0] == configuration.Regions[0] && another.Regions[2].Hp != baseline[2].Hp && another.Regions[2].Energy == baseline[2].Energy);
                first.Preview.BeginSelection(new(area.X + 20, area.Y + 20)); first.Preview.FinishSelection(new(area.X + 20.5, area.Y + 20.5));
                check("calibration_ignores_accidental_subpixel_selection", EvidenceJson.PythonEquals(first.Value, another.ToEvidence()));
                check("vision_preview_changes_leave_persisted_settings_untouched", EvidenceJson.PythonEquals(original, settings.Current.VisionSettings)
                    && EvidenceJson.PythonEquals(original, codec.Load().VisionSettings));
                first.Target.SelectedValue = new BigInteger(456);
                check("vision_target_change_clears_previous_window_image", first.Preview.Image is null);
                await Until(() => { first.Refresh(); return first.Preview.TargetWindow == 456; });
                check("vision_target_preview_matches_selected_window", VisionConfiguration.Normalize(first.Value).TargetWindow == 456
                    && controller.VisualTargets.Windows.SequenceEqual([123L, 456L]));
                await first.Dispatcher.InvokeAsync(() => first.UpdateLayout(), System.Windows.Threading.DispatcherPriority.Render);
                Screenshot(first, Path.ChangeExtension(output, ".calibration.png"));
                Descendants<Button>(first).Single(value => Equals(value.Content, "取消")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            });
            check("vision_cancel_keeps_saved_config_and_releases_ui_image", accepted == false && first.Preview.Image is null
                && EvidenceJson.PythonEquals(original, settings.Current.VisionSettings) && vision.Running);
            await Until(() => vision.State.Get("target_hwnd") is EvidenceInteger { Value: var hwnd } && hwnd == 123
                && vision.State.Get("frame_valid") is EvidenceBoolean { Value: true });
            check("vision_cancel_restores_saved_recognition_geometry", vision.State.Get("layout") is EvidenceText { Value: "keyboard" } && controller.TakePreview() is null);
            VisionSettingsWindow second = new(controller, settings) { Owner = owner };
            EvidenceObject? customSaved = null;
            accepted = Inspect(second, async () =>
            {
                second.Mode.SelectedValue = "custom";
                second.Target.SelectedValue = new BigInteger(456);
                await Until(() => { second.Refresh(); return second.Preview.TargetWindow == 456; });
                customSaved = second.Value;
                Descendants<Button>(second).Single(value => Equals(value.Content, "保存")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
            });
            check("calibration_save_persists_all_normalized_regions", accepted == true && customSaved is not null
                && EvidenceJson.PythonEquals(customSaved, codec.Load().VisionSettings) && VisionConfiguration.Normalize(codec.Load().VisionSettings).Regions.Count == 4);
            VisionSettingsWindow reopened = new(controller, settings) { Owner = owner };
            accepted = Inspect(reopened, () =>
            {
                check("calibration_reopens_saved_custom_settings", EvidenceJson.PythonEquals(customSaved!, reopened.Value));
                reopened.Mode.SelectedValue = "gamepad_expanded";
                Descendants<Button>(reopened).Single(value => Equals(value.Content, "保存")).RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                return Task.CompletedTask;
            });
            var saved = VisionConfiguration.Normalize(codec.Load().VisionSettings);
            check("vision_save_persists_layout_and_target_without_custom_regions", accepted == true && saved.Layout == "gamepad_expanded" && saved.TargetWindow == 456 && saved.Regions.Count == 0);
            VisionSettingsWindow hidden = new(controller, settings) { Owner = owner }; hidden.Show();
            await Until(() => { hidden.Refresh(); return hidden.Preview.Image is not null; }); hidden.Hide();
            check("hidden_calibration_releases_preview_pixels", hidden.Preview.Image is null && controller.TakePreview() is null && vision.Running); hidden.Close();
            controller.SetRequirements([]); await Until(() => !vision.Running && capture.Disposed);
            check("calibration_last_demand_releases_capture_backend", capture.Disposed && capture.Released > 0 && controller.TakePreview() is null);
        }
        finally { await controller.DisposeAsync(); temporary.Delete(true); }
    }
}
