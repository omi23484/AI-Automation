namespace NetPulse.Analytics;

/// <summary>Relative weights of the six risk factors; mirrors the Admin panel.</summary>
public sealed record RiskWeights(
    double Peak = 0.30, double Avg = 0.15, double Trend = 0.20,
    double Growth = 0.15, double Violations = 0.12, double Anomaly = 0.08);

/// <summary>Everything the risk model reads about a link.</summary>
public sealed record RiskInput(
    double P95, double Avg, double? Pk, double Slope, double Growth,
    int BreachesBh, int Anomalies, string Impact);

public sealed record RiskResult(int Score, IReadOnlyDictionary<string, double> Factors, double ImpactMultiplier);

/// <summary>
/// Risk scoring, ported from riskScore() in diff/netpulse.html.
///
/// Six weighted factors on a non-linear utilization curve, multiplied by a business
/// impact factor — so a 60 %-utilized trading link can outrank a 95 %-utilized backup.
/// Factor names are the strings the UI and reports display; they are part of the
/// contract, not internal labels.
/// </summary>
public static class Risk
{
    private static readonly Dictionary<string, double> ImpactMultipliers = new()
    {
        ["Critical"] = 1.25, ["High"] = 1.05, ["Medium"] = 0.85, ["Low"] = 0.65
    };

    /// <summary>Non-linear utilization response: clamp(v,0,1)^1.4.</summary>
    private static double Curve(double v) => Math.Pow(Stats.Clamp(v, 0, 1), 1.4);

    public static RiskResult Score(RiskInput f, RiskWeights w)
    {
        if (!ImpactMultipliers.TryGetValue(f.Impact, out var impactMul))
            throw new ArgumentOutOfRangeException(nameof(f), f.Impact,
                "Unknown business impact; expected Critical, High, Medium or Low.");

        var factors = new Dictionary<string, double>
        {
            ["Peak util"]   = Curve(f.Pk ?? f.P95) * w.Peak,
            ["Avg util"]    = Curve(f.Avg) * w.Avg,
            ["Trend"]       = Stats.Clamp(f.Slope * 60 / 0.5, 0, 1) * w.Trend,
            ["Growth"]      = Stats.Clamp(f.Growth / 0.3, 0, 1) * w.Growth,
            ["Violations"]  = Stats.Clamp(f.BreachesBh / 14d, 0, 1) * w.Violations,
            ["Anomalies"]   = Stats.Clamp(f.Anomalies / 4d, 0, 1) * w.Anomaly
        };

        var sumW = w.Peak + w.Avg + w.Trend + w.Growth + w.Violations + w.Anomaly;
        var raw = factors.Values.Sum() / sumW;
        var score = (int)Math.Round(Stats.Clamp(raw * impactMul, 0, 1) * 100, MidpointRounding.AwayFromZero);
        return new RiskResult(score, factors, impactMul);
    }
}

/// <summary>Utilization band thresholds, as fractions (0.60 = 60 %).</summary>
public sealed record Thresholds(double Warn, double High, double Crit);

public enum UtilState { NoData, Normal, Warning, High, Critical }

public static class States
{
    /// <summary>Ported from stateOfT(): band membership is inclusive at the lower edge.</summary>
    public static UtilState Of(double? util, Thresholds t)
    {
        if (util is null) return UtilState.NoData;
        if (util >= t.Crit) return UtilState.Critical;
        if (util >= t.High) return UtilState.High;
        if (util >= t.Warn) return UtilState.Warning;
        return UtilState.Normal;
    }
}
