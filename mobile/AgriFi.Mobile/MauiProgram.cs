using AgriFi.Mobile.Adapters;
using AgriFi.Mobile.Services;
using Microsoft.Extensions.Logging;

namespace AgriFi.Mobile;

public static class MauiProgram
{
	public static MauiApp CreateMauiApp()
	{
		var builder = MauiApp.CreateBuilder();
		builder
			.UseMauiApp<App>()
			.ConfigureFonts(fonts =>
			{
				fonts.AddFont("OpenSans-Regular.ttf", "OpenSansRegular");
				fonts.AddFont("OpenSans-Semibold.ttf", "OpenSansSemibold");
			});
		builder.Services.AddSingleton<HttpClient>();
		builder.Services.AddSingleton<ISecureStore, MauiSecureStore>();
		builder.Services.AddSingleton<IAppSettings, MauiAppSettings>();
		builder.Services.AddSingleton<ApiClient>();
		builder.Services.AddSingleton<IHarvestBatchApi>(services => services.GetRequiredService<ApiClient>());
		builder.Services.AddSingleton(_ => new OutboxStore(
			Path.Combine(FileSystem.AppDataDirectory, "agrifi-outbox.db3")));
		builder.Services.AddSingleton<HarvestBatchSyncService>();
		builder.Services.AddSingleton<MainPage>();

#if DEBUG
		builder.Logging.AddDebug();
#endif

		return builder.Build();
	}
}
