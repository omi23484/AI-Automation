using System.Text.Json;
using Xunit;

namespace NetPulse.Analytics.Tests;

/// <summary>
/// Numeric parity between this C# port and the browser engine it replaces.
///
/// The server must publish the same numbers as the tool the reports were validated
/// against — a threshold report that says 88.5 % in one place and 88.7 % in another is
/// worse than no report. Every case here is a fixture captured from the live JS.
/// </summary>
public class ParityTests
{
    // ---------------------------------------------------------------- primitives

    [Fact]
    public void Percentile_matches_javascript_across_the_quantile_range()
    {
        var g = Golden.Load("primitives.json");
        var samples = g.GetProperty("samples").EnumerateArray().Select(x => x.GetDouble()).ToArray();
        var checked_ = 0;
        foreach (var p in g.GetProperty("percentiles").EnumerateObject())
        {
            var q = double.Parse(p.Name, System.Globalization.CultureInfo.InvariantCulture);
            Assert.Equal(p.Value.GetDouble(), Stats.Percentile(samples, q), Golden.Tol);
            checked_++;
        }
        Assert.Equal(10, checked_);
    }

    [Fact]
    public void Mean_max_and_min_match_javascript()
    {
        var g = Golden.Load("primitives.json");
        var samples = g.GetProperty("samples").EnumerateArray().Select(x => x.GetDouble()).ToArray();
        Assert.Equal(g.GetProperty("mean").GetDouble(), Stats.Mean(samples), Golden.Tol);
        Assert.Equal(g.GetProperty("max").GetDouble(), Stats.Max(samples), Golden.Tol);
        Assert.Equal(g.GetProperty("min").GetDouble(), Stats.Min(samples), Golden.Tol);
    }

    [Fact]
    public void RollingMedian_matches_javascript_for_every_window()
    {
        var g = Golden.Load("primitives.json");
        var samples = g.GetProperty("samples").EnumerateArray().Select(x => x.GetDouble()).Take(60).ToArray();
        foreach (var w in g.GetProperty("rollingMedian").EnumerateObject())
        {
            var expected = w.Value.EnumerateArray().Select(x => x.GetDouble()).ToArray();
            var actual = Stats.RollingMedian(samples, int.Parse(w.Name));
            Assert.Equal(expected.Length, actual.Length);
            for (var i = 0; i < expected.Length; i++)
                Assert.Equal(expected[i], actual[i], Golden.Tol);
        }
    }

    [Fact]
    public void TheilSen_matches_javascript_at_every_confidence_level()
    {
        var g = Golden.Load("primitives.json");
        var pts = g.GetProperty("theilSenPoints").EnumerateArray()
            .Select(p => (p.GetProperty("x").GetDouble(), p.GetProperty("y").GetDouble())).ToList();

        foreach (var c in g.GetProperty("theilSen").EnumerateObject())
        {
            var ci = double.Parse(c.Name, System.Globalization.CultureInfo.InvariantCulture);
            var fit = Forecast.TheilSen(pts, ci);
            Assert.NotNull(fit);
            Assert.Equal(c.Value.GetProperty("slope").GetDouble(), fit!.Slope, Golden.Tol);
            Assert.Equal(c.Value.GetProperty("inter").GetDouble(), fit.Intercept, Golden.Tol);
            Assert.Equal(c.Value.GetProperty("slopeLo").GetDouble(), fit.SlopeLo, Golden.Tol);
            Assert.Equal(c.Value.GetProperty("slopeHi").GetDouble(), fit.SlopeHi, Golden.Tol);
        }
    }

    // ------------------------------------------------------------------ forecast

    public static TheoryData<string> ForecastCaseNames()
    {
        var data = new TheoryData<string>();
        foreach (var c in Golden.Load("forecast.json").GetProperty("cases").EnumerateArray())
            data.Add(c.GetProperty("name").GetString()!);
        return data;
    }

    [Theory]
    [MemberData(nameof(ForecastCaseNames))]
    public void Forecast_matches_javascript(string caseName)
    {
        var root = Golden.Load("forecast.json");
        var c = root.GetProperty("cases").EnumerateArray()
            .Single(x => x.GetProperty("name").GetString() == caseName);

        var cfgJson = root.GetProperty("cfg");
        var cfg = new ForecastConfig(
            cfgJson.GetProperty("forecastCI").GetDouble(),
            cfgJson.GetProperty("upgradeLeadDays").GetInt32());

        var daily = c.GetProperty("daily").EnumerateArray()
            .Select(d => new DailyPoint(d.GetProperty("d").GetInt64(), d.GetProperty("p95").GetDouble()))
            .ToList();

        var actual = Forecast.From(daily, c.GetProperty("p95").GetDouble(), cfg);
        var e = c.GetProperty("forecast");

        Assert.Equal(e.GetProperty("slopePerDay").GetDouble(), actual.SlopePerDay, Golden.Tol);
        Assert.Equal(e.GetProperty("current").GetDouble(), actual.Current, Golden.Tol);
        Assert.Equal(e.GetProperty("growthMoM").GetDouble(), actual.GrowthMoM, Golden.Tol);
        Assert.Equal(e.GetProperty("conf").GetDouble(), actual.Conf, Golden.Tol);
        Assert.Equal(e.GetProperty("r2").GetDouble(), actual.R2, Golden.Tol);
        Assert.Equal(e.GetProperty("modelNote").GetString(), actual.ModelNote);

        AssertNullableEqual(e.OptDouble("t80"), actual.T80, "t80");
        AssertNullableEqual(e.OptDouble("t90"), actual.T90, "t90");
        AssertNullableEqual(e.OptDouble("t95"), actual.T95, "t95");
        AssertNullableEqual(e.OptDouble("t80Lo"), actual.T80Lo, "t80Lo");
        AssertNullableEqual(e.OptDouble("t80Hi"), actual.T80Hi, "t80Hi");
        AssertNullableEqual(e.OptDouble("t90Lo"), actual.T90Lo, "t90Lo");
        AssertNullableEqual(e.OptDouble("t90Hi"), actual.T90Hi, "t90Hi");
        AssertNullableEqual(e.OptDouble("t95Lo"), actual.T95Lo, "t95Lo");
        AssertNullableEqual(e.OptDouble("t95Hi"), actual.T95Hi, "t95Hi");

        foreach (var d in new[] { 30, 60, 90, 180 })
        {
            Assert.Equal(e.GetProperty("proj").GetProperty(d.ToString()).GetDouble(), actual.Proj[d], Golden.Tol);
            if (e.GetProperty("projLo").TryGetProperty(d.ToString(), out var lo))
                Assert.Equal(lo.GetDouble(), actual.ProjLo[d], Golden.Tol);
            if (e.GetProperty("projHi").TryGetProperty(d.ToString(), out var hi))
                Assert.Equal(hi.GetDouble(), actual.ProjHi[d], Golden.Tol);
        }

        if (e.TryGetProperty("window", out var w) && w.ValueKind == JsonValueKind.Array)
        {
            Assert.NotNull(actual.Window);
            Assert.Equal(w[0].GetInt32(), actual.Window![0]);
            Assert.Equal(w[1].GetInt32(), actual.Window[1]);
        }
        else
        {
            Assert.Null(actual.Window);
        }
    }

    // ---------------------------------------------------------------------- risk

    public static TheoryData<string> RiskCaseNames()
    {
        var data = new TheoryData<string>();
        foreach (var c in Golden.Load("risk.json").GetProperty("cases").EnumerateArray())
            data.Add(c.GetProperty("name").GetString()!);
        return data;
    }

    [Theory]
    [MemberData(nameof(RiskCaseNames))]
    public void RiskScore_matches_javascript(string caseName)
    {
        var root = Golden.Load("risk.json");
        var c = root.GetProperty("cases").EnumerateArray()
            .Single(x => x.GetProperty("name").GetString() == caseName);

        var wj = root.GetProperty("cfg").GetProperty("riskWeights");
        var w = new RiskWeights(
            wj.GetProperty("peak").GetDouble(), wj.GetProperty("avg").GetDouble(),
            wj.GetProperty("trend").GetDouble(), wj.GetProperty("growth").GetDouble(),
            wj.GetProperty("violations").GetDouble(), wj.GetProperty("anomaly").GetDouble());

        var i = c.GetProperty("input");
        var input = new RiskInput(
            i.GetProperty("p95").GetDouble(), i.GetProperty("avg").GetDouble(), i.OptDouble("pk"),
            i.GetProperty("slope").GetDouble(), i.GetProperty("growth").GetDouble(),
            i.GetProperty("breachesBH").GetInt32(), i.GetProperty("anomalies").GetInt32(),
            i.GetProperty("impact").GetString()!);

        var actual = Risk.Score(input, w);
        var e = c.GetProperty("result");

        Assert.Equal(e.GetProperty("score").GetInt32(), actual.Score);
        Assert.Equal(e.GetProperty("impactMul").GetDouble(), actual.ImpactMultiplier, Golden.Tol);
        foreach (var f in e.GetProperty("factors").EnumerateObject())
            Assert.Equal(f.Value.GetDouble(), actual.Factors[f.Name], Golden.Tol);
    }

    private static void AssertNullableEqual(double? expected, double? actual, string field)
    {
        if (expected is null) { Assert.True(actual is null, $"{field}: expected null, got {actual}"); return; }
        Assert.True(actual is not null, $"{field}: expected {expected}, got null");
        Assert.Equal(expected.Value, actual!.Value, Golden.Tol);
    }
}
