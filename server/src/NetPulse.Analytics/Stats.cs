namespace NetPulse.Analytics;

/// <summary>
/// Statistical primitives, ported from the browser engine in diff/netpulse.html.
///
/// These are deliberately literal translations. Where a more idiomatic C# form would
/// change a rounding boundary or an interpolation edge, the JavaScript shape is kept —
/// the numbers these produce are published in regulatory capacity reports, and the
/// parity tests in NetPulse.Analytics.Tests pin every one of them against fixtures
/// captured from the running JavaScript. Optimise only with a green parity run.
/// </summary>
public static class Stats
{
    /// <summary>JS: clamp(v,a,b) = Math.max(a, Math.min(b, v)).</summary>
    public static double Clamp(double v, double a = 0, double b = 1) => Math.Max(a, Math.Min(b, v));

    /// <summary>
    /// Linear-interpolated percentile over a sorted copy, matching the JS exactly:
    /// i = p*(n-1); result = a[floor(i)] + (a[ceil(i)] - a[floor(i)]) * (i - floor(i)).
    /// An empty input yields 0, as in the original.
    /// </summary>
    public static double Percentile(IReadOnlyList<double> values, double p)
    {
        if (values.Count == 0) return 0;
        var a = values.ToArray();
        Array.Sort(a);
        var i = Clamp(p, 0, 1) * (a.Length - 1);
        var lo = (int)Math.Floor(i);
        var hi = (int)Math.Ceiling(i);
        return a[lo] + (a[hi] - a[lo]) * (i - lo);
    }

    /// <summary>Arithmetic mean; empty yields 0, as in the original.</summary>
    public static double Mean(IReadOnlyList<double> values)
    {
        if (values.Count == 0) return 0;
        double s = 0;
        foreach (var v in values) s += v;
        return s / values.Count;
    }

    /// <summary>JS amax: max of the list, or 0 when empty.</summary>
    public static double Max(IReadOnlyList<double> values)
    {
        var m = double.NegativeInfinity;
        foreach (var v in values) if (v > m) m = v;
        return double.IsNegativeInfinity(m) ? 0 : m;
    }

    /// <summary>JS amin: min of the list, or 0 when empty.</summary>
    public static double Min(IReadOnlyList<double> values)
    {
        var m = double.PositiveInfinity;
        foreach (var v in values) if (v < m) m = v;
        return double.IsPositiveInfinity(m) ? 0 : m;
    }

    /// <summary>
    /// Centred rolling median with a half-window of (w-1)>>1, clipped at both ends.
    /// Removes the weekday/weekend sawtooth before a trend is fitted.
    /// </summary>
    public static double[] RollingMedian(IReadOnlyList<double> ys, int w)
    {
        var h = (w - 1) >> 1;
        var outp = new double[ys.Count];
        for (var i = 0; i < ys.Count; i++)
        {
            var a = Math.Max(0, i - h);
            var b = Math.Min(ys.Count, i + h + 1);
            var slice = new double[b - a];
            for (var k = a; k < b; k++) slice[k - a] = ys[k];
            outp[i] = Percentile(slice, 0.5);
        }
        return outp;
    }
}
