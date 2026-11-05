using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using AgriFi.Mobile.Models;

namespace AgriFi.Mobile.Services;

public sealed class ApiClient(HttpClient http, ISecureStore secureStore, IAppSettings settings)
    : IHarvestBatchApi
{
    private const string AccessTokenKey = "agrifi_access_token";
    private const string RefreshTokenKey = "agrifi_refresh_token";
    private const string ApiBaseUrlKey = "agrifi_api_base_url";
    private const string UserIdKey = "agrifi_user_id";
    private readonly SemaphoreSlim _refreshLock = new(1, 1);

    // The API speaks snake_case; bind it to PascalCase DTOs.
    internal static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
    };

    public string ApiBaseUrl =>
        NormalizeApiBaseUrl(settings.Get(ApiBaseUrlKey) ?? settings.DefaultApiBaseUrl);

    public void SetApiBaseUrl(string value) =>
        settings.Set(ApiBaseUrlKey, NormalizeApiBaseUrl(value));

    public static string NormalizeApiBaseUrl(string value)
    {
        if (!Uri.TryCreate(value.Trim(), UriKind.Absolute, out var uri)
            || (uri.Scheme != Uri.UriSchemeHttps && uri.Scheme != Uri.UriSchemeHttp))
        {
            throw new ArgumentException("Enter a valid HTTP or HTTPS API base URL.", nameof(value));
        }

        var isLocalDevelopmentHost = new[] { "localhost", "127.0.0.1", "10.0.2.2", "10.0.3.2" }
            .Contains(uri.Host, StringComparer.OrdinalIgnoreCase);
        if (uri.Scheme == Uri.UriSchemeHttp && !isLocalDevelopmentHost)
        {
            throw new ArgumentException("Use HTTPS except for the local development endpoints.", nameof(value));
        }

        return uri.AbsoluteUri.TrimEnd('/') + "/";
    }

    public async Task<AuthenticatedUser> LoginAsync(string email, string password)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, Endpoint("auth/login/"))
        {
            Content = CreateJsonContent(new { email, password }),
        };
        var response = await http.SendAsync(request);
        await EnsureSuccessAsync(response);

        var tokens = await response.Content.ReadFromJsonAsync<LoginResponse>(JsonOptions)
            ?? throw new InvalidDataException("The API returned an empty login response.");
        if (string.IsNullOrWhiteSpace(tokens.Access) || string.IsNullOrWhiteSpace(tokens.Refresh))
        {
            throw new InvalidDataException("The API response did not contain both authentication tokens.");
        }

        await secureStore.SetAsync(AccessTokenKey, tokens.Access);
        await secureStore.SetAsync(RefreshTokenKey, tokens.Refresh);
        await secureStore.SetAsync(UserIdKey, tokens.User.Id);
        return tokens.User;
    }

    public async Task LogoutAsync()
    {
        var refresh = await secureStore.GetAsync(RefreshTokenKey);
        try
        {
            if (!string.IsNullOrWhiteSpace(refresh))
            {
                using var response = await SendAuthenticatedResponseAsync(
                    HttpMethod.Post,
                    "auth/logout/",
                    new { refresh },
                    retryAfterRefresh: false);
                if (response.StatusCode == HttpStatusCode.Unauthorized)
                {
                    await RefreshAccessTokenAsync(staleAccessToken: null);
                    refresh = await secureStore.GetAsync(RefreshTokenKey);
                    if (string.IsNullOrWhiteSpace(refresh))
                    {
                        throw new ApiRequestException(
                            HttpStatusCode.Unauthorized,
                            "The refresh token was unavailable during sign-out.");
                    }

                    using var retry = await SendAuthenticatedResponseAsync(
                        HttpMethod.Post,
                        "auth/logout/",
                        new { refresh },
                        retryAfterRefresh: false);
                    await EnsureSuccessAsync(retry);
                }
                else
                {
                    await EnsureSuccessAsync(response);
                }
            }
        }
        finally
        {
            secureStore.Remove(AccessTokenKey);
            secureStore.Remove(RefreshTokenKey);
            secureStore.Remove(UserIdKey);
        }
    }

    public async Task<AuthenticatedUser> GetCurrentUserAsync(CancellationToken cancellationToken = default)
    {
        var user = await SendAuthenticatedAsync<AuthenticatedUser>(
            HttpMethod.Get, "auth/me/", cancellationToken: cancellationToken);
        await secureStore.SetAsync(UserIdKey, user.Id);
        return user;
    }

    public Task<string?> GetAuthenticatedUserIdAsync() => secureStore.GetAsync(UserIdKey);

    public async Task<FarmerProfile> GetFarmerProfileAsync() =>
        await SendAuthenticatedAsync<FarmerProfile>(HttpMethod.Get, "auth/profiles/farmer/");

    public async Task<FarmerProfile> SaveFarmerProfileAsync(FarmerProfile profile) =>
        await SendAuthenticatedAsync<FarmerProfile>(
            HttpMethod.Patch,
            "auth/profiles/farmer/",
            new
            {
                display_name = profile.DisplayName,
                region = profile.Region,
                location = profile.Location,
            });

    public Task<List<CropCategory>> GetCategoriesAsync() =>
        GetCollectionAsync<CropCategory>("categories/");

    public async Task<HarvestBatchResponse> CreateHarvestBatchAsync(
        HarvestBatchDraft draft,
        CancellationToken cancellationToken = default)
    {
        var payload = new Dictionary<string, object?>
        {
            ["category"] = draft.CategoryId,
            ["quantity"] = draft.Quantity,
            ["unit_code"] = draft.UnitCode,
            ["harvested_on"] = draft.HarvestedOn,
            ["notes"] = draft.Notes,
            ["client_sync_id"] = draft.ClientSyncId,
        };
        if (!string.IsNullOrWhiteSpace(draft.ResubmissionOfServerBatchId))
        {
            payload["resubmission_of"] = draft.ResubmissionOfServerBatchId;
        }

        // operation_id doubles as the server idempotency key; a replay returns the stored receipt.
        var body = new Dictionary<string, object?>
        {
            ["operation_id"] = draft.ClientSyncId,
            ["operation_type"] = "harvest_batch.create",
            ["schema_version"] = 1,
            ["payload"] = payload,
        };
        var receipt = await SendAuthenticatedAsync<SyncReceipt>(
            HttpMethod.Post, "sync/operations/", body, cancellationToken);
        return receipt.Result;
    }

    public Task<List<HarvestBatchResponse>> GetHarvestBatchesAsync(CancellationToken cancellationToken = default) =>
        GetCollectionAsync<HarvestBatchResponse>("harvest-batches/", cancellationToken);

    public async Task<bool> IsAuthenticatedAsync() =>
        !string.IsNullOrWhiteSpace(await secureStore.GetAsync(RefreshTokenKey));

    private async Task<List<T>> GetCollectionAsync<T>(string path, CancellationToken cancellationToken = default)
    {
        using var response = await SendAuthenticatedResponseAsync(
            HttpMethod.Get, path, cancellationToken: cancellationToken);
        await EnsureSuccessAsync(response);
        using var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
        using var document = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken);

        if (document.RootElement.ValueKind == JsonValueKind.Array)
        {
            return document.RootElement.Deserialize<List<T>>(JsonOptions) ?? [];
        }

        if (document.RootElement.TryGetProperty("results", out var results))
        {
            return results.Deserialize<List<T>>(JsonOptions) ?? [];
        }

        throw new InvalidDataException("The API returned an unsupported collection response.");
    }

    private async Task<T> SendAuthenticatedAsync<T>(
        HttpMethod method,
        string path,
        object? body = null,
        CancellationToken cancellationToken = default)
    {
        using var response = await SendAuthenticatedResponseAsync(method, path, body, cancellationToken: cancellationToken);
        await EnsureSuccessAsync(response);
        return await response.Content.ReadFromJsonAsync<T>(JsonOptions, cancellationToken)
            ?? throw new InvalidDataException("The API returned an empty response.");
    }

    private async Task<HttpResponseMessage> SendAuthenticatedResponseAsync(
        HttpMethod method,
        string path,
        object? body = null,
        bool retryAfterRefresh = true,
        CancellationToken cancellationToken = default)
    {
        using var request = new HttpRequestMessage(method, Endpoint(path));
        if (body is not null)
        {
            request.Content = CreateJsonContent(body);
        }

        var usedToken = await secureStore.GetAsync(AccessTokenKey);
        if (!string.IsNullOrWhiteSpace(usedToken))
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", usedToken);
        }

        var response = await http.SendAsync(request, cancellationToken);
        if (response.StatusCode != HttpStatusCode.Unauthorized || !retryAfterRefresh)
        {
            return response;
        }

        response.Dispose();
        await RefreshAccessTokenAsync(usedToken, cancellationToken);
        return await SendAuthenticatedResponseAsync(
            method, path, body, retryAfterRefresh: false, cancellationToken: cancellationToken);
    }

    private async Task RefreshAccessTokenAsync(string? staleAccessToken, CancellationToken cancellationToken = default)
    {
        await _refreshLock.WaitAsync(cancellationToken);
        try
        {
            // A concurrent request already refreshed; refresh tokens rotate, so don't spend another.
            var current = await secureStore.GetAsync(AccessTokenKey);
            if (staleAccessToken is not null
                && !string.IsNullOrWhiteSpace(current)
                && current != staleAccessToken)
            {
                return;
            }

            var refresh = await secureStore.GetAsync(RefreshTokenKey);
            if (string.IsNullOrWhiteSpace(refresh))
            {
                throw new ApiRequestException(HttpStatusCode.Unauthorized, "Sign in again to continue.");
            }

            using var request = new HttpRequestMessage(HttpMethod.Post, Endpoint("auth/refresh/"))
            {
                Content = CreateJsonContent(new { refresh }),
            };
            using var response = await http.SendAsync(request, cancellationToken);
            await EnsureSuccessAsync(response);
            var tokens = await response.Content.ReadFromJsonAsync<RefreshResponse>(JsonOptions, cancellationToken)
                ?? throw new InvalidDataException("The API returned an empty token refresh response.");

            await secureStore.SetAsync(AccessTokenKey, tokens.Access);
            if (!string.IsNullOrWhiteSpace(tokens.Refresh))
            {
                await secureStore.SetAsync(RefreshTokenKey, tokens.Refresh);
            }
        }
        finally
        {
            _refreshLock.Release();
        }
    }

    private Uri Endpoint(string path) => new(new Uri(ApiBaseUrl, UriKind.Absolute), path);

    private static HttpContent CreateJsonContent<T>(T value)
    {
        // JsonContent streams its payload on Android, which may use chunked transfer encoding.
        // Buffering lets simple WSGI servers (including Django runserver) read the request body.
        var content = new ByteArrayContent(JsonSerializer.SerializeToUtf8Bytes(value, JsonOptions));
        content.Headers.ContentType = new MediaTypeHeaderValue("application/json");
        return content;
    }

    private static async Task EnsureSuccessAsync(HttpResponseMessage response)
    {
        if (response.IsSuccessStatusCode)
        {
            return;
        }

        var body = await response.Content.ReadAsStringAsync();
        throw new ApiRequestException(response.StatusCode, body);
    }

    private sealed record LoginResponse(string Access, string Refresh, AuthenticatedUser User);
    private sealed record RefreshResponse(string Access, string? Refresh);
}

public sealed class ApiRequestException(HttpStatusCode statusCode, string responseBody)
    : Exception(GetSafeUserMessage(statusCode, responseBody))
{
    public HttpStatusCode StatusCode { get; } = statusCode;
    public string ResponseBody { get; } = responseBody;

    // Standard server envelope: {code, message, detail, request_id, fields?}.
    private readonly (string? Code, string? Message, string? RequestId) _envelope = ParseEnvelope(responseBody);
    private readonly string _userMessage = GetSafeUserMessage(statusCode, responseBody);

    public string? ErrorCode => _envelope.Code;
    public string? RequestId => _envelope.RequestId;
    public string UserMessage => _userMessage;

    private static string GetSafeUserMessage(HttpStatusCode statusCode, string body)
    {
        var envelope = ParseEnvelope(body);
        if (!string.IsNullOrWhiteSpace(envelope.Message))
        {
            return envelope.Message!;
        }

        var trimmed = body.Trim();
        if (trimmed.Length is > 0 and <= 300
            && !trimmed.StartsWith('<')
            && !trimmed.StartsWith('{')
            && !trimmed.StartsWith('['))
        {
            return trimmed;
        }

        return $"API request failed with {(int)statusCode} ({statusCode}).";
    }

    private static (string? Code, string? Message, string? RequestId) ParseEnvelope(string body)
    {
        try
        {
            using var document = System.Text.Json.JsonDocument.Parse(body);
            if (document.RootElement.ValueKind != System.Text.Json.JsonValueKind.Object)
            {
                return (null, null, null);
            }

            string? Read(string name) =>
                document.RootElement.TryGetProperty(name, out var value)
                && value.ValueKind == System.Text.Json.JsonValueKind.String
                    ? value.GetString()
                    : null;

            var message = Read("message") ?? Read("detail");
            if (string.IsNullOrWhiteSpace(message))
            {
                message = document.RootElement.TryGetProperty("fields", out var fields)
                    ? ReadFirstError(fields)
                    : ReadFirstError(document.RootElement);
            }

            return (Read("code"), message, Read("request_id"));
        }
        catch (System.Text.Json.JsonException)
        {
            return (null, null, null);
        }
    }

    private static string? ReadFirstError(System.Text.Json.JsonElement element)
    {
        if (element.ValueKind == System.Text.Json.JsonValueKind.String)
        {
            return element.GetString();
        }

        if (element.ValueKind == System.Text.Json.JsonValueKind.Array)
        {
            foreach (var item in element.EnumerateArray())
            {
                var message = ReadFirstError(item);
                if (!string.IsNullOrWhiteSpace(message))
                {
                    return message;
                }
            }
        }
        else if (element.ValueKind == System.Text.Json.JsonValueKind.Object)
        {
            foreach (var property in element.EnumerateObject())
            {
                if (property.Name is "code" or "request_id" or "message" or "detail")
                {
                    continue;
                }

                var message = ReadFirstError(property.Value);
                if (!string.IsNullOrWhiteSpace(message))
                {
                    return message;
                }
            }
        }

        return null;
    }
}

public sealed record AuthenticatedUser(string Id, string Email, string[] Roles);

public sealed record SyncReceipt(
    string OperationId, string OperationType, string Status, bool Replayed, string ResourceId, HarvestBatchResponse Result);

public sealed record CropCategory(string Id, string Name, bool IsActive);

public sealed record HarvestBatchResponse(
    string Id,
    string ClientSyncId,
    string Status,
    string? RejectionReason = null);

public sealed record FarmerProfile(string DisplayName, string Region, string Location);
