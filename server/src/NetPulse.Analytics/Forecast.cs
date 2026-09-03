namespace NetPulse.Analytics;

/// <summary>A single day's busy-period utilization, the input to forecasting.</summary>
public readonly record struct DailyPoint(long DateMs, double P95);

/// <summary>Theil–Sen fit with a slope confidence interval.</summary>
public sealed record TheilSenFit(double Slope, double Intercept, double SlopeLo, double SlopeHi);

/// <summary>Settings the forecast reads; mirrors the Admin panel in the browser app.</summary>
public sealed record ForecastConfig(double Ci = 0.8, int UpgradeLeadDays = 42);

/// <summary>Output of <see cref="Forecast.From"/>. Days-to-threshold are null when unreachable.</summary>
public sealed class ForecastResult
{
    public double SlopePerDay { get; set; }
    public double Current { get; set; }
    public double? T80 { get; set; }
    public double? T90 { get; set; }
    public double? T95 { get; set; }
    public double? T80Lo { get; set; }
    public double? T80Hi { get; set; }
    public double? T90Lo { get; set; }
    public double? T90Hi { get; set; }
    public double? T95Lo { get; set; }
    public double? T95Hi { get; set; }
    public double GrowthMoM { get; set; }
    public double Conf { get; set; } = 0.2;
    public Dictionary<int, double> Proj { get; } = new();
    public Dictionary<int, double> ProjLo { get; } = new();
    public Dictionary<int, double> ProjHi { get; } = new();
    public int[]? Window { get; set; }
    public double R2 { get; set; }
    public double Ci { get; set; }
    public double SlopeLo { get; set; }
    public double SlopeHi { get; set; }
    public string ModelNote { get; set; } = "";
}

/// <summary>
/// Capacity forecasting, ported from forecastFrom() in diff/netpulse.html.
///
/// Theil–Sen (median of pairwise slopes) rather than least squares, so one spike day
/// cannot bend the trend; the weekly cycle is removed with a 7-day rolling median
/// first; and when weekdays run clearly hotter than weekends the fit uses weekdays
/// only, because a business link is capped by its busy days.
/// </summary>
public static class Forecast
{
    private const double DayMs = 86_400_000d;
    private const double SlopeCeiling = 0.04;   // ±4 %/day plausibility ceiling

    /// <summary>
    /// Theil–Sen with a slope confidence interval. Pairs are sampled with a stride of
    /// max(1, floor(n/45)) — the same decimation the JS uses, which is part of the
    /// result, not an optimisation: changing it changes the median slope.
    /// </summary>
    public static TheilSenFit? TheilSen(IReadOnlyList<(double X, double Y)> pts, double ci)
    {
        var n = pts.Count;
        if (n < 2) return null;
        var step = Math.Max(1, (int)Math.Floor(n / 45d));
        var slopes = new List<double>();
        for (var i = 0; i < n; i += step)
        for (var j = i + 1; j < n; j += step)
        {
            var dx = pts[j].X - pts[i].X;
            if (dx > 0) slopes.Add((pts[j].Y - pts[i].Y) / dx);
        }
        if (slopes.Count == 0) return null;
        var slope = Stats.Percentile(slopes, 0.5);
        var a = (1 - (ci <= 0 ? 0.8 : ci)) / 2;
        var inters = new double[n];
        for (var k = 0; k < n; k++) inters[k] = pts[k].Y - slope * pts[k].X;
        return new TheilSenFit(slope, Stats.Percentile(inters, 0.5),
            Stats.Percentile(slopes, a), Stats.Percentile(slopes, 1 - a));
    }

    /// <summary>Mean absolute error of a fit against held-out points.</summary>
    public static double MeanAbsError(TheilSenFit fit, IReadOnlyList<(double X, double Y)> pts)
    {
        if (pts.Count == 0) return double.PositiveInfinity;
        var errs = new double[pts.Count];
        for (var i = 0; i < pts.Count; i++) errs[i] = Math.Abs(pts[i].Y - (fit.Slope * pts[i].X + fit.Intercept));
        return Stats.Mean(errs);
    }

    public static ForecastResult From(IReadOnlyList<DailyPoint> daily, double p95, ForecastConfig cfg)
    {
        var ci = cfg.Ci <= 0 ? 0.8 : cfg.Ci;
        var o = new ForecastResult { Current = p95, Ci = ci };
        foreach (var d in new[] { 30, 60, 90, 180 }) o.Proj[d] = p95;

        if (daily.Count < 5) { o.ModelNote = "not enough history for a trend"; return o; }

        var d0 = daily[0].DateMs;
        var xs = new double[daily.Count];
        var ys = new double[daily.Count];
        var dows = new int[daily.Count];
        for (var i = 0; i < daily.Count; i++)
        {
            xs[i] = (daily[i].DateMs - d0) / DayMs;
            ys[i] = Stats.Clamp(daily[i].P95, 0, 1.5);
            dows[i] = (int)DateTimeOffset.FromUnixTimeMilliseconds(daily[i].DateMs).UtcDateTime.DayOfWeek;
        }

        // Deseasonalize the weekly cycle before fitting the trend.
        var sm = Stats.RollingMedian(ys, 7);
        var pts = new List<(double X, double Y, int Dow)>(daily.Count);
        for (var i = 0; i < daily.Count; i++) pts.Add((xs[i], sm[i], dows[i]));

        // KNOWN DORMANT BRANCH — ported faithfully, do not "fix" without a decision.
        //
        // The intent is: when weekdays run clearly hotter than weekends, fit the trend
        // from weekdays only, because a business link is capped by its busy days.
        //
        // It cannot fire. The 7-day rolling median directly above runs first, and a
        // centred 7-day window over a 5-on/2-off weekly cycle always contains exactly
        // five weekday values and two weekend values — so its median is the weekday
        // value at EVERY point, weekend-labelled points included. Measured against the
        // browser engine with a raw 9:1 weekday:weekend ratio, both smoothed medians
        // come out identical (0.90 and 0.90), so `wdMed > weMed * 1.35 + 0.02` is
        // false for any regular weekly pattern, and for irregular ones too.
        //
        // The deseasonalisation destroys the signal this test looks for. Consequently
        // no link has ever been forecast on a weekday-only basis, and no report has
        // ever carried the "busy-weekday" model note.
        //
        // It is kept here because the server must publish the same numbers as the tool
        // the existing reports were validated against. Making it live would change
        // forecasts for every business link. That is a product decision, not a port
        // decision; see server/ARCHITECTURE.md "Open questions".
        var note = "";
        var wd = pts.Where(p => p.Dow >= 1 && p.Dow <= 5).ToList();
        var we = pts.Where(p => p.Dow is 0 or 6).ToList();
        if (wd.Count >= 5 && we.Count >= 2 &&
            Stats.Percentile(wd.Select(p => p.Y).ToArray(), 0.5) >
            Stats.Percentile(we.Select(p => p.Y).ToArray(), 0.5) * 1.35 + 0.02)
        {
            pts = wd;
            note = "busy-weekday";
        }

        var xy = pts.Select(p => (p.X, p.Y)).ToList();
        var recCount = Math.Max(7, (int)Math.Floor(xy.Count / 2d));
        var rec = xy.Skip(Math.Max(0, xy.Count - recCount)).ToList();

        var cands = new List<(string Name, List<(double X, double Y)> Pts, TheilSenFit Fit)>();
        foreach (var (name, cp) in new[] { ("full-window trend", xy), ("recent trend", rec) })
        {
            var f = TheilSen(cp, ci);
            if (f != null) cands.Add((name, cp, f));
        }
        if (cands.Count == 0) { o.ModelNote = note + " · no fit"; return o; }

        var chosen = cands[0];
        var relErr = 0.35;
        if (xy.Count >= 8)
        {
            var k = Math.Max(3, (int)Math.Round(xy.Count * 0.2, MidpointRounding.AwayFromZero));
            var cut = xy[xy.Count - k - 1].X;
            var test = xy.Skip(xy.Count - k).ToList();
            var best = double.PositiveInfinity;
            foreach (var c in cands)
            {
                var tf = TheilSen(c.Pts.Where(p => p.X <= cut).ToList(), ci);
                if (tf == null) continue;
                var err = MeanAbsError(tf, test);
                if (err < best) { best = err; chosen = c; }
            }
            if (!double.IsPositiveInfinity(best))
                relErr = Stats.Clamp(best / Math.Max(0.05, Stats.Mean(test.Select(p => p.Y).ToArray())), 0, 1);
        }

        var fit = chosen.Fit;
        var slope = Stats.Clamp(fit.Slope, -SlopeCeiling, SlopeCeiling);
        var sHi = Stats.Clamp(fit.SlopeHi, -SlopeCeiling, SlopeCeiling);
        var sLo = Stats.Clamp(fit.SlopeLo, -SlopeCeiling, SlopeCeiling);
        var lastX = xy[^1].X;
        var cur = Stats.Clamp(slope * lastX + fit.Intercept, 0, 1.5);

        o.SlopePerDay = slope; o.Current = cur; o.R2 = Stats.Clamp(1 - relErr, 0, 1);
        o.SlopeLo = sLo; o.SlopeHi = sHi;

        // A faster slope reaches the threshold sooner, so sHi gives the Lo (earliest) day.
        double? TimeTo(double t, double sl) => cur >= t ? 0 : (sl > 1e-5 ? (t - cur) / sl : (double?)null);
        o.T80 = TimeTo(0.80, slope); o.T80Lo = TimeTo(0.80, sHi); o.T80Hi = TimeTo(0.80, sLo);
        o.T90 = TimeTo(0.90, slope); o.T90Lo = TimeTo(0.90, sHi); o.T90Hi = TimeTo(0.90, sLo);
        o.T95 = TimeTo(0.95, slope); o.T95Lo = TimeTo(0.95, sHi); o.T95Hi = TimeTo(0.95, sLo);

        foreach (var dd in new[] { 30, 60, 90, 180 })
        {
            o.Proj[dd] = Stats.Clamp(cur + slope * dd, 0, 1.2);
            o.ProjLo[dd] = Stats.Clamp(cur + sLo * dd, 0, 1.2);
            o.ProjHi[dd] = Stats.Clamp(cur + sHi * dd, 0, 1.2);
        }

        // Growth comes from the same fitted slope, so it can never disagree with the trend.
        o.GrowthMoM = Stats.Clamp(slope * 30 / Math.Max(cur, 0.03), -3, 3);

        var agree = cands.Count == 2 && Math.Sign(cands[0].Fit.Slope) == Math.Sign(cands[1].Fit.Slope);
        double? bandDays = (o.T90Hi != null && o.T90Lo != null) ? Math.Abs(o.T90Hi.Value - o.T90Lo.Value) : null;
        var tight = bandDays != null ? Stats.Clamp(1 - bandDays.Value / 120, 0, 1) : 0.35;
        o.Conf = Stats.Clamp(0.15
                             + Stats.Clamp((lastX - xy[0].X) / 45, 0, 1) * 0.25
                             + (1 - relErr) * 0.3
                             + (agree ? 0.1 : 0)
                             + tight * 0.15, 0, 0.95);

        o.ModelNote = (note.Length > 0 ? note + " · " : "") + chosen.Name
                      + $" · {Math.Round(ci * 100, MidpointRounding.AwayFromZero)}% band";

        if (o.T90 is > 0)
        {
            var c0 = Math.Max(0, o.T90.Value - cfg.UpgradeLeadDays);
            o.Window = new[]
            {
                (int)Math.Round(c0, MidpointRounding.AwayFromZero),
                (int)Math.Round(Math.Max(c0 + 15, o.T90.Value), MidpointRounding.AwayFromZero)
            };
        }
        return o;
    }
}
