using System.Collections;
using System.Globalization;
using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using Google.Protobuf;
using Google.Protobuf.Reflection;

namespace EndfieldLogs.Runtime.Sessions;

/// <summary>Typed protobuf reads preserve message defaults separately from wire presence.</summary>
internal readonly record struct ProtoMessage(IMessage? Value)
{
    private FieldDescriptor? Field(string name) => Value?.Descriptor.FindFieldByName(name);
    public object? Scalar(string name) => Field(name)?.Accessor.GetValue(Value);
    public bool Declares(string name) => Field(name) is not null;
    public BigInteger Number(string name) => Scalar(name) switch
    {
        ulong n => n, long n => n, uint n => n, int n => n, ushort n => n, short n => n,
        byte n => n, sbyte n => n, System.Enum value => Convert.ToInt64(value, CultureInfo.InvariantCulture), _ => BigInteger.Zero,
    };
    public BigInteger? Optional(string name) => Number(name) is { IsZero: false } number ? number : null;
    public string Text(string name) => Scalar(name) is System.Enum value
        ? Convert.ToInt64(value, CultureInfo.InvariantCulture).ToString(CultureInfo.InvariantCulture) : Scalar(name)?.ToString() ?? "";
    public bool Boolean(string name) => Scalar(name) is true;
    public double Real(string name) => Scalar(name) is { } value ? Convert.ToDouble(value, CultureInfo.InvariantCulture) : 0;
    public bool Has(string name) => Field(name) is { HasPresence: true } field && field.Accessor.HasValue(Value);
    public string? Case(string name) => Value?.Descriptor.Oneofs.FirstOrDefault(row => row.Name == name)?.Accessor.GetCaseFieldDescriptor(Value)?.Name;
    public string? Enum(string name) => Field(name) is { FieldType: FieldType.Enum } field
        ? field.EnumType.FindValueByNumber(Convert.ToInt32(Scalar(name), CultureInfo.InvariantCulture))?.Name : null;

    public ProtoMessage Child(string name)
    {
        if (Field(name) is not { FieldType: FieldType.Message, IsRepeated: false } field) return new(null);
        return new((IMessage?)field.Accessor.GetValue(Value) ?? field.MessageType.Parser.ParseFrom(Array.Empty<byte>()));
    }

    public IEnumerable<ProtoMessage> Children(string name) => Items(name).OfType<IMessage>().Select(row => new ProtoMessage(row));
    public IEnumerable<object> Items(string name) => Scalar(name) is IEnumerable items ? items.Cast<object>() : [];
    public IEnumerable<(object Key, object? Value)> Mapping(string name)
    {
        if (Scalar(name) is not IDictionary values) yield break;
        foreach (DictionaryEntry pair in values) yield return (pair.Key, pair.Value);
    }

    public double? PresentFloat(string name)
    {
        if (Field(name) is not { } field) return null;
        if (field.HasPresence) return Has(name) ? Real(name) : null;
        var value = Real(name);
        return value != 0 ? value : null;
    }

    public Dictionary<string, object?> Payload(bool defaults = false)
    {
        if (Value is null) return new(StringComparer.Ordinal);
        var settings = new JsonFormatter.Settings(defaults).WithPreserveProtoFieldNames(true);
        var parsed = (EvidenceObject)EvidenceJson.Parse(new JsonFormatter(settings).Format(Value));
        return MessagePayload(parsed, Value.Descriptor);
    }

    private static Dictionary<string, object?> MessagePayload(EvidenceObject obj, MessageDescriptor descriptor) => obj.Fields.ToDictionary(
        pair => pair.Key, pair => FieldPayload(pair.Value, descriptor.FindFieldByName(pair.Key)), StringComparer.Ordinal);

    private static object? FieldPayload(EvidenceValue value, FieldDescriptor? field)
    {
        if (field is null) return Plain(value);
        if (field.IsMap && value is EvidenceObject map)
        {
            var entryValue = field.MessageType.FindFieldByName("value");
            return map.Fields.ToDictionary(pair => pair.Key, pair => ScalarPayload(pair.Value, entryValue), StringComparer.Ordinal);
        }
        if (field.IsRepeated && value is EvidenceArray array) return array.Items.Select(item => ScalarPayload(item, field)).ToArray();
        return ScalarPayload(value, field);
    }

    private static object? ScalarPayload(EvidenceValue value, FieldDescriptor field) => (field.FieldType, value) switch
    {
        (FieldType.Float or FieldType.Double, EvidenceInteger integer) => (double)integer.Value,
        (FieldType.Message, EvidenceObject obj) => MessagePayload(obj, field.MessageType),
        _ => Plain(value),
    };

    internal static object? Plain(EvidenceValue value) => value switch
    {
        EvidenceNull => null, EvidenceBoolean flag => flag.Value, EvidenceInteger number => number.Value,
        EvidenceReal number => number.Value, EvidenceText text => text.Value,
        EvidenceArray array => array.Items.Select(Plain).ToArray(),
        EvidenceObject obj => obj.Fields.ToDictionary(pair => pair.Key, pair => Plain(pair.Value), StringComparer.Ordinal),
        _ => throw new InvalidDataException("Unsupported protobuf JSON value"),
    };

    public static (string? Type, BigInteger? Number, string? Text) Template(ProtoMessage template) =>
        (template.Enum("type"), template.Optional("int_id"), template.Text("str_id") is { Length: > 0 } text ? text : null);
}
