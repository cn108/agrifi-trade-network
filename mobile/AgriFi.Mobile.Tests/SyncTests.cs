using System.Net;
using AgriFi.Mobile.Models;
using AgriFi.Mobile.Services;

namespace AgriFi.Mobile.Tests;

public class OutboxPersistenceTests
{
    [Fact]
    public async Task Draft_survives_app_restart_with_same_key_and_pending_status()
    {
        using var h = new Harness();
        var draft = await h.AddDraftAsync("12.5");

        await h.RestartAsync();

        var stored = await h.Outbox.GetPendingAsync("user-1");
        var single = Assert.Single(stored);
        Assert.Equal(draft.Id, single.Id);
        Assert.Equal(draft.ClientSyncId, single.ClientSyncId);
        Assert.Equal("12.5", single.Quantity);
        Assert.Equal(DraftStatus.Pending, single.SyncStatus);
    }

    [Fact]
    public async Task Client_sync_id_is_unique_per_draft_and_stable_across_updates()
    {
        using var h = new Harness();
        var first = await h.AddDraftAsync();
        var second = await h.AddDraftAsync();
        Assert.NotEqual(first.ClientSyncId, second.ClientSyncId);

        first.LastError = "changed";
        await h.Outbox.UpdateAsync(first);
        Assert.Equal(first.ClientSyncId, (await h.Outbox.FindAsync(first.Id))!.ClientSyncId);
    }

    [Fact]
    public async Task Saving_a_duplicate_sync_id_is_rejected_not_overwritten()
    {
        using var h = new Harness();
        var original = await h.AddDraftAsync("5");
        var clash = new HarvestBatchDraft { OwnerUserId = "user-1", ClientSyncId = original.ClientSyncId, Quantity = "99" };

        await Assert.ThrowsAnyAsync<Exception>(() => h.Outbox.SaveAsync(clash));

        Assert.Equal("5", (await h.Outbox.FindAsync(original.Id))!.Quantity);
    }

    [Fact]
    public async Task Drafts_are_isolated_per_owner()
    {
        using var h = new Harness();
        await h.AddDraftAsync(owner: "user-1");
        await h.AddDraftAsync(owner: "user-2");

        Assert.Single(await h.Outbox.GetAllAsync("user-1"));
        Assert.Single(await h.Outbox.GetPendingAsync("user-2"));
        Assert.Empty(await h.Outbox.GetAllAsync("someone-else"));
    }

    [Fact]
    public async Task Category_cache_is_replaced_and_only_active_returned()
    {
        using var h = new Harness();
        await h.Outbox.SaveCategoriesAsync(
        [
            new CachedCropCategory { Id = "1", Name = "Maize", IsActive = true },
            new CachedCropCategory { Id = "2", Name = "Old", IsActive = false },
        ]);
        await h.RestartAsync();

        var active = await h.Outbox.GetActiveCategoriesAsync();
        Assert.Equal(["Maize"], active.Select(item => item.Name));
    }
}

public class ApiClientTests
{
    [Fact]
    public async Task Login_sends_buffered_json_with_a_content_length()
    {
        using var h = new Harness();

        await h.SignInAsync();

        Assert.True(h.Server.LoginHadContentLength);
        Assert.False(h.Server.LoginUsedChunkedTransfer);
    }

    [Fact]
    public async Task Snake_case_responses_bind_to_dtos()
    {
        using var h = new Harness();
        await h.SignInAsync();
        await h.AddDraftAsync();
        await h.Sync.SyncPendingAsync();
        h.Server.Review(h.Server.Batches[0].ClientSyncId, "rejected", "Photo missing");

        var batches = await h.Api.GetHarvestBatchesAsync();

        var batch = Assert.Single(batches);
        Assert.Equal(h.Server.Batches[0].ClientSyncId, batch.ClientSyncId);
        Assert.Equal("Photo missing", batch.RejectionReason);
    }

    [Fact]
    public async Task Concurrent_expired_requests_trigger_a_single_refresh()
    {
        using var h = new Harness();
        await h.SignInAsync();
        h.Server.ExpireAccessToken();

        var users = await Task.WhenAll(Enumerable.Range(0, 5).Select(_ => h.Api.GetCurrentUserAsync()));

        Assert.All(users, user => Assert.Equal("user-1", user.Id));
        Assert.Equal(1, h.Server.RefreshRequests);
    }

    [Theory]
    [InlineData("http://example.com/api/v1/")]
    [InlineData("ftp://localhost/")]
    [InlineData("not a url")]
    public void Insecure_or_invalid_base_urls_are_rejected(string url)
    {
        Assert.Throws<ArgumentException>(() => ApiClient.NormalizeApiBaseUrl(url));
    }

    [Fact]
    public void Local_http_and_remote_https_base_urls_are_accepted()
    {
        Assert.Equal("http://10.0.2.2:8000/api/v1/", ApiClient.NormalizeApiBaseUrl("http://10.0.2.2:8000/api/v1"));
        Assert.Equal("https://api.example.com/api/v1/", ApiClient.NormalizeApiBaseUrl("https://api.example.com/api/v1"));
    }

    [Fact]
    public async Task Logout_clears_stored_credentials_even_when_the_network_fails()
    {
        using var h = new Harness();
        await h.SignInAsync();
        h.Server.Offline = true;

        await Assert.ThrowsAsync<HttpRequestException>(() => h.Api.LogoutAsync());

        Assert.False(await h.Api.IsAuthenticatedAsync());
        Assert.Null(await h.Api.GetAuthenticatedUserIdAsync());
    }
}

public class SyncTests
{
    [Fact]
    public async Task Pending_draft_is_submitted_and_reflects_server_status()
    {
        using var h = new Harness();
        await h.SignInAsync();
        var draft = await h.AddDraftAsync();

        var completed = await h.Sync.SyncPendingAsync();

        Assert.Equal(1, completed);
        var stored = (await h.Outbox.FindAsync(draft.Id))!;
        Assert.Equal(DraftStatus.Submitted, stored.SyncStatus);
        Assert.Equal(h.Server.Batches[0].Id, stored.ServerBatchId);
        Assert.Equal(1, stored.AttemptCount);
    }

    [Fact]
    public async Task Lost_response_is_retried_with_the_same_key_and_creates_one_server_record()
    {
        using var h = new Harness();
        await h.SignInAsync();
        var draft = await h.AddDraftAsync();
        h.Server.LoseNextCreateResponse = true;

        await h.Sync.SyncPendingAsync();
        var afterLoss = (await h.Outbox.FindAsync(draft.Id))!;
        Assert.Equal(DraftStatus.Pending, afterLoss.SyncStatus);
        Assert.Single(h.Server.Batches);

        h.Server.Offline = false;
        await h.Sync.SyncPendingAsync();

        var stored = (await h.Outbox.FindAsync(draft.Id))!;
        Assert.Equal(DraftStatus.Submitted, stored.SyncStatus);
        Assert.Equal(draft.ClientSyncId, stored.ClientSyncId);
        Assert.Single(h.Server.Batches);
        Assert.Equal(2, h.Server.CreateRequests);
    }

    [Fact]
    public async Task Network_failure_keeps_drafts_pending_then_recovers_without_duplicates()
    {
        using var h = new Harness();
        await h.SignInAsync();
        await h.AddDraftAsync("1");
        await h.AddDraftAsync("2");
        h.Server.Offline = true;

        await Assert.ThrowsAsync<HttpRequestException>(() => h.Sync.SyncPendingAsync());
        Assert.Equal(2, (await h.Outbox.GetPendingAsync("user-1")).Count);
        Assert.Empty(h.Server.Batches);

        h.Server.Offline = false;
        Assert.Equal(2, await h.Sync.SyncPendingAsync());
        Assert.Equal(2, h.Server.Batches.Count);
        Assert.Empty(await h.Outbox.GetPendingAsync("user-1"));
    }

    [Fact]
    public async Task Pending_records_survive_restart_and_sync_afterwards()
    {
        using var h = new Harness();
        await h.SignInAsync();
        var draft = await h.AddDraftAsync();
        await h.RestartAsync();

        Assert.Equal(1, await h.Sync.SyncPendingAsync());

        Assert.Equal(DraftStatus.Submitted, (await h.Outbox.FindAsync(draft.Id))!.SyncStatus);
    }

    [Fact]
    public async Task Offline_draft_is_only_pending_until_the_server_accepts_it()
    {
        using var h = new Harness();
        await h.AddDraftAsync();

        var stored = Assert.Single(await h.Outbox.GetAllAsync("user-1"));
        Assert.Equal(DraftStatus.Pending, stored.SyncStatus);
        Assert.Empty(h.Server.Batches);
    }

    [Fact]
    public async Task Expired_access_token_is_refreshed_transparently()
    {
        using var h = new Harness();
        await h.SignInAsync();
        await h.AddDraftAsync();
        h.Server.ExpireAccessToken();

        Assert.Equal(1, await h.Sync.SyncPendingAsync());
        Assert.Equal(1, h.Server.RefreshRequests);
    }

    [Fact]
    public async Task Rejected_refresh_keeps_drafts_pending_and_recovery_reuses_the_same_keys()
    {
        using var h = new Harness();
        await h.SignInAsync();
        var draft = await h.AddDraftAsync();
        var key = draft.ClientSyncId;
        h.Server.ExpireAccessToken();
        h.Server.RefreshRejected = true;

        var exception = await Assert.ThrowsAsync<ApiRequestException>(() => h.Sync.SyncPendingAsync());
        Assert.Equal(HttpStatusCode.Unauthorized, exception.StatusCode);
        Assert.Equal(DraftStatus.Pending, (await h.Outbox.FindAsync(draft.Id))!.SyncStatus);
        Assert.Empty(h.Server.Batches);

        h.Server.RefreshRejected = false;
        await h.Api.LoginAsync("farmer@example.com", "correct-password");
        Assert.Equal(1, await h.Sync.SyncPendingAsync());

        Assert.Equal(key, h.Server.Batches.Single().ClientSyncId);
    }

    [Fact]
    public async Task Validation_failure_marks_draft_failed_with_server_message()
    {
        using var h = new Harness();
        await h.SignInAsync();
        var draft = await h.AddDraftAsync("-1");
        h.Server.RejectQuantity = quantity => quantity.StartsWith('-');

        await h.Sync.SyncPendingAsync();

        var stored = (await h.Outbox.FindAsync(draft.Id))!;
        Assert.Equal(DraftStatus.Failed, stored.SyncStatus);
        Assert.Contains("Quantity is not acceptable", stored.LastError);
        Assert.Empty(h.Server.Batches);
    }

    [Fact]
    public async Task Error_envelope_message_and_request_id_are_surfaced_to_the_user()
    {
        using var h = new Harness();
        await h.SignInAsync();
        var draft = await h.AddDraftAsync("-1");
        h.Server.UseErrorEnvelope = true;
        h.Server.RejectQuantity = quantity => quantity.StartsWith('-');

        await h.Sync.SyncPendingAsync();

        var stored = (await h.Outbox.FindAsync(draft.Id))!;
        Assert.Equal(DraftStatus.Failed, stored.SyncStatus);
        Assert.Equal("The server rejected this batch: Quantity is not acceptable. (ref req-123)", stored.LastError);
    }

    [Fact]
    public async Task Throttled_response_keeps_draft_queued_with_the_same_key_and_recovers()
    {
        using var h = new Harness();
        await h.SignInAsync();
        var draft = await h.AddDraftAsync("5");
        var key = draft.ClientSyncId;
        h.Server.ThrottleCreates = true;

        await h.Sync.SyncPendingAsync();

        var queued = (await h.Outbox.FindAsync(draft.Id))!;
        Assert.Equal(DraftStatus.Pending, queued.SyncStatus);
        Assert.Contains("slow down", queued.LastError);
        Assert.Empty(h.Server.Batches);

        h.Server.ThrottleCreates = false;
        await h.Sync.SyncPendingAsync();

        var synced = (await h.Outbox.FindAsync(draft.Id))!;
        Assert.Equal(key, synced.ClientSyncId);
        Assert.Single(h.Server.Batches);
    }

    [Fact]
    public async Task Sync_uses_the_operation_envelope_with_the_draft_key_as_operation_id()
    {
        using var h = new Harness();
        await h.SignInAsync();
        var draft = await h.AddDraftAsync("7");

        await h.Sync.SyncPendingAsync();

        Assert.Equal(1, h.Server.SyncOperationRequests);
        Assert.Equal(draft.ClientSyncId, h.Server.Batches.Single().ClientSyncId);
        var stored = (await h.Outbox.FindAsync(draft.Id))!;
        Assert.Equal(h.Server.Batches.Single().Id, stored.ServerBatchId);
    }

    private static string ContractText(string name) =>
        File.ReadAllText(Path.Combine(
            Path.GetDirectoryName(typeof(SyncTests).Assembly.Location)!, "contracts", name));

    private static HashSet<string> Keys(System.Text.Json.JsonElement element) =>
        element.EnumerateObject().Select(p => p.Name).ToHashSet();

    [Fact]
    public async Task Request_body_matches_the_shared_django_contract_fixture()
    {
        using var h = new Harness();
        await h.SignInAsync();
        await h.AddDraftAsync("7");

        await h.Sync.SyncPendingAsync();

        using var sent = System.Text.Json.JsonDocument.Parse(h.Server.LastSyncBody!);
        using var fixture = System.Text.Json.JsonDocument.Parse(ContractText("sync-harvest-create.request.json"));
        Assert.Equal(Keys(fixture.RootElement), Keys(sent.RootElement));
        Assert.Equal(
            Keys(fixture.RootElement.GetProperty("payload")),
            Keys(sent.RootElement.GetProperty("payload")));
        Assert.Equal("harvest_batch.create", sent.RootElement.GetProperty("operation_type").GetString());
    }

    [Fact]
    public async Task Receipt_fixture_from_django_deserializes_into_a_synced_draft()
    {
        using var h = new Harness();
        await h.SignInAsync();
        var draft = await h.AddDraftAsync("7");
        h.Server.SyncReceiptOverride = ContractText("sync-harvest-create.receipt.json");

        await h.Sync.SyncPendingAsync();

        using var fixture = System.Text.Json.JsonDocument.Parse(ContractText("sync-harvest-create.receipt.json"));
        var expectedId = fixture.RootElement.GetProperty("result").GetProperty("id").GetString();
        var stored = (await h.Outbox.FindAsync(draft.Id))!;
        Assert.Equal(expectedId, stored.ServerBatchId);
    }

    [Fact]
    public async Task Non_farmer_accounts_cannot_sync_and_drafts_stay_queued()
    {
        using var h = new Harness();
        h.Server.Roles = ["buyer"];
        await h.SignInAsync();
        var draft = await h.AddDraftAsync();

        var exception = await Assert.ThrowsAsync<ApiRequestException>(() => h.Sync.SyncPendingAsync());

        Assert.Equal(HttpStatusCode.Forbidden, exception.StatusCode);
        Assert.Equal(DraftStatus.Pending, (await h.Outbox.FindAsync(draft.Id))!.SyncStatus);
        Assert.Equal(0, h.Server.CreateRequests);
    }

    [Fact]
    public async Task Concurrent_sync_attempts_send_each_draft_once()
    {
        using var h = new Harness();
        await h.SignInAsync();
        await h.AddDraftAsync("1");
        await h.AddDraftAsync("2");
        await h.AddDraftAsync("3");

        var results = await Task.WhenAll(Enumerable.Range(0, 6).Select(_ => h.Sync.SyncPendingAsync()));

        Assert.Equal(3, results.Sum());
        Assert.Equal(3, h.Server.CreateRequests);
        Assert.Equal(3, h.Server.Batches.Count);
    }

    [Fact]
    public async Task Server_review_outcome_and_reason_are_mirrored_locally()
    {
        using var h = new Harness();
        await h.SignInAsync();
        var draft = await h.AddDraftAsync();
        await h.Sync.SyncPendingAsync();

        h.Server.Review(draft.ClientSyncId, "rejected", "Quantity looks wrong");
        await h.Sync.SyncPendingAsync();

        var stored = (await h.Outbox.FindAsync(draft.Id))!;
        Assert.Equal(DraftStatus.Rejected, stored.SyncStatus);
        Assert.Equal("Quantity looks wrong", stored.RejectionReason);
        Assert.Equal("Quantity looks wrong", stored.LastError);

        h.Server.Review(draft.ClientSyncId, "accepted");
        await h.Sync.SyncPendingAsync();
        Assert.Equal(DraftStatus.Accepted, (await h.Outbox.FindAsync(draft.Id))!.SyncStatus);
    }

    [Fact]
    public async Task Retry_failed_requeues_failed_drafts_with_the_same_key()
    {
        using var h = new Harness();
        await h.SignInAsync();
        var draft = await h.AddDraftAsync("-1");
        h.Server.RejectQuantity = quantity => quantity.StartsWith('-');
        await h.Sync.SyncPendingAsync();

        await h.Sync.RetryFailedAsync("user-1");

        var stored = (await h.Outbox.FindAsync(draft.Id))!;
        Assert.Equal(DraftStatus.Pending, stored.SyncStatus);
        Assert.Equal(draft.ClientSyncId, stored.ClientSyncId);
    }
}

public class DraftEditingTests
{
    [Fact]
    public async Task Never_sent_draft_is_edited_in_place_and_keeps_its_key()
    {
        using var h = new Harness();
        var draft = await h.AddDraftAsync("1");

        var edited = await h.Outbox.EditDraftAsync(draft.Id, "user-1", Harness.Fields("2"));

        Assert.Equal("2", edited.Quantity);
        Assert.Equal(draft.ClientSyncId, edited.ClientSyncId);
    }

    [Fact]
    public async Task Pending_draft_with_unknown_outcome_cannot_be_edited()
    {
        using var h = new Harness();
        await h.SignInAsync();
        var draft = await h.AddDraftAsync();
        h.Server.LoseNextCreateResponse = true;
        await h.Sync.SyncPendingAsync();

        await Assert.ThrowsAsync<InvalidOperationException>(
            () => h.Outbox.EditDraftAsync(draft.Id, "user-1", Harness.Fields("99")));
    }

    [Fact]
    public async Task Failed_draft_is_edited_with_a_new_key_and_resubmitted_once()
    {
        using var h = new Harness();
        await h.SignInAsync();
        var draft = await h.AddDraftAsync("-1");
        h.Server.RejectQuantity = quantity => quantity.StartsWith('-');
        await h.Sync.SyncPendingAsync();

        var edited = await h.Outbox.EditDraftAsync(draft.Id, "user-1", Harness.Fields("7"));
        Assert.NotEqual(draft.ClientSyncId, edited.ClientSyncId);
        Assert.Equal(DraftStatus.Pending, edited.SyncStatus);

        await h.Sync.SyncPendingAsync();

        Assert.Equal("7", h.Server.Batches.Single().Quantity);
        Assert.Equal(DraftStatus.Submitted, (await h.Outbox.FindAsync(draft.Id))!.SyncStatus);
    }

    [Fact]
    public async Task Rejected_draft_is_corrected_by_a_new_linked_draft_and_original_is_kept()
    {
        using var h = new Harness();
        await h.SignInAsync();
        var original = await h.AddDraftAsync("100");
        await h.Sync.SyncPendingAsync();
        h.Server.Review(original.ClientSyncId, "rejected", "Too large");
        await h.Sync.SyncPendingAsync();

        var correction = await h.Outbox.CreateCorrectionAsync(original.Id, "user-1", Harness.Fields("10"));
        await h.Sync.SyncPendingAsync();

        var storedOriginal = (await h.Outbox.FindAsync(original.Id))!;
        var storedCorrection = (await h.Outbox.FindAsync(correction.Id))!;
        Assert.Equal(DraftStatus.Rejected, storedOriginal.SyncStatus);
        Assert.Equal("Too large", storedOriginal.RejectionReason);
        Assert.Equal(correction.Id, storedOriginal.CorrectedByDraftId);
        Assert.NotEqual(original.ClientSyncId, storedCorrection.ClientSyncId);
        Assert.Equal(storedOriginal.ServerBatchId, storedCorrection.ResubmissionOfServerBatchId);
        Assert.Equal(DraftStatus.Submitted, storedCorrection.SyncStatus);
        Assert.Equal(2, h.Server.Batches.Count);
        Assert.Equal(storedOriginal.ServerBatchId, h.Server.Batches.Last().ResubmissionOf);
    }

    [Fact]
    public async Task Correction_survives_lost_response_without_duplicating()
    {
        using var h = new Harness();
        await h.SignInAsync();
        var original = await h.AddDraftAsync("100");
        await h.Sync.SyncPendingAsync();
        h.Server.Review(original.ClientSyncId, "rejected", "Too large");
        await h.Sync.SyncPendingAsync();
        await h.Outbox.CreateCorrectionAsync(original.Id, "user-1", Harness.Fields("10"));
        h.Server.LoseNextCreateResponse = true;

        await h.Sync.SyncPendingAsync();
        h.Server.Offline = false;
        await h.RestartAsync();
        await h.Sync.SyncPendingAsync();

        Assert.Equal(2, h.Server.Batches.Count);
    }

    [Fact]
    public async Task A_rejected_draft_can_only_be_corrected_once()
    {
        using var h = new Harness();
        await h.SignInAsync();
        var original = await h.AddDraftAsync("100");
        await h.Sync.SyncPendingAsync();
        h.Server.Review(original.ClientSyncId, "rejected", "No");
        await h.Sync.SyncPendingAsync();
        await h.Outbox.CreateCorrectionAsync(original.Id, "user-1", Harness.Fields("10"));

        await Assert.ThrowsAsync<InvalidOperationException>(
            () => h.Outbox.CreateCorrectionAsync(original.Id, "user-1", Harness.Fields("11")));
        Assert.Equal(2, (await h.Outbox.GetAllAsync("user-1")).Count);
    }

    [Fact]
    public async Task Only_server_rejected_drafts_can_be_corrected_and_only_by_their_owner()
    {
        using var h = new Harness();
        await h.SignInAsync();
        var pending = await h.AddDraftAsync();
        await Assert.ThrowsAsync<InvalidOperationException>(
            () => h.Outbox.CreateCorrectionAsync(pending.Id, "user-1", Harness.Fields("1")));

        await h.Sync.SyncPendingAsync();
        h.Server.Review(pending.ClientSyncId, "rejected", "No");
        await h.Sync.SyncPendingAsync();
        await Assert.ThrowsAsync<InvalidOperationException>(
            () => h.Outbox.CreateCorrectionAsync(pending.Id, "user-2", Harness.Fields("1")));
    }

    [Fact]
    public async Task Rejected_drafts_cannot_be_edited_in_place()
    {
        using var h = new Harness();
        await h.SignInAsync();
        var draft = await h.AddDraftAsync();
        await h.Sync.SyncPendingAsync();
        h.Server.Review(draft.ClientSyncId, "rejected", "No");
        await h.Sync.SyncPendingAsync();

        await Assert.ThrowsAsync<InvalidOperationException>(
            () => h.Outbox.EditDraftAsync(draft.Id, "user-1", Harness.Fields("1")));
    }
}
