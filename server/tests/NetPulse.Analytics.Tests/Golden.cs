using System.Text.Json;

namespace NetPulse.Analytics.Tests;

/// <summary>
/// Loads the fixtures in golden/, which are captured from the running browser engine
/// by scripts/capture-golden.mjs. They are the definition of "correct" for this port:
/// the numbers in them are the ones already validated against real polling data and
/// published in threshold and regulatory reports.
/// </summary>
internal static class Golden
{
    private static readonly JsonDocumentOptions Opts = new() { AllowTrailingCommas = true };

    internal static JsonElement Load(string file)
    {
        var path = Path.Combine(AppContext.BaseDirectory, "golden", file);
        if (!File.Exists(path))
            throw new FileNotFoundException(
                $"Golden fixture '{file}' is missing. Regenerate it with " +
                "scripts/capture-golden.mjs against diff/netpulse.html.", path);
        return JsonDocument.Parse(File.ReadAllText(path), Opts).RootElement.Clone();
    }

    /// <summary>
    /// Tolerance for cross-runtime float comparison. JavaScript and .NET both use IEEE
    /// 754 doubles and agree bit-for-bit on +-*/, so differences only accumulate through
    /// long reduction chains. 1e-9 catches a genuine algorithmic divergence while
    /// tolerating last-bit ordering effects; it is roughly one part in a billion of a
    /// utilization fraction, far below anything a report displays.
    /// </summary>
    internal const double Tol = 1e-9;

    internal static double? OptDouble(this JsonElement e, string name)
        => e.TryGetProperty(name, out var v) && v.ValueKind is not (JsonValueKind.Null or JsonValueKind.Undefined)
            ? v.GetDouble()
            : null;
}
