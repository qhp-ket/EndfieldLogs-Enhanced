namespace EndfieldLogs.Core.Compatibility;

public static class PythonTextLines
{
    /// <summary>Streaming str.splitlines(keepends=True), including a CRLF crossing a read boundary.</summary>
    public static IEnumerable<string> ReadKeepEnds(TextReader reader, CancellationToken cancellationToken = default)
    {
        System.Text.StringBuilder line = new(); char[] buffer = new char[16 * 1024];
        var carriageReturn = false; int count;
        while ((count = reader.Read(buffer, 0, buffer.Length)) > 0)
        {
            cancellationToken.ThrowIfCancellationRequested();
            for (var index = 0; index < count; index++)
            {
                var character = buffer[index];
                if (carriageReturn)
                {
                    carriageReturn = false;
                    if (character == '\n')
                    { line.Append(character); yield return line.ToString(); line.Clear(); continue; }
                    yield return line.ToString(); line.Clear();
                }
                line.Append(character);
                if (character == '\r') carriageReturn = true;
                else if (character is '\n' or '\v' or '\f' or '\u001c' or '\u001d' or '\u001e' or '\u0085' or '\u2028' or '\u2029')
                { yield return line.ToString(); line.Clear(); }
            }
        }
        cancellationToken.ThrowIfCancellationRequested();
        if (line.Length > 0) yield return line.ToString();
    }

    public static IEnumerable<string> SplitKeepEnds(string text)
    {
        var start = 0;
        for (var index = 0; index < text.Length; index++)
        {
            if (text[index] is not ('\n' or '\r' or '\v' or '\f' or '\u001c' or '\u001d' or '\u001e' or '\u0085' or '\u2028' or '\u2029')) continue;
            if (text[index] == '\r' && index + 1 < text.Length && text[index + 1] == '\n') index++;
            yield return text[start..(index + 1)]; start = index + 1;
        }
        if (start < text.Length) yield return text[start..];
    }
    /// <summary>Python str.splitlines without retained separators or a synthetic terminal empty line.</summary>
    public static IEnumerable<string> Split(string text)
    {
        var start = 0;
        for (var index = 0; index < text.Length; index++)
        {
            if (text[index] is not ('\n' or '\r' or '\v' or '\f' or '\u001c' or '\u001d' or '\u001e' or '\u0085' or '\u2028' or '\u2029')) continue;
            yield return text[start..index];
            if (text[index] == '\r' && index + 1 < text.Length && text[index + 1] == '\n') index++;
            start = index + 1;
        }
        if (start < text.Length) yield return text[start..];
    }
}
