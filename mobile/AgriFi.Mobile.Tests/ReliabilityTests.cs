using System.Net;
using AgriFi.Mobile.Models;
using AgriFi.Mobile.Services;

namespace AgriFi.Mobile.Tests;

public sealed class ManualClock(DateTimeOffset start) : TimeProvider
{
    private DateTimeOffset _now = start;

    public override DateTimeOffset GetUtcNow() => _now;

    public void Advance(TimeSpan by) => _now += by;
}

public class ReliabilityTests
{
    private static readonly DateTimeOffset Start = new(2026, 3, 1, 8, 0, 0, TimeSpan.Zero);

    private static SyncPolicy Policy(int maxAttempts = 8, double random = 0.5) => new()
    {
        BaseDelay = TimeSpan.FromSeconds(10),
        MaxDelay = TimeSpan.FromSeconds(60),
        MaxRetryableAttempts = maxAttempts,
        JitterRatio = 0.25,
        Random = () => random,
    };

    [Fact]
    public void Backoff_doubles_up_to_the_cap()
    {
        var policy = Policy();

        Assert.Equal(TimeSpan.FromSeconds(10), policy.DelayFor(1));
        Assert.Equal(TimeSpan.FromSeconds(20), policy.DelayFor(2));
        Assert.Equal(TimeSpan.FromSeconds(40), policy.DelayFor(3));
        Assert.Equal(TimeSpan.FromSeconds(60), policy.DelayFor(4));
        Assert.Equal(TimeSpan.FromSeconds(60), policy.DelayFor(500));
    }

    [Fact]
    public void Jitter_spreads_delays_within_the_configured_ratio()
    {
        Assert.Equal(TimeSpan.FromSeconds(7.5), Policy(random: 0).DelayFor(1));
        Assert.Equal(TimeSpan.FromSeconds(12.5), Policy(random: 1).DelayFor(1));
    }

    [Fact]
    public async Task Server_error_defers_the_draft_and_the_retry_reuses_the_same_operation_id()
    {
        var clock = new ManualClock(Start);
        using var h = new Harness(Policy(), clock);
        await h.SignInAsync();
        var draft = await h.AddDraftAsync();
        h.Server.ServerErrorsRemaining = 1;

        await h.Sync.SyncPendingAsync();
        var deferred = (await h.Outbox.FindAsync(draft.Id))!;
        Assert.Equal(DraftStatus.Pending, deferred.SyncStatus);
        Assert.Equal(1, deferred.RetryCount);
        Assert.Equal(Start.AddSeconds(10), DateTimeOffset.Parse(deferred.NextAttemptAtUtc));

        // Not due yet: nothing is sent.
        await h.Sync.SyncPendingAsync();
        Assert.Equal(1, h.Server.SyncOperationRequests);

        clock.Advance(TimeSpan.FromSeconds(11));
        Assert.Equal(1, await h.Sync.SyncPendingAsync());

        Assert.Equal(2, h.Server.SyncOperationRequests);
        Assert.Equal(draft.ClientSyncId, h.Server.Batches.Single().ClientSyncId);
        Assert.Equal(0, (await h.Outbox.FindAsync(draft.Id))!.RetryCount);
    }

    [Fact]
    public async Task Backoff_survives_an_app_restart()
    {
        var clock = new ManualClock(Start);
        using var h = new Harness(Policy(), clock);
        await h.SignInAsync();
        await h.AddDraftAsync();
        h.Server.ServerErrorsRemaining = 1;
        await h.Sync.SyncPendingAsync();
        await h.RestartAsync();
        await h.Sync.SyncPendingAsync();
        Assert.Equal(1, h.Server.SyncOperationRequests);

        clock.Advance(TimeSpan.FromMinutes(5));
        Assert.Equal(1, await h.Sync.SyncPendingAsync());
        Assert.Single(h.Server.Batches);
    }

    [Fact]
    public async Task Retry_limit_parks_the_draft_and_manual_retry_resends_without_duplicating()
    {
        var clock = new ManualClock(Start);
        using var h = new Harness(Policy(maxAttempts: 3), clock);
        await h.SignInAsync();
        var draft = await h.AddDraftAsync();
        h.Server.ServerErrorsRemaining = 3;

        for (var i = 0; i < 3; i++)
        {
            await h.Sync.SyncPendingAsync();
            clock.Advance(TimeSpan.FromMinutes(2));
        }

        var parked = (await h.Outbox.FindAsync(draft.Id))!;
        Assert.Equal(DraftStatus.Failed, parked.SyncStatus);
        Assert.Contains("Gave up after 3 attempts", parked.LastError);
        Assert.Equal(3, h.Server.SyncOperationRequests);

        // A parked draft is not sent again until the user asks.
        await h.Sync.SyncPendingAsync();
        Assert.Equal(3, h.Server.SyncOperationRequests);

        await h.Sync.RetryFailedAsync("user-1");
        Assert.Equal(1, await h.Sync.SyncPendingAsync());
        Assert.Equal(draft.ClientSyncId, h.Server.Batches.Single().ClientSyncId);
    }

    [Fact]
    public async Task Permanent_rejection_is_not_retried_and_does_not_use_backoff()
    {
        var clock = new ManualClock(Start);
        using var h = new Harness(Policy(), clock);
        await h.SignInAsync();
        var draft = await h.AddDraftAsync("bad");
        h.Server.RejectQuantity = quantity => quantity == "bad";

        await h.Sync.SyncPendingAsync();
        clock.Advance(TimeSpan.FromHours(1));
        await h.Sync.SyncPendingAsync();

        var stored = (await h.Outbox.FindAsync(draft.Id))!;
        Assert.Equal(DraftStatus.Failed, stored.SyncStatus);
        Assert.Equal(0, stored.RetryCount);
        Assert.Equal(1, h.Server.SyncOperationRequests);
    }

    [Fact]
    public async Task Cancelling_a_sync_keeps_the_draft_queued_under_the_same_key()
    {
        using var h = new Harness();
        await h.SignInAsync();
        var draft = await h.AddDraftAsync();
        h.Server.HangSyncUntilCancelled = true;
        using var cts = new CancellationTokenSource(TimeSpan.FromMilliseconds(200));

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => h.Sync.SyncPendingAsync(cts.Token));

        var stored = (await h.Outbox.FindAsync(draft.Id))!;
        Assert.Equal(DraftStatus.Pending, stored.SyncStatus);
        Assert.Equal(draft.ClientSyncId, stored.ClientSyncId);
        Assert.Equal(0, stored.RetryCount);

        // The sync lock was released, so the next pass works and creates exactly one batch.
        h.Server.HangSyncUntilCancelled = false;
        Assert.Equal(1, await h.Sync.SyncPendingAsync());
        Assert.Single(h.Server.Batches);
    }

    [Fact]
    public async Task Already_cancelled_token_sends_nothing()
    {
        using var h = new Harness();
        await h.SignInAsync();
        await h.AddDraftAsync();
        using var cts = new CancellationTokenSource();
        await cts.CancelAsync();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => h.Sync.SyncPendingAsync(cts.Token));

        Assert.Equal(0, h.Server.SyncOperationRequests);
    }

    [Fact]
    public async Task Expired_session_that_cannot_refresh_keeps_drafts_queued_without_spending_retries()
    {
        using var h = new Harness(Policy());
        await h.SignInAsync();
        var draft = await h.AddDraftAsync();
        h.Server.ExpireAccessToken();
        h.Server.RefreshRejected = true;

        var exception = await Assert.ThrowsAsync<ApiRequestException>(() => h.Sync.SyncPendingAsync());

        Assert.Equal(HttpStatusCode.Unauthorized, exception.StatusCode);
        var stored = (await h.Outbox.FindAsync(draft.Id))!;
        Assert.Equal(DraftStatus.Pending, stored.SyncStatus);
        Assert.Equal(0, stored.RetryCount);
        Assert.Equal(0, stored.AttemptCount);
        Assert.Equal(0, h.Server.SyncOperationRequests);
    }

    [Fact]
    public async Task Throttling_backs_off_and_stops_the_pass()
    {
        var clock = new ManualClock(Start);
        using var h = new Harness(Policy(), clock);
        await h.SignInAsync();
        await h.AddDraftAsync("1");
        await h.AddDraftAsync("2");
        h.Server.ThrottleCreates = true;

        await h.Sync.SyncPendingAsync();

        Assert.Equal(1, h.Server.SyncOperationRequests);
        h.Server.ThrottleCreates = false;
        await h.Sync.SyncPendingAsync();
        // The first draft is deferred; the second is due and is sent.
        Assert.Single(h.Server.Batches);

        clock.Advance(TimeSpan.FromSeconds(30));
        await h.Sync.SyncPendingAsync();
        Assert.Equal(2, h.Server.Batches.Count);
        Assert.Equal(2, h.Server.Batches.Select(batch => batch.ClientSyncId).Distinct().Count());
    }
}
