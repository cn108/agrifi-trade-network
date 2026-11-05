namespace AgriFi.Mobile.Services;

/// <summary>
/// Retry schedule for outbox sync: exponential backoff with jitter and a retry limit.
/// Backoff is persisted on the draft (NextAttemptAtUtc) rather than slept, so it survives app restarts.
/// </summary>
public sealed class SyncPolicy
{
    /// <summary>Retryable failures tolerated before a draft is parked as failed for manual retry.</summary>
    public int MaxRetryableAttempts { get; init; } = 8;

    public TimeSpan BaseDelay { get; init; } = TimeSpan.FromSeconds(5);
    public TimeSpan MaxDelay { get; init; } = TimeSpan.FromMinutes(15);

    /// <summary>Fraction of the delay randomised in both directions (0.25 = ±25%).</summary>
    public double JitterRatio { get; init; } = 0.25;

    /// <summary>Returns a value in [0, 1); injectable for deterministic tests.</summary>
    public Func<double> Random { get; init; } = System.Random.Shared.NextDouble;

    public static SyncPolicy Default { get; } = new();

    /// <summary>No waiting between attempts; the retry limit still applies.</summary>
    public static SyncPolicy NoBackoff { get; } = new() { BaseDelay = TimeSpan.Zero, MaxRetryableAttempts = int.MaxValue };

    /// <param name="failures">Consecutive retryable failures so far (1 for the first).</param>
    public TimeSpan DelayFor(int failures)
    {
        if (BaseDelay <= TimeSpan.Zero || failures < 1)
        {
            return TimeSpan.Zero;
        }

        var exponent = Math.Min(failures - 1, 30);
        var seconds = Math.Min(MaxDelay.TotalSeconds, BaseDelay.TotalSeconds * Math.Pow(2, exponent));
        var jitter = 1 + JitterRatio * (2 * Random() - 1);
        return TimeSpan.FromSeconds(Math.Max(0, seconds * jitter));
    }
}
