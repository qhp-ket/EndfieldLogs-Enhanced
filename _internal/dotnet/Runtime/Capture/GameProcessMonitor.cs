using System.Diagnostics;
using System.Runtime.Versioning;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Native.Processes;

namespace EndfieldLogs.Runtime.Capture;

public sealed record GameProcessObservation(bool Running, FlowKey? Flow);

[SupportedOSPlatform("windows")]
public sealed class GameProcessMonitor(string gameExecutable)
{
    public GameProcessObservation Read()
    {
        var name = Path.GetFileNameWithoutExtension(gameExecutable);
        var processes = Process.GetProcessesByName(name);
        HashSet<uint> pids = [];
        try { foreach (var process in processes) pids.Add(checked((uint)process.Id)); }
        finally { foreach (var process in processes) process.Dispose(); }
        if (pids.Count == 0) return new(false, null);
        var connection = TcpProcessConnections.Read().FirstOrDefault(row => pids.Contains(row.ProcessId)
            && row.RemotePort == 30000 && row.LocalPort != 0 && row.RemoteAddress != "0.0.0.0");
        return new(true, connection is null ? null : new(new(connection.LocalAddress, connection.LocalPort), new(connection.RemoteAddress, connection.RemotePort)));
    }
}
