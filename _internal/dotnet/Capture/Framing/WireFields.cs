using System.Numerics;
using System.Text;

namespace EndfieldLogs.Capture.Framing;

public sealed record WireField(BigInteger Number, int WireType, BigInteger? Integer, byte[]? Bytes);
public sealed record SessionHead(BigInteger? MessageId=null, BigInteger? UpSequenceId=null, BigInteger? DownSequenceId=null,
    BigInteger? TotalPackCount=null, BigInteger? CurrentPackIndex=null, bool? IsCompressed=null, BigInteger? Checksum=null,
    string? ParseError=null)
{
    public Dictionary<string, object?> ToPayload()
    {
        Dictionary<string, object?> values = [];
        void Add(string key, object? value) { if (value is not null) values[key] = value; }
        Add("msgid", MessageId); Add("up_seqid", UpSequenceId); Add("down_seqid", DownSequenceId);
        Add("total_pack_count", TotalPackCount); Add("current_pack_index", CurrentPackIndex);
        Add("is_compress", IsCompressed); Add("checksum", Checksum); Add("parse_error", ParseError);
        return values;
    }
}
public sealed record SessionLogin(string? Uid=null, string? LoginToken=null, byte[]? EncryptedSessionKey=null,
    byte[]? SessionNonce=null, BigInteger? ServerTime=null, BigInteger? ServerZone=null);

public static class WireFields
{
    public static (BigInteger Value, int Offset) DecodeVarint(byte[] data, int offset=0)
    {
        BigInteger value = 0;
        var shift = 0;
        var index = offset;
        while (index < data.Length)
        {
            // Negative offsets have Python byte-index semantics. They are not used by live framing.
            var actual = index < 0 ? data.Length+index : index;
            if (actual < 0) throw new IndexOutOfRangeException("index out of range");
            var item = data[actual];
            index++;
            value |= (BigInteger)(item & 0x7f) << shift;
            if ((item & 0x80) == 0) return (value, index);
            shift += 7;
            if (shift > 63) throw new InvalidDataException("varint too long");
        }
        throw new InvalidDataException("incomplete varint");
    }

    public static IEnumerable<WireField> Enumerate(byte[] data)
    {
        var index = 0;
        while (index < data.Length)
        {
            var (tag, next) = DecodeVarint(data, index);
            index = next;
            var field = tag >> 3;
            var wire = (int)(tag & 7);
            if (wire == 0)
            {
                var (value, end) = DecodeVarint(data, index);
                index = end;
                yield return new(field, wire, value, null);
                continue;
            }
            BigInteger length;
            var error = "";
            switch (wire)
            {
                case 2: (length, index) = DecodeVarint(data, index); error="field length overflow"; break;
                case 5: length=4; error="fixed32 overflow"; break;
                case 1: length=8; error="fixed64 overflow"; break;
                default: throw new InvalidDataException($"unsupported wire type: {wire}");
            }
            var endIndex = index+length;
            if (endIndex > data.Length) throw new InvalidDataException(error);
            var bytes = data[index..(int)endIndex];
            index = (int)endIndex;
            yield return new(field, wire, null, bytes);
        }
    }

    public static SessionHead ParseHead(byte[] data)
    {
        SessionHead head = new();
        try
        {
            foreach (var field in Enumerate(data))
            {
                if (field.WireType != 0) continue;
                head = field.Number switch
                {
                    var n when n == 1 => head with { MessageId=field.Integer },
                    var n when n == 2 => head with { UpSequenceId=field.Integer },
                    var n when n == 3 => head with { DownSequenceId=field.Integer },
                    var n when n == 4 => head with { TotalPackCount=field.Integer },
                    var n when n == 5 => head with { CurrentPackIndex=field.Integer },
                    var n when n == 6 => head with { IsCompressed=field.Integer != 0 },
                    var n when n == 7 => head with { Checksum=field.Integer },
                    _ => head,
                };
            }
        }
        catch (InvalidDataException error) { head = head with { ParseError=error.Message }; }
        return head;
    }

    public static SessionLogin ParseLogin(byte[] data)
    {
        SessionLogin login = new();
        foreach (var field in Enumerate(data))
        {
            if (field.WireType == 2 && field.Bytes is byte[] bytes)
            {
                login = field.Number switch
                {
                    var n when n == 1 => login with { Uid=Encoding.UTF8.GetString(bytes) },
                    var n when n == 2 => login with { LoginToken=Encoding.UTF8.GetString(bytes) },
                    var n when n == 3 => login with { EncryptedSessionKey=bytes },
                    var n when n == 4 => login with { SessionNonce=bytes },
                    _ => login,
                };
            }
            else if (field.WireType == 0)
            {
                if (field.Number == 8) login = login with { ServerTime=field.Integer };
                else if (field.Number == 10) login = login with { ServerZone=field.Integer };
            }
        }
        return login;
    }
}
