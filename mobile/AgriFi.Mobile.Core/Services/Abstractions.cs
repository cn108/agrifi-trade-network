using AgriFi.Mobile.Models;

namespace AgriFi.Mobile.Services;

public interface ISecureStore
{
    Task<string?> GetAsync(string key);
    Task SetAsync(string key, string value);
    void Remove(string key);
}

public interface IAppSettings
{
    string DefaultApiBaseUrl { get; }
    string? Get(string key);
    void Set(string key, string value);
}

/// <summary>The server calls the sync service needs; faked in tests.</summary>
public interface IHarvestBatchApi
{
    Task<AuthenticatedUser> GetCurrentUserAsync(CancellationToken cancellationToken = default);
    Task<HarvestBatchResponse> CreateHarvestBatchAsync(HarvestBatchDraft draft, CancellationToken cancellationToken = default);
    Task<List<HarvestBatchResponse>> GetHarvestBatchesAsync(CancellationToken cancellationToken = default);
}
