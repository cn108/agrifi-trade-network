using System.Collections.ObjectModel;
using System.Globalization;
using System.Net;
using AgriFi.Mobile.Models;
using AgriFi.Mobile.Services;
using SQLite;

namespace AgriFi.Mobile;

public partial class MainPage : ContentPage
{
    private readonly ApiClient _api;
    private readonly OutboxStore _outbox;
    private readonly HarvestBatchSyncService _sync;
    private readonly ObservableCollection<HarvestBatchDisplay> _batchRows = [];
    private readonly Dictionary<string, string> _categoryNames = [];
    private string? _editingDraftId;
    private bool _correcting;

    public MainPage(ApiClient api, OutboxStore outbox, HarvestBatchSyncService sync)
    {
        InitializeComponent();
        _api = api;
        _outbox = outbox;
        _sync = sync;
        ApiBaseUrlEntry.Text = api.ApiBaseUrl;
        UnitPicker.ItemsSource = new[] { "kg", "tonne", "bag", "crate", "piece" };
        UnitPicker.SelectedIndex = 0;
        BatchCollection.ItemsSource = _batchRows;
    }

    protected override async void OnAppearing()
    {
        base.OnAppearing();
        await LoadSavedBatchesAsync();
        await RestoreSessionAsync();
    }

    private async void OnSignInClicked(object? sender, EventArgs e)
    {
        SetBusy(true);
        try
        {
            _api.SetApiBaseUrl(ApiBaseUrlEntry.Text ?? string.Empty);
            var user = await _api.LoginAsync(EmailEntry.Text ?? string.Empty, PasswordEntry.Text ?? string.Empty);
            if (!user.Roles.Contains("farmer", StringComparer.Ordinal))
            {
                await _api.LogoutAsync();
                ShowMessage("This application is for farmer accounts.");
                return;
            }

            SignedInLabel.Text = user.Email;
            await ShowWorkspaceAsync(offline: false);
            await RefreshRemoteDataAsync();
            PasswordEntry.Text = string.Empty;
            HideMessage();
        }
        catch (ApiRequestException exception)
        {
            ShowMessage($"Sign-in failed: {exception.UserMessage}");
        }
        catch (HttpRequestException)
        {
            ShowMessage("The API could not be reached. Check the API URL and network connection.");
        }
        catch (TaskCanceledException)
        {
            ShowMessage("The API request timed out. Check the API URL and network connection.");
        }
        catch (ArgumentException exception)
        {
            ShowMessage(exception.Message);
        }
        catch (SQLiteException exception)
        {
            ShowMessage($"Local storage is unavailable: {exception.Message}");
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void OnSignOutClicked(object? sender, EventArgs e)
    {
        SetBusy(true);
        try
        {
            await _api.LogoutAsync();
            WorkspacePanel.IsVisible = false;
            SignInPanel.IsVisible = true;
            HideMessage();
        }
        catch (HttpRequestException)
        {
            ShowMessage("Sign-out could not reach the API. Local credentials were cleared; revoke access when online.");
            WorkspacePanel.IsVisible = false;
            SignInPanel.IsVisible = true;
        }
        catch (ApiRequestException exception)
        {
            ShowMessage($"Signed out on this device. The API did not confirm token revocation: {exception.Message}");
            WorkspacePanel.IsVisible = false;
            SignInPanel.IsVisible = true;
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void OnSaveProfileClicked(object? sender, EventArgs e)
    {
        SetBusy(true);
        try
        {
            var profile = new FarmerProfile(
                DisplayNameEntry.Text?.Trim() ?? string.Empty,
                RegionEntry.Text?.Trim() ?? string.Empty,
                LocationEntry.Text?.Trim() ?? string.Empty);
            var saved = await _api.SaveFarmerProfileAsync(profile);
            ApplyProfile(saved);
            ShowMessage("Farmer profile saved.");
        }
        catch (ApiRequestException exception)
        {
            ShowMessage($"Profile could not be saved: {exception.Message}");
        }
        catch (HttpRequestException)
        {
            ShowMessage("The API could not be reached. Profile edits require a connection.");
        }
        catch (TaskCanceledException)
        {
            ShowMessage("The profile request timed out. Profile edits require a connection.");
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void OnSaveBatchClicked(object? sender, EventArgs e)
    {
        if (CategoryPicker.SelectedItem is not CropCategory category
            || UnitPicker.SelectedItem is not string unit)
        {
            ShowMessage("Sign in while online to load an active crop category before recording a batch.");
            return;
        }

        if (!decimal.TryParse(
                QuantityEntry.Text,
                NumberStyles.AllowDecimalPoint,
                CultureInfo.InvariantCulture,
                out var quantity)
            || quantity <= 0
            || decimal.Round(quantity, 3) != quantity)
        {
            ShowMessage("Enter a positive quantity with no more than three decimal places.");
            return;
        }

        var fields = new DraftFields(
            category.Id,
            quantity.ToString("0.###", CultureInfo.InvariantCulture),
            unit,
            $"{HarvestDatePicker.Date:yyyy-MM-dd}",
            NotesEditor.Text?.Trim() ?? string.Empty);
        var ownerUserId = await _api.GetAuthenticatedUserIdAsync();
        if (string.IsNullOrWhiteSpace(ownerUserId))
        {
            ShowMessage("Sign in before saving a harvest batch.");
            return;
        }

        try
        {
            if (_editingDraftId is null)
            {
                await _outbox.SaveAsync(new HarvestBatchDraft
                {
                    OwnerUserId = ownerUserId,
                    CategoryId = fields.CategoryId,
                    Quantity = fields.Quantity,
                    UnitCode = fields.UnitCode,
                    HarvestedOn = fields.HarvestedOn,
                    Notes = fields.Notes,
                });
                ShowMessage("Batch saved on this device with a retry-safe operation ID.");
            }
            else if (_correcting)
            {
                await _outbox.CreateCorrectionAsync(_editingDraftId, ownerUserId, fields);
                ShowMessage("Correction saved. It is linked to the rejected batch and will sync as a new submission.");
            }
            else
            {
                await _outbox.EditDraftAsync(_editingDraftId, ownerUserId, fields);
                ShowMessage("Batch updated. Sync to submit it.");
            }

            ClearEditing();
            await LoadSavedBatchesAsync();
        }
        catch (InvalidOperationException exception)
        {
            ShowMessage(exception.Message);
            ClearEditing();
            await LoadSavedBatchesAsync();
        }
        catch (SQLiteException exception)
        {
            ShowMessage($"The batch was not saved locally: {exception.Message}");
        }
    }

    private async void OnBatchActionClicked(object? sender, EventArgs e)
    {
        if ((sender as Button)?.BindingContext is not HarvestBatchDisplay row)
        {
            return;
        }

        var draft = await _outbox.FindAsync(row.DraftId);
        if (draft is null)
        {
            return;
        }

        _editingDraftId = draft.Id;
        _correcting = draft.SyncStatus == DraftStatus.Rejected;
        CategoryPicker.SelectedItem = (CategoryPicker.ItemsSource as List<CropCategory>)?
            .FirstOrDefault(category => category.Id == draft.CategoryId) ?? CategoryPicker.SelectedItem;
        QuantityEntry.Text = draft.Quantity;
        UnitPicker.SelectedItem = draft.UnitCode;
        if (DateTime.TryParse(draft.HarvestedOn, CultureInfo.InvariantCulture, out var harvestedOn))
        {
            HarvestDatePicker.Date = harvestedOn;
        }

        NotesEditor.Text = draft.Notes;
        SaveBatchButton.Text = _correcting ? "Save correction" : "Save changes";
        CancelEditButton.IsVisible = true;
        ShowMessage(_correcting
            ? $"Correcting a rejected batch. Reason: {draft.RejectionReason}"
            : "Editing a batch that has not been accepted.");
    }

    private void OnCancelEditClicked(object? sender, EventArgs e)
    {
        ClearEditing();
        HideMessage();
    }

    private void ClearEditing()
    {
        _editingDraftId = null;
        _correcting = false;
        SaveBatchButton.Text = "Save on this device";
        CancelEditButton.IsVisible = false;
        QuantityEntry.Text = string.Empty;
        NotesEditor.Text = string.Empty;
    }

    private async void OnSyncClicked(object? sender, EventArgs e)
    {
        await SyncPendingAsync();
    }

    private async Task SyncPendingAsync()
    {
        SetBusy(true);
        try
        {
            var synced = await _sync.SyncPendingAsync();
            await LoadSavedBatchesAsync();
            ShowMessage($"{synced} pending batch(es) submitted. Server review status is shown below.");
            OfflineLabel.IsVisible = false;
        }
        catch (ApiRequestException exception)
        {
            await LoadSavedBatchesAsync();
            ShowMessage($"Sync could not be completed: {exception.Message}");
        }
        catch (SQLiteException exception)
        {
            ShowMessage($"Local outbox could not be updated: {exception.Message}");
        }
        catch (HttpRequestException)
        {
            await LoadSavedBatchesAsync();
            OfflineLabel.IsVisible = true;
            ShowMessage("The API could not be reached. Pending batches remain stored on this device.");
        }
        catch (TaskCanceledException)
        {
            await LoadSavedBatchesAsync();
            OfflineLabel.IsVisible = true;
            ShowMessage("Sync timed out. Pending batches remain stored on this device.");
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void OnRetryFailedClicked(object? sender, EventArgs e)
    {
        try
        {
            var ownerUserId = await _api.GetAuthenticatedUserIdAsync();
            if (string.IsNullOrWhiteSpace(ownerUserId))
            {
                ShowMessage("Sign in with the farmer account that owns these batches before retrying.");
                return;
            }

            await _sync.RetryFailedAsync(ownerUserId);
            await SyncPendingAsync();
        }
        catch (SQLiteException exception)
        {
            ShowMessage($"Failed batches could not be queued for retry: {exception.Message}");
        }
    }

    private async Task RestoreSessionAsync()
    {
        if (!await _api.IsAuthenticatedAsync())
        {
            return;
        }

        try
        {
            var user = await _api.GetCurrentUserAsync();
            if (!user.Roles.Contains("farmer", StringComparer.Ordinal))
            {
                await _api.LogoutAsync();
                ShowMessage("The saved account is not a farmer account. Sign in with a farmer account.");
                return;
            }

            SignedInLabel.Text = user.Email;
            await ShowWorkspaceAsync(offline: false);
            await RefreshRemoteDataAsync();
        }
        catch (HttpRequestException)
        {
            await ShowWorkspaceAsync(offline: true);
        }
        catch (TaskCanceledException)
        {
            await ShowWorkspaceAsync(offline: true);
        }
        catch (ApiRequestException exception) when (exception.StatusCode == HttpStatusCode.Unauthorized)
        {
            ShowMessage("Your saved session expired. Sign in again to sync; local batches remain available.");
        }
        catch (ApiRequestException exception)
        {
            await ShowWorkspaceAsync(offline: true);
            ShowMessage($"The API is unavailable. Saved batches remain available: {exception.Message}");
        }
        catch (SQLiteException exception)
        {
            ShowMessage($"Local storage is unavailable: {exception.Message}");
        }
    }

    private async Task ShowWorkspaceAsync(bool offline)
    {
        SignInPanel.IsVisible = false;
        WorkspacePanel.IsVisible = true;
        OfflineLabel.IsVisible = offline;
        var cachedCategories = await _outbox.GetActiveCategoriesAsync();
        ApplyCategories(cachedCategories.Select(category =>
            new CropCategory(category.Id, category.Name, category.IsActive)).ToList());
        await LoadSavedBatchesAsync();
    }

    private async Task RefreshRemoteDataAsync()
    {
        var profile = await _api.GetFarmerProfileAsync();
        ApplyProfile(profile);
        var categories = await _api.GetCategoriesAsync();
        ApplyCategories(categories);
        await _outbox.SaveCategoriesAsync(categories.Select(category =>
            new CachedCropCategory
            {
                Id = category.Id,
                Name = category.Name,
                IsActive = category.IsActive,
            }));
        await LoadSavedBatchesAsync();
        OfflineLabel.IsVisible = false;
    }

    private void ApplyProfile(FarmerProfile profile)
    {
        DisplayNameEntry.Text = profile.DisplayName;
        RegionEntry.Text = profile.Region;
        LocationEntry.Text = profile.Location;
    }

    private void ApplyCategories(List<CropCategory> categories)
    {
        _categoryNames.Clear();
        foreach (var category in categories)
        {
            _categoryNames[category.Id] = category.Name;
        }

        CategoryPicker.ItemsSource = categories;
        if (categories.Count > 0 && CategoryPicker.SelectedItem is null)
        {
            CategoryPicker.SelectedItem = categories[0];
        }
    }

    private async Task LoadSavedBatchesAsync()
    {
        try
        {
            var ownerUserId = await _api.GetAuthenticatedUserIdAsync();
            List<HarvestBatchDraft> drafts = string.IsNullOrWhiteSpace(ownerUserId)
                ? []
                : await _outbox.GetAllAsync(ownerUserId);
            _batchRows.Clear();
            foreach (var draft in drafts)
            {
                _batchRows.Add(new HarvestBatchDisplay(
                    draft.Id,
                    _categoryNames.GetValueOrDefault(draft.CategoryId, "Crop category"),
                    $"{draft.Quantity} {draft.UnitCode} · harvested {draft.HarvestedOn}",
                    FormatStatus(draft),
                    draft.SyncStatus == DraftStatus.Rejected
                        ? $"Reason: {draft.RejectionReason}".TrimEnd(' ', ':')
                        : draft.LastError,
                    ActionFor(draft)));
            }
        }
        catch (SQLiteException exception)
        {
            ShowMessage($"Local batch storage could not be read: {exception.Message}");
        }
    }

    private static string FormatStatus(HarvestBatchDraft draft) => draft.SyncStatus switch
    {
        DraftStatus.Pending => "Pending sync",
        DraftStatus.Submitted => "Submitted · awaiting operations review",
        DraftStatus.Accepted => "Accepted",
        DraftStatus.Rejected when !string.IsNullOrWhiteSpace(draft.CorrectedByDraftId) =>
            "Rejected · corrected by a new submission",
        DraftStatus.Rejected => "Rejected",
        DraftStatus.Failed => "Failed · edit or retry",
        _ => draft.SyncStatus,
    };

    private static string ActionFor(HarvestBatchDraft draft) => draft.SyncStatus switch
    {
        DraftStatus.Pending when draft.AttemptCount == 0 => "Edit",
        DraftStatus.Failed => "Edit and resubmit",
        DraftStatus.Rejected when string.IsNullOrWhiteSpace(draft.CorrectedByDraftId) => "Correct and resubmit",
        _ => string.Empty,
    };

    private void SetBusy(bool busy)
    {
        SignInPanel.IsEnabled = !busy;
        WorkspacePanel.IsEnabled = !busy;
    }

    private void ShowMessage(string text)
    {
        MessageLabel.Text = text;
        MessageLabel.IsVisible = true;
    }

    private void HideMessage()
    {
        MessageLabel.Text = string.Empty;
        MessageLabel.IsVisible = false;
    }

    public sealed record HarvestBatchDisplay(
        string DraftId,
        string CategoryName,
        string QuantityDisplay,
        string StatusDisplay,
        string LastError,
        string ActionText)
    {
        public bool HasAction => !string.IsNullOrEmpty(ActionText);
    }
}
