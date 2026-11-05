using System.Text.Json;
using System.Text.Json.Serialization;
using System.Globalization;
using System.Numerics;

namespace EndfieldLogs.Core.Compatibility;

public static class JsonContract
{
    public static JsonSerializerOptions Options { get; } = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
        NumberHandling = JsonNumberHandling.Strict,
        WriteIndented = false,
        Converters = { new BigIntegerJsonConverter() },
    };

    public static string Serialize<T>(T value) => JsonSerializer.Serialize(value, Options);
}

internal sealed class BigIntegerJsonConverter : JsonConverter<BigInteger>
{
    public override BigInteger Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        using var document = JsonDocument.ParseValue(ref reader);
        return BigInteger.Parse(document.RootElement.GetRawText(), CultureInfo.InvariantCulture);
    }
    public override void Write(Utf8JsonWriter writer, BigInteger value, JsonSerializerOptions options) =>
        writer.WriteRawValue(value.ToString(CultureInfo.InvariantCulture));
    public override BigInteger ReadAsPropertyName(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options) =>
        BigInteger.Parse(reader.GetString()!,CultureInfo.InvariantCulture);
    public override void WriteAsPropertyName(Utf8JsonWriter writer, BigInteger value, JsonSerializerOptions options) =>
        writer.WritePropertyName(value.ToString(CultureInfo.InvariantCulture));
}
