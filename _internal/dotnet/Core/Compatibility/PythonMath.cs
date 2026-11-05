using System.Runtime.InteropServices;

namespace EndfieldLogs.Core.Compatibility;

internal static class PythonMath
{
    // The fixed Windows Python uses the Universal CRT for log1p. Double.LogP1
    // currently loses the small-x correction, changing source-time ink weights.
    [DllImport("ucrtbase.dll", EntryPoint = "log1p", CallingConvention = CallingConvention.Cdecl)]
    private static extern double WindowsLogOnePlus(double value);

    internal static double LogOnePlus(double value) => OperatingSystem.IsWindows() ? WindowsLogOnePlus(value) : double.LogP1(value);
}
