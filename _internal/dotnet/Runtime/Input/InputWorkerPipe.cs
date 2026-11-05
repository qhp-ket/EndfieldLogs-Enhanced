using System.Buffers.Binary;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Input;

/// <summary>Length-bounded JSON control/status channel; raw input stays in the worker's sidecar.</summary>
public sealed class InputWorkerPipe(Stream stream) : IAsyncDisposable
{
    public const int Limit = 1024 * 1024;
    private static readonly UTF8Encoding Utf8 = new(false, true);
    private readonly SemaphoreSlim send = new(1, 1);
    private int disposed;
    public async Task SendAsync(EvidenceObject value, CancellationToken token = default)
    {
        var bytes = Utf8.GetBytes(TraceData.Json(value, finite: true)); if (bytes.Length > Limit) throw new InvalidDataException("输入服务控制消息超过大小限制");
        byte[] header = new byte[4]; BinaryPrimitives.WriteInt32BigEndian(header, bytes.Length);
        await send.WaitAsync(token).ConfigureAwait(false);
        try { await stream.WriteAsync(header, token).ConfigureAwait(false); await stream.WriteAsync(bytes, token).ConfigureAwait(false); await stream.FlushAsync(token).ConfigureAwait(false); }
        finally { send.Release(); }
    }
    public async Task<EvidenceObject> ReceiveAsync(CancellationToken token = default)
    {
        byte[] header = new byte[4]; await stream.ReadExactlyAsync(header, token).ConfigureAwait(false);
        var size = BinaryPrimitives.ReadInt32BigEndian(header); if (size is <= 0 or > Limit) throw new InvalidDataException("输入服务控制消息长度无效");
        var bytes = new byte[size]; await stream.ReadExactlyAsync(bytes, token).ConfigureAwait(false);
        return EvidenceJson.Parse(Utf8.GetString(bytes)) as EvidenceObject ?? throw new InvalidDataException("输入服务控制消息格式无效");
    }
    public static async Task AuthenticateServerAsync(PipeStream stream, byte[] key, int childPid, CancellationToken token)
    {
        if (OperatingSystem.IsWindows() && (!GetNamedPipeClientProcessId(stream.SafePipeHandle, out var actual) || actual != childPid))
            throw new UnauthorizedAccessException("输入服务管道的客户端身份不符");
        var nonce = RandomNumberGenerator.GetBytes(32); await stream.WriteAsync(nonce, token).ConfigureAwait(false); await stream.FlushAsync(token).ConfigureAwait(false);
        byte[] response = new byte[32]; await stream.ReadExactlyAsync(response, token).ConfigureAwait(false);
        if (!CryptographicOperations.FixedTimeEquals(response, HMACSHA256.HashData(key, nonce))) throw new UnauthorizedAccessException("输入服务管道认证失败");
    }
    public static async Task AuthenticateClientAsync(PipeStream stream, byte[] key, int parentPid, CancellationToken token)
    {
        if (OperatingSystem.IsWindows() && (!GetNamedPipeServerProcessId(stream.SafePipeHandle, out var actual) || actual != parentPid))
            throw new UnauthorizedAccessException("输入服务管道的服务端身份不符");
        byte[] nonce = new byte[32]; await stream.ReadExactlyAsync(nonce, token).ConfigureAwait(false);
        await stream.WriteAsync(HMACSHA256.HashData(key, nonce), token).ConfigureAwait(false); await stream.FlushAsync(token).ConfigureAwait(false);
    }
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetNamedPipeClientProcessId(Microsoft.Win32.SafeHandles.SafePipeHandle pipe, out uint pid);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetNamedPipeServerProcessId(Microsoft.Win32.SafeHandles.SafePipeHandle pipe, out uint pid);
    public async ValueTask DisposeAsync()
    { if (Interlocked.Exchange(ref disposed, 1) == 0) await stream.DisposeAsync().ConfigureAwait(false); }
}
