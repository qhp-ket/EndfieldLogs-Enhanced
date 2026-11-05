using System.Net;
using System.Text;
using System.Text.Json;
using EndfieldLogs.Runtime.Updates;

internal static class ReleaseUpdateSpecs
{
    private sealed class Handler(Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> send) : HttpMessageHandler
    { protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token) => send(request, token); }
    private sealed class UnboundedContent(int size) : HttpContent
    {
        protected override bool TryComputeLength(out long length) { length = 0; return false; }
        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) => stream.WriteAsync(new byte[size]).AsTask();
    }
    public static void Run(Action<bool, string> check)
    {
        ReleaseUpdate? Parse(string tag, string current, string ignored = "", string extra = "")
        { using var json = JsonDocument.Parse($$"""{"tag_name":"{{tag}}","published_at":"2026-10-28T10:20:30Z"{{extra}}} """); return ReleaseUpdates.Parse(json.RootElement, current, ignored); }
        var release = Parse("v0.2.1", "0.2.0")!;
        check(release.Version == "0.2.1" && release.Url.AbsoluteUri == "https://github.com/qhp-ket/EndfieldLogs-Enhanced/releases/tag/v0.2.1" && release.PublishedAt.Offset == TimeSpan.Zero, "Official stable metadata yields version, timezone and constructed URL");
        check(Parse("v0.2.1", "0.2.1") is null && Parse("v0.2.0", "0.2.1") is null && Parse("v0.2.1", "0.2.1-dev.2") is not null, "Equal or older stable release is suppressed; same-version development build may upgrade");
        check(Parse("v0.2.1", "0.2.0", "v0.2.1") is null && Parse("v0.2.1", "0.2.0", extra: ",\"prerelease\":true") is null && Parse("v0.2.1", "0.2.0", extra: ",\"draft\":true") is null, "Ignored, draft and prerelease candidates do not notify");
        check(new[] { "v01.2.3", "0.2.1-beta", "0.2.1+build", "../../evil", "https://evil.example" }.All(tag => Parse(tag, "0.0.0") is null), "Stable tags reject leading zeros, suffixes and URL injection");
        check(Parse("v999999999999999999999999.1.0", "999999999999999999999998.9.9") is not null, "Version comparison is numerical without integer overflow");
        using (var naive = JsonDocument.Parse("""{"tag_name":"v1.0.0","published_at":"2026-10-28T10:20:30"}""")) check(ReleaseUpdates.Parse(naive.RootElement, "0.0.0") is null, "Timezone-less publication is rejected");
        var requested = false;
        using (HttpClient client = new(new Handler((request, _) =>
        {
            requested = request.RequestUri == ReleaseUpdates.Endpoint && request.Headers.UserAgent.ToString() == "Endfield-Logs-Enhanced" && request.Headers.Accept.ToString().Contains("application/vnd.github+json", StringComparison.Ordinal);
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("""{"tag_name":"v1.0.0","published_at":"2026-10-28T10:20:30Z","html_url":"https://evil.example"}""", Encoding.UTF8, "application/json") });
        })))
        {
            var result = ReleaseUpdates.CheckAsync("0.0.0", client: client).GetAwaiter().GetResult();
            check(requested && result?.Url.Host == "github.com", "HTTP fetch uses fixed endpoint and required headers; payload URL never controls navigation");
        }
        using (HttpClient missing = new(new Handler((_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound)))))
            check(ReleaseUpdates.CheckAsync("0.0.0", client: missing).GetAwaiter().GetResult() is null, "No published release is a normal no-update result");
        using (HttpClient large = new(new Handler((_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new UnboundedContent(1024 * 1024 + 1) }))))
        {
            var rejected = false; try { ReleaseUpdates.CheckAsync("0.0.0", client: large).GetAwaiter().GetResult(); } catch (InvalidDataException) { rejected = true; }
            check(rejected, "Chunked or unknown-size response is bounded to one MiB");
        }
        using (HttpClient stalled = new(new Handler(async (_, token) => { await Task.Delay(Timeout.Infinite, token); return new(HttpStatusCode.OK); })))
        using (CancellationTokenSource cancel = new())
        {
            var pending = ReleaseUpdates.CheckAsync("0.0.0", token: cancel.Token, client: stalled); cancel.Cancel();
            var stopped = false; try { pending.GetAwaiter().GetResult(); } catch (OperationCanceledException) { stopped = true; }
            check(stopped, "Closing cancels an in-flight HTTP request");
        }
    }
}
