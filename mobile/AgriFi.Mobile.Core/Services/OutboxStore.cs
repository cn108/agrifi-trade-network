using AgriFi.Mobile.Models;
using SQLite;

namespace AgriFi.Mobile.Services;

public sealed record DraftFields(
    string CategoryId,
    string Quantity,
    string UnitCode,
    string HarvestedOn,
    string Notes);

public sealed class OutboxStore(string databasePath)
{
    private readonly SQLiteAsyncConnection _database = new(databasePath);
    private readonly SemaphoreSlim _initialization = new(1, 1);
    private bool _initialized;

    public async Task InitializeAsync()
    {
        if (_initialized)
        {
            return;
        }

        await _initialization.WaitAsync();
        try
        {
            if (!_initialized)
            {
                var columns = await _database.GetTableInfoAsync(nameof(HarvestBatchDraft));
                if (columns.Count > 0
                    && columns.All(column => column.Name != nameof(HarvestBatchDraft.OwnerUserId)))
                {
                    await _database.ExecuteAsync(
                        "ALTER TABLE HarvestBatchDraft ADD COLUMN OwnerUserId TEXT NOT NULL DEFAULT ''");
                }

                // CreateTable adds any columns introduced after the first release.
                await _database.CreateTableAsync<HarvestBatchDraft>();
                await _database.CreateTableAsync<CachedCropCategory>();
                _initialized = true;
            }
        }
        finally
        {
            _initialization.Release();
        }
    }

    public Task CloseAsync() => _database.CloseAsync();

    /// <summary>Records a brand-new draft. A duplicate Id or ClientSyncId is rejected, never overwritten.</summary>
    public async Task SaveAsync(HarvestBatchDraft draft)
    {
        await InitializeAsync();
        await _database.InsertAsync(draft);
    }

    public async Task<HarvestBatchDraft?> FindAsync(string id)
    {
        await InitializeAsync();
        return await _database.Table<HarvestBatchDraft>().Where(item => item.Id == id).FirstOrDefaultAsync();
    }

    public async Task<List<HarvestBatchDraft>> GetAllAsync(string ownerUserId)
    {
        await InitializeAsync();
        return await _database.Table<HarvestBatchDraft>()
            .Where(item => item.OwnerUserId == ownerUserId)
            .OrderByDescending(item => item.CreatedAtUtc)
            .ToListAsync();
    }

    public async Task<List<HarvestBatchDraft>> GetPendingAsync(string ownerUserId)
    {
        await InitializeAsync();
        return await _database.Table<HarvestBatchDraft>()
            .Where(item => item.SyncStatus == DraftStatus.Pending && item.OwnerUserId == ownerUserId)
            .OrderBy(item => item.CreatedAtUtc)
            .ToListAsync();
    }

    public async Task UpdateAsync(HarvestBatchDraft draft)
    {
        await InitializeAsync();
        await _database.UpdateAsync(draft);
    }

    public async Task RetryFailedAsync(string ownerUserId)
    {
        await InitializeAsync();
        var failed = await _database.Table<HarvestBatchDraft>()
            .Where(item => item.SyncStatus == DraftStatus.Failed && item.OwnerUserId == ownerUserId)
            .ToListAsync();

        foreach (var draft in failed)
        {
            draft.SyncStatus = DraftStatus.Pending;
            draft.LastError = string.Empty;
            draft.RetryCount = 0;
            draft.NextAttemptAtUtc = string.Empty;
            await _database.UpdateAsync(draft);
        }
    }

    /// <summary>
    /// Edits a draft that the server has not seen a decision for.
    /// Never-sent pending drafts keep their key. Failed drafts (the server persisted nothing)
    /// get a fresh key. Anything whose outcome is unknown is not editable, because changing
    /// the payload under the same key conflicts and changing the key could duplicate it.
    /// </summary>
    public async Task<HarvestBatchDraft> EditDraftAsync(string draftId, string ownerUserId, DraftFields fields)
    {
        await InitializeAsync();
        var draft = await FindOwnedAsync(draftId, ownerUserId);
        if (draft.SyncStatus == DraftStatus.Pending && draft.AttemptCount == 0)
        {
            Apply(draft, fields);
        }
        else if (draft.SyncStatus == DraftStatus.Failed)
        {
            Apply(draft, fields);
            draft.ClientSyncId = Guid.NewGuid().ToString();
            draft.SyncStatus = DraftStatus.Pending;
            draft.AttemptCount = 0;
            draft.RetryCount = 0;
            draft.NextAttemptAtUtc = string.Empty;
            draft.LastError = string.Empty;
        }
        else
        {
            throw new InvalidOperationException(
                "This batch can no longer be edited. Rejected batches are corrected by resubmitting.");
        }

        await _database.UpdateAsync(draft);
        return draft;
    }

    /// <summary>
    /// Creates a new draft that corrects a server-rejected one. The rejected draft stays
    /// as history and is linked to its correction; the new draft uses a new key.
    /// </summary>
    public async Task<HarvestBatchDraft> CreateCorrectionAsync(
        string rejectedDraftId,
        string ownerUserId,
        DraftFields fields)
    {
        await InitializeAsync();
        var original = await FindOwnedAsync(rejectedDraftId, ownerUserId);
        if (original.SyncStatus != DraftStatus.Rejected || string.IsNullOrWhiteSpace(original.ServerBatchId))
        {
            throw new InvalidOperationException("Only batches rejected by the server can be corrected.");
        }

        if (!string.IsNullOrWhiteSpace(original.CorrectedByDraftId))
        {
            throw new InvalidOperationException("This rejected batch has already been corrected.");
        }

        var correction = new HarvestBatchDraft
        {
            OwnerUserId = ownerUserId,
            ResubmissionOfServerBatchId = original.ServerBatchId,
        };
        Apply(correction, fields);
        original.CorrectedByDraftId = correction.Id;

        await _database.RunInTransactionAsync(connection =>
        {
            connection.Insert(correction);
            connection.Update(original);
        });
        return correction;
    }

    public async Task SaveCategoriesAsync(IEnumerable<CachedCropCategory> categories)
    {
        await InitializeAsync();
        await _database.RunInTransactionAsync(connection =>
        {
            connection.DeleteAll<CachedCropCategory>();
            connection.InsertAll(categories);
        });
    }

    public async Task<List<CachedCropCategory>> GetActiveCategoriesAsync()
    {
        await InitializeAsync();
        return await _database.Table<CachedCropCategory>()
            .Where(category => category.IsActive)
            .OrderBy(category => category.Name)
            .ToListAsync();
    }

    private async Task<HarvestBatchDraft> FindOwnedAsync(string draftId, string ownerUserId)
    {
        var draft = await _database.Table<HarvestBatchDraft>()
            .Where(item => item.Id == draftId && item.OwnerUserId == ownerUserId)
            .FirstOrDefaultAsync();
        return draft ?? throw new InvalidOperationException("The batch was not found on this device.");
    }

    private static void Apply(HarvestBatchDraft draft, DraftFields fields)
    {
        draft.CategoryId = fields.CategoryId;
        draft.Quantity = fields.Quantity;
        draft.UnitCode = fields.UnitCode;
        draft.HarvestedOn = fields.HarvestedOn;
        draft.Notes = fields.Notes;
    }
}
