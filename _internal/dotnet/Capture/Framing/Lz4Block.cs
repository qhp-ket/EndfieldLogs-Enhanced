namespace EndfieldLogs.Capture.Framing;

public static class Lz4Block
{
    public static byte[] Decompress(byte[] data)
    {
        List<byte> output = [];
        var source = 0;
        int Length(int initial, string failure)
        {
            var length = initial;
            if (length != 15) return length;
            while (true)
            {
                if (source >= data.Length) throw new InvalidDataException(failure);
                var extra = data[source++];
                length = checked(length+extra);
                if (extra != 255) return length;
            }
        }
        while (source < data.Length)
        {
            var token = data[source++];
            var literals = Length(token >> 4, "lz4 literal length overflow");
            if (literals > data.Length-source) throw new InvalidDataException("lz4 literal overflow");
            for (var i = 0; i < literals; i++) output.Add(data[source+i]);
            source += literals;
            if (source >= data.Length) break;
            if (source+2 > data.Length) throw new InvalidDataException("lz4 missing match offset");
            var offset = data[source] | (data[source+1] << 8);
            source += 2;
            if (offset <= 0 || offset > output.Count) throw new InvalidDataException("lz4 invalid match offset");
            var length = checked(Length(token & 15, "lz4 match length overflow")+4);
            for (var i = 0; i < length; i++) output.Add(output[output.Count-offset]);
        }
        return output.ToArray();
    }
}
