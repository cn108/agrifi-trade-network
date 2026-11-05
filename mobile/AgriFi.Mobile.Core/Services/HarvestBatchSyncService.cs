using System.Net;
using AgriFi.Mobile.Models;

namespace AgriFi.Mobile.Services;

/// <summary>
/// Submits outbox drafts to the server. The server is authoritative: this class never
/// derives stock and only mirrors the review status the server reports.
/// </summary>
public sealed class HarvestBatchSyncService(
    IHarvestBatchApi api,
    OutboxStore outbox,
    SyncPolicy? policy = null,
    TimeProvider? clock = null)
{
    private const int MaxServerMessageLength = 300;
    private readonly SemaphoreSlim _syncLock = new(1, 1);
    private readonly SyncPolicy _policy = policy ?? SyncPolicy.Default;
    private readonly TimeProvider _clock = clock ?? TimeProvider.System;

    public async Task<int> SyncPendingAsync(CancellationToken cancellationToken = default)
    {
        // One pass at a time so overlapping triggers cannot send the same draft twice.
        await _syncLock.WaitAsync(cancellationToken);
        try
        {
            return await SyncCoreAsync(cancellationToken);
        }
        finally
        {
            _syncLock.Release();
        }
    }

    private async Task<int> SyncCoreAsync(CancellationToken cancellationToken)
    {
        var user = await api.GetCurrentUserAsync(cancellationToken);
        if (!user.Roles.Contains("farmer", StringComparer.Ordinal))
        {
            throw new ApiRequestException(HttpStatusCode.Forbidden, "Only farmer accounts can sync harvest batches.");
        }

        var now = _clock.GetUtcNow();
        var pending = (await outbox.GetPendingAsync(user.Id)).Where(draft => IsDue(draft, now)).ToList();
        var completed = 0;

        foreach (var draft in pending)
        {
            cancellationToken.ThrowIfCancellationRequested();
            draft.AttemptCount++;
            await outbox.UpdateAsync(draft);
            try
            {
                var result = await api.CreateHarvestBatchAsync(draft, cancellationToken);
                ApplyServerState(draft, result);
                draft.RetryCount = 0;
                draft.NextAttemptAtUtc = string.Empty;
                await outbox.UpdateAsync(draft);
                completed++;
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                // The request may have reached the server; the draft stays queued under the same key.
                draft.LastError = "Sync was cancelled. This batch remains queued with the same operation ID.";
                await outbox.UpdateAsync(draft);
                throw;
            }
            catch (ApiRequestException exception) when (IsPermanentClientError(exception.StatusCode))
            {
                draft.SyncStatus = DraftStatus.Failed;
                draft.LastError = "The server rejected this batch: " + Truncate(exception.UserMessage)
                    + (exception.RequestId is { Length: > 0 } requestId ? $" (ref {requestId})" : string.Empty);
                await outbox.UpdateAsync(draft);
            }
            catch (ApiRequestException exception) when (exception.StatusCode == HttpStatusCode.Unauthorized)
            {
                // Expired or revoked credentials are not the draft's fault: no backoff, no retry budget spent.
                draft.LastError = "Authentication is unavailable. Sign in again; this batch remains queued.";
                await outbox.UpdateAsync(draft);
                break;
            }
            catch (ApiRequestException exception)
            {
                var throttled = exception.StatusCode == (HttpStatusCode)429;
                await RecordRetryableFailureAsync(
                    draft,
                    throttled
                        ? "The server asked the app to slow down. This batch remains queued and will be retried."
                        : "The server could not confirm this request. It remains queued with the same operation ID.");
                if (throttled)
                {
                    break;
                }
            }
            catch (HttpRequestException)
            {
                await RecordRetryableFailureAsync(
                    draft,
                    "The API could not be reached. This batch remains queued with the same operation ID.");
                break;
            }
            catch (TaskCanceledException)
            {
                await RecordRetryableFailureAsync(
                    draft,
                    "The request timed out. This batch remains queued with the same operation ID.");
                break;
            }
        }

        try
        {
            await RefreshServerStatusesAsync(user.Id, cancellationToken);
        }
        catch (Exception exception) when (
            exception is HttpRequestException or ApiRequestException
            || (exception is TaskCanceledException && !cancellationToken.IsCancellationRequested))
        {
            // Submissions already succeeded; statuses are refreshed on the next sync.
        }

        return completed;
    }

    private bool IsDue(HarvestBatchDraft draft, DateTimeOffset now) =>
        string.IsNullOrEmpty(draft.NextAttemptAtUtc)
        || !DateTimeOffset.TryParse(draft.NextAttemptAtUtc, out var due)
        || due <= now;

    private async Task RecordRetryableFailureAsync(HarvestBatchDraft draft, string message)
    {
        draft.RetryCount++;
        if (draft.RetryCount >= _policy.MaxRetryableAttempts)
        {
            // Parked, not lost: manual retry resends under the same operation ID, which the server dedupes.
            draft.SyncStatus = DraftStatus.Failed;
            draft.LastError = $"Gave up after {draft.RetryCount} attempts. Retry when the connection is better; "
                + "the same operation ID is reused so nothing is duplicated.";
            draft.NextAttemptAtUtc = string.Empty;
        }
        else
        {
            draft.LastError = message;
            draft.NextAttemptAtUtc = _clock.GetUtcNow().Add(_policy.DelayFor(draft.RetryCount)).ToString("O");
        }

        await outbox.UpdateAsync(draft);
    }

    public Task RetryFailedAsync(string ownerUserId) => outbox.RetryFailedAsync(ownerUserId);

    private async Task RefreshServerStatusesAsync(string ownerUserId, CancellationToken cancellationToken)
    {
        var serverBatches = await api.GetHarvestBatchesAsync(cancellationToken);
        var byOperationId = serverBatches
            .Where(batch => !string.IsNullOrWhiteSpace(batch.ClientSyncId))
            .GroupBy(batch => batch.ClientSyncId)
            .ToDictionary(group => group.Key, group => group.First());

        foreach (var draft in await outbox.GetAllAsync(ownerUserId))
        {
            if (byOperationId.TryGetValue(draft.ClientSyncId, out var server)
                && (draft.SyncStatus != server.Status
                    || draft.ServerBatchId != server.Id
                    || draft.RejectionReason != (server.RejectionReason ?? string.Empty)))
            {
                ApplyServerState(draft, server);
                await outbox.UpdateAsync(draft);
            }
        }
    }

    private static void ApplyServerState(HarvestBatchDraft draft, HarvestBatchResponse server)
    {
        draft.SyncStatus = server.Status;
        draft.ServerBatchId = server.Id;
        draft.RejectionReason = server.RejectionReason ?? string.Empty;
        draft.LastError = server.Status == DraftStatus.Rejected
            ? (string.IsNullOrWhiteSpace(draft.RejectionReason)
                ? "Rejected by operations (no reason given)."
                : draft.RejectionReason)
            : string.Empty;
    }

    private static string Truncate(string value) =>
        value.Length <= MaxServerMessageLength ? value : value[..MaxServerMessageLength] + "…";

    private static bool IsPermanentClientError(HttpStatusCode statusCode) =>
        (int)statusCode is >= 400 and < 500
        && statusCode is not HttpStatusCode.Unauthorized
        && statusCode is not HttpStatusCode.RequestTimeout
        && (int)statusCode != 429;
}
