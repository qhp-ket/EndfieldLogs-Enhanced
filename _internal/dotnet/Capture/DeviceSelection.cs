using System.Globalization;
using System.Numerics;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Native.Capture;

namespace EndfieldLogs.Capture;

public static class DeviceSelection
{
    public const string DiscoveryFilter = "tcp port 30000";
    public static string FlowFilter(FlowKey flow) => string.Create(CultureInfo.InvariantCulture,
        $"tcp and ((src host {flow.Client.Ip} and src port {flow.Client.Port} and dst host {flow.Server.Ip} and dst port {flow.Server.Port}) or (src host {flow.Server.Ip} and src port {flow.Server.Port} and dst host {flow.Client.Ip} and dst port {flow.Client.Port}))");

    public static IReadOnlyList<DeviceInfo> Select(IReadOnlyList<DeviceInfo> devices, string? request)
    {
        var value = (string.IsNullOrEmpty(request) ? "auto" : request).Trim().Trim('"').Trim('\'');
        if (value.Equals("auto", StringComparison.OrdinalIgnoreCase)) return devices.Where(device =>
            (device.Flags & 1) != 0 || device.Ipv4Addresses.Count != 0 ||
            new[] { "wan miniport (ip)", "ndiswan", "ppp adapter" }.Any(hint =>
                (device.Description ?? "").Contains(hint, StringComparison.OrdinalIgnoreCase))).ToArray();
        if (value.Length > 0 && value.All(char.IsDigit))
        {
            var ascii = string.Concat(value.Select(character => char.GetNumericValue(character).ToString(CultureInfo.InvariantCulture)));
            var index = BigInteger.Parse(ascii, CultureInfo.InvariantCulture);
            return index >= 1 && index <= devices.Count ? [devices[(int)index-1]] : [];
        }
        return devices.Where(device => new[] { device.Name, device.Description ?? "" }.Concat(device.Ipv4Addresses)
            .Any(item => item.Contains(value, StringComparison.OrdinalIgnoreCase))).ToArray();
    }

    public static (int Score, int AddressCount, string Name) Preference(DeviceInfo device, IReadOnlySet<string> observed)
    {
        var description = (device.Description ?? "").ToLowerInvariant();
        var score = observed.Contains(device.Name) ? 100 : 0;
        if (new[] { "virtual", "vmware", "hyper-v" }.Any(description.Contains)) score -= 20;
        if (new[] { "ethernet", "wi-fi", "wireless" }.Any(description.Contains)) score += 5;
        return (score, device.Ipv4Addresses.Count, device.Name);
    }

    public static DeviceInfo? ChooseForFlow(IReadOnlyList<DeviceInfo> devices, FlowKey flow, IReadOnlySet<string> observed)
    {
        var exact = devices.Where(device => device.Ipv4Addresses.Contains(flow.Client.Ip)).ToArray();
        var candidates = exact.Length > 0 ? exact : observed.Count > 0 ? devices.Where(device => observed.Contains(device.Name)) : devices;
        return candidates.OrderByDescending(device => Preference(device, observed).Score)
            .ThenByDescending(device => device.Ipv4Addresses.Count).ThenByDescending(device => device.Name, StringComparer.Ordinal).FirstOrDefault();
    }
}
