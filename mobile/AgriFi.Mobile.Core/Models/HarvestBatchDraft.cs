using SQLite;

namespace AgriFi.Mobile.Models;

public static class DraftStatus
{
    public const string Pending = "pending";
    public const string Submitted = "submitted";
    public const string Accepted = "accepted";
    public const string Rejected = "rejected";
    public const string Failed = "failed";
}

/// <summary>
/// A locally recorded harvest batch. It is an outbox entry only: it never counts as stock
/// until the server accepts it.
/// </summary>
public sealed class HarvestBatchDraft
{
    [PrimaryKey]
    public string Id { get; set; } = Guid.NewGuid().ToString();

    [Indexed(Unique = true)]
    public string ClientSyncId { get; set; } = Guid.NewGuid().ToString();

    [Indexed]
    public string OwnerUserId { get; set; } = string.Empty;

    public string CategoryId { get; set; } = string.Empty;
    public string Quantity { get; set; } = string.Empty;
    public string UnitCode { get; set; } = "kg";
    public string HarvestedOn { get; set; } = string.Empty;
    public string Notes { get; set; } = string.Empty;
    public string SyncStatus { get; set; } = DraftStatus.Pending;
    public string LastError { get; set; } = string.Empty;
    public string CreatedAtUtc { get; set; } = DateTimeOffset.UtcNow.ToString("O");

    /// <summary>Server batch id, known once the server has reported this draft.</summary>
    public string ServerBatchId { get; set; } = string.Empty;

    public string RejectionReason { get; set; } = string.Empty;

    /// <summary>Server id of the rejected batch this draft corrects (sent as resubmission_of).</summary>
    public string ResubmissionOfServerBatchId { get; set; } = string.Empty;

    /// <summary>Local id of the draft that corrected this rejected draft.</summary>
    public string CorrectedByDraftId { get; set; } = string.Empty;

    /// <summary>Number of times a create request was sent; above zero the server outcome may be unknown.</summary>
    public int AttemptCount { get; set; }

    /// <summary>Consecutive retryable failures since the last success or manual retry.</summary>
    public int RetryCount { get; set; }

    /// <summary>ISO-8601 UTC time before which sync leaves this draft alone; empty means send now.</summary>
    public string NextAttemptAtUtc { get; set; } = string.Empty;
}
