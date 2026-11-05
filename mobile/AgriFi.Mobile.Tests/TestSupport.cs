using System.Net;
using System.Text;
using System.Text.Json;
using AgriFi.Mobile.Models;
using AgriFi.Mobile.Services;

namespace AgriFi.Mobile.Tests;

public sealed class MemorySecureStore : ISecureStore
{
    private readonly Dictionary<string, string> _values = [];

    public Task<string?> GetAsync(string key)
    {
        lock (_values)
        {
            return Task.FromResult(_values.GetValueOrDefault(key));
        }
    }

    public Task SetAsync(string key, string value)
    {
        lock (_values)
        {
            _values[key] = value;
        }

        return Task.CompletedTask;
    }

    public void Remove(string key)
    {
        lock (_values)
        {
            _values.Remove(key);
        }
    }
}

public sealed class MemorySettings : IAppSettings
{
    private readonly Dictionary<string, string> _values = [];
    public string DefaultApiBaseUrl => "http://localhost:8000/api/v1/";
    public string? Get(string key) => _values.GetValueOrDefault(key);
    public void Set(string key, string value) => _values[key] = value;
}

public sealed record ServerBatch(
    string Id,
    string ClientSyncId,
    string Quantity,
    string? ResubmissionOf)
{
    public string Status { get; set; } = "submitted";
    public string RejectionReason { get; set; } = string.Empty;
}

/// <summary>
/// In-process stand-in for the Django API: snake_case JSON, JWT-style 401s, rotating
/// refresh tokens and idempotent batch creation keyed by client_sync_id.
/// </summary>
public sealed class FakeServer : HttpMessageHandler
{
    private readonly object _gate = new();
    private int _tokenCounter;

    public string UserId { get; set; } = "user-1";
    public string[] Roles { get; set; } = ["farmer"];
    public string ValidAccess { get; private set; } = "access-0";
    public string ValidRefresh { get; private set; } = "refresh-0";
    public bool RefreshRejected { get; set; }
    public bool Offline { get; set; }
    public bool LoseNextCreateResponse { get; set; }
    public Func<string, bool>? RejectQuantity { get; set; }
    public bool UseErrorEnvelope { get; set; }
    public bool ThrottleCreates { get; set; }
    public TaskCompletionSource? HoldCreates { get; set; }
    public bool LoginHadContentLength { get; private set; }
    public bool LoginUsedChunkedTransfer { get; private set; }

    public List<ServerBatch> Batches { get; } = [];
    public int CreateRequests { get; private set; }
    public int RefreshRequests { get; private set; }

    public void ExpireAccessToken() => ValidAccess = "expired-" + Interlocked.Increment(ref _tokenCounter);

    public void Review(string clientSyncId, string status, string reason = "")
    {
        lock (_gate)
        {
            var batch = Batches.Single(item => item.ClientSyncId == clientSyncId);
            batch.Status = status;
            batch.RejectionReason = reason;
        }
    }

    protected override async Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        if (Offline)
        {
            throw new HttpRequestException("Network unreachable.");
        }

        var path = request.RequestUri!.AbsolutePath;
        var body = request.Content is null ? string.Empty : await request.Content.ReadAsStringAsync(cancellationToken);

        if (path.EndsWith("/auth/login/", StringComparison.Ordinal))
        {
            LoginHadContentLength = request.Content?.Headers.ContentLength is not null;
            LoginUsedChunkedTransfer = request.Headers.TransferEncodingChunked == true;
            return Login(body);
        }

        if (path.EndsWith("/auth/refresh/", StringComparison.Ordinal))
        {
            return Refresh(body);
        }

        if (request.Headers.Authorization?.Parameter != ValidAccess)
        {
            return Json(HttpStatusCode.Unauthorized, new { detail = "Token is invalid or expired." });
        }

        if (path.EndsWith("/auth/me/", StringComparison.Ordinal))
        {
            return Json(HttpStatusCode.OK, new { id = UserId, email = "farmer@example.com", roles = Roles });
        }

        if (path.EndsWith("/sync/operations/", StringComparison.Ordinal) && request.Method == HttpMethod.Post)
        {
            return await SyncOperationAsync(body, cancellationToken);
        }

        if (path.EndsWith("/harvest-batches/", StringComparison.Ordinal))
        {
            return request.Method == HttpMethod.Post
                ? await CreateBatchAsync(body)
                : ListBatches();
        }

        return Json(HttpStatusCode.NotFound, new { detail = "Not found." });
    }

    public int SyncOperationRequests { get; private set; }
    public string? LastSyncBody { get; private set; }
    public string? SyncReceiptOverride { get; set; }
    public int ServerErrorsRemaining { get; set; }
    public bool HangSyncUntilCancelled { get; set; }

    private async Task<HttpResponseMessage> SyncOperationAsync(string body, CancellationToken cancellationToken)
    {
        SyncOperationRequests++;
        LastSyncBody = body;
        if (HangSyncUntilCancelled)
        {
            await Task.Delay(Timeout.Infinite, cancellationToken);
        }

        if (ServerErrorsRemaining > 0)
        {
            ServerErrorsRemaining--;
            return Json(HttpStatusCode.InternalServerError, new { code = "server_error", message = "Boom." });
        }
        if (SyncReceiptOverride is not null)
        {
            return new HttpResponseMessage(HttpStatusCode.Created)
            {
                Content = new StringContent(SyncReceiptOverride, System.Text.Encoding.UTF8, "application/json"),
            };
        }

        using var envelope = JsonDocument.Parse(body);
        var root = envelope.RootElement;
        var operationId = root.GetProperty("operation_id").GetString()!;
        if (root.GetProperty("operation_type").GetString() != "harvest_batch.create"
            || root.GetProperty("schema_version").GetInt32() != 1)
        {
            return Json(HttpStatusCode.BadRequest, new { code = "validation_error", message = "Unsupported operation." });
        }

        var payload = root.GetProperty("payload");
        var inner = await CreateBatchAsync(payload.GetRawText());
        if (!inner.IsSuccessStatusCode)
        {
            return inner;
        }

        var result = JsonDocument.Parse(await inner.Content.ReadAsStringAsync()).RootElement.Clone();
        return Json(inner.StatusCode, new
        {
            operation_id = operationId,
            operation_type = "harvest_batch.create",
            schema_version = 1,
            status = "applied",
            replayed = inner.StatusCode == HttpStatusCode.OK,
            resource_id = result.GetProperty("id").GetString(),
            result,
        });
    }

    private HttpResponseMessage Login(string body)
    {
        using var document = JsonDocument.Parse(body);
        if (document.RootElement.GetProperty("password").GetString() != "correct-password")
        {
            return Json(HttpStatusCode.Unauthorized, new { detail = "Invalid credentials." });
        }

        return Json(HttpStatusCode.OK, new
        {
            access = ValidAccess,
            refresh = ValidRefresh,
            user = new { id = UserId, email = "farmer@example.com", roles = Roles },
        });
    }

    private HttpResponseMessage Refresh(string body)
    {
        RefreshRequests++;
        using var document = JsonDocument.Parse(body);
        if (RefreshRejected || document.RootElement.GetProperty("refresh").GetString() != ValidRefresh)
        {
            return Json(HttpStatusCode.Unauthorized, new { detail = "Token is invalid or expired." });
        }

        var number = Interlocked.Increment(ref _tokenCounter);
        ValidAccess = $"access-{number}";
        ValidRefresh = $"refresh-{number}";
        return Json(HttpStatusCode.OK, new { access = ValidAccess, refresh = ValidRefresh });
    }

    private async Task<HttpResponseMessage> CreateBatchAsync(string body)
    {
        if (HoldCreates is not null)
        {
            await HoldCreates.Task;
        }

        using var document = JsonDocument.Parse(body);
        var root = document.RootElement;
        var key = root.GetProperty("client_sync_id").GetString()!;
        var quantity = root.GetProperty("quantity").GetString()!;
        var resubmission = root.TryGetProperty("resubmission_of", out var value) ? value.GetString() : null;

        HttpResponseMessage response;
        lock (_gate)
        {
            CreateRequests++;
            var existing = Batches.FirstOrDefault(item => item.ClientSyncId == key);
            if (ThrottleCreates)
            {
                response = Json((HttpStatusCode)429, new { code = "throttled", message = "Too many requests.", request_id = "req-429" });
            }
            else if (existing is not null)
            {
                response = existing.Quantity == quantity && existing.ResubmissionOf == resubmission
                    ? Json(HttpStatusCode.OK, Serialize(existing))
                    : Json(HttpStatusCode.Conflict, new { detail = "Idempotency key reused with a different request." });
            }
            else if (RejectQuantity?.Invoke(quantity) == true)
            {
                response = UseErrorEnvelope
                    ? Json(HttpStatusCode.BadRequest, new
                    {
                        code = "validation_error",
                        message = "Quantity is not acceptable.",
                        request_id = "req-123",
                        fields = new { quantity = new[] { "Quantity is not acceptable." } },
                    })
                    : Json(HttpStatusCode.BadRequest, new { quantity = new[] { "Quantity is not acceptable." } });
            }
            else if (resubmission is not null && !CanCorrect(resubmission))
            {
                response = Json(HttpStatusCode.BadRequest, new { resubmission_of = new[] { "Not a rejected batch of yours." } });
            }
            else
            {
                var created = new ServerBatch(Guid.NewGuid().ToString(), key, quantity, resubmission);
                Batches.Add(created);
                response = Json(HttpStatusCode.Created, Serialize(created));
            }
        }

        if (LoseNextCreateResponse && response.IsSuccessStatusCode)
        {
            LoseNextCreateResponse = false;
            Offline = true;
            throw new HttpRequestException("Connection dropped after the server processed the request.");
        }

        return response;
    }

    private bool CanCorrect(string originalId) =>
        Batches.Any(item => item.Id == originalId && item.Status == "rejected")
        && Batches.All(item => item.ResubmissionOf != originalId);

    private HttpResponseMessage ListBatches()
    {
        lock (_gate)
        {
            return Json(HttpStatusCode.OK, new { count = Batches.Count, results = Batches.Select(Serialize).ToArray() });
        }
    }

    private static object Serialize(ServerBatch batch) => new
    {
        id = batch.Id,
        client_sync_id = batch.ClientSyncId,
        status = batch.Status,
        rejection_reason = batch.RejectionReason,
        resubmission_of = batch.ResubmissionOf,
    };

    private static HttpResponseMessage Json(HttpStatusCode status, object payload) =>
        new(status)
        {
            Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json"),
        };
}

/// <summary>Wires the real ApiClient, OutboxStore and sync service to a FakeServer and a temp SQLite file.</summary>
public sealed class Harness : IDisposable
{
    private readonly string _directory = Directory.CreateTempSubdirectory("agrifi-tests-").FullName;
    private readonly SyncPolicy _policy;
    private readonly TimeProvider? _clock;

    public Harness(SyncPolicy? policy = null, TimeProvider? clock = null)
    {
        _policy = policy ?? SyncPolicy.NoBackoff;
        _clock = clock;
        DatabasePath = Path.Combine(_directory, "outbox.db3");
        Server = new FakeServer();
        Store = new MemorySecureStore();
        Build();
    }

    public string DatabasePath { get; }
    public FakeServer Server { get; }
    public MemorySecureStore Store { get; }
    public ApiClient Api { get; private set; } = null!;
    public OutboxStore Outbox { get; private set; } = null!;
    public HarvestBatchSyncService Sync { get; private set; } = null!;

    public async Task SignInAsync() => await Api.LoginAsync("farmer@example.com", "correct-password");

    /// <summary>Simulates closing and reopening the app: new objects, same database file and secure store.</summary>
    public async Task RestartAsync()
    {
        await Outbox.CloseAsync();
        Build();
    }

    public async Task<HarvestBatchDraft> AddDraftAsync(string quantity = "10", string owner = "user-1")
    {
        var draft = new HarvestBatchDraft
        {
            OwnerUserId = owner,
            CategoryId = "category-1",
            Quantity = quantity,
            UnitCode = "kg",
            HarvestedOn = "2026-01-15",
            Notes = "test",
        };
        await Outbox.SaveAsync(draft);
        return draft;
    }

    public static DraftFields Fields(string quantity) => new("category-1", quantity, "kg", "2026-01-15", "edited");

    private void Build()
    {
        Api = new ApiClient(new HttpClient(Server), Store, new MemorySettings());
        Outbox = new OutboxStore(DatabasePath);
        Sync = new HarvestBatchSyncService(Api, Outbox, _policy, _clock);
    }

    public void Dispose()
    {
        Outbox.CloseAsync().GetAwaiter().GetResult();
        try
        {
            Directory.Delete(_directory, recursive: true);
        }
        catch (IOException)
        {
        }
    }
}
