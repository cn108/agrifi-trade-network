using SQLite;

namespace AgriFi.Mobile.Models;

public sealed class CachedCropCategory
{
    [PrimaryKey]
    public string Id { get; set; } = string.Empty;

    public string Name { get; set; } = string.Empty;
    public bool IsActive { get; set; }
}
