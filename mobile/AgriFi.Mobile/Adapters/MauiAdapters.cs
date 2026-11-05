using AgriFi.Mobile.Services;

namespace AgriFi.Mobile.Adapters;

public sealed class MauiSecureStore : ISecureStore
{
    public Task<string?> GetAsync(string key) => SecureStorage.Default.GetAsync(key);
    public Task SetAsync(string key, string value) => SecureStorage.Default.SetAsync(key, value);
    public void Remove(string key) => SecureStorage.Default.Remove(key);
}

public sealed class MauiAppSettings : IAppSettings
{
#if ANDROID
    public string DefaultApiBaseUrl => "http://10.0.2.2:8000/api/v1/";
#else
    public string DefaultApiBaseUrl => "http://localhost:8000/api/v1/";
#endif

    public string? Get(string key) => Preferences.ContainsKey(key) ? Preferences.Get(key, string.Empty) : null;
    public void Set(string key, string value) => Preferences.Set(key, value);
}
