namespace EndfieldLogs.Runtime.Configuration;

/// <summary>Application-owned settings; view adapters commit changes on their owner thread.</summary>
public sealed class SettingsStore(ApplicationSettings current, SettingsCodec codec, string? path = null)
{
    private readonly int owner = Environment.CurrentManagedThreadId;
    public ApplicationSettings Current { get; private set; } = current;
    public SettingsContext Context => codec.Context;
    public void Update(Func<ApplicationSettings, ApplicationSettings> update, bool save = true)
    {
        if (Environment.CurrentManagedThreadId != owner) throw new InvalidOperationException("设置只能在所属线程提交");
        Current = update(Current); if (save) Save();
    }
    public void Save()
    {
        if (Environment.CurrentManagedThreadId != owner) throw new InvalidOperationException("设置只能在所属线程提交");
        codec.Save(Current, path);
    }
}
