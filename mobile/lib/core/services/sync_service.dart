import 'package:dio/dio.dart';
import 'api_service.dart';
import 'offline_cache_service.dart';
import '../config/app_config.dart';

/// SyncService — flushes pending offline actions to server when back online.
/// Call syncPendingActions() on app resume or connectivity change.
class SyncService {
  static final SyncService instance = SyncService._();
  SyncService._();

  final _api = ApiService();
  bool _syncing = false;

  /// Attempt to flush all queued offline actions.
  /// Returns number of successfully synced actions.
  Future<int> syncPendingActions() async {
    if (_syncing) return 0;
    _syncing = true;

    int synced = 0;
    try {
      final pending = await OfflineCacheService.instance.getPendingActions();
      for (final action in pending) {
        final id = action['id'] as int;
        final visitId = action['visit_id'] as int;
        final type = action['action_type'] as String;
        final retries = (action['retry_count'] as int?) ?? 0;

        // Give up after 5 retries
        if (retries >= 5) {
          await OfflineCacheService.instance.deletePendingAction(id);
          continue;
        }

        try {
          final data = <String, dynamic>{};
          if (action['latitude'] != null) data['latitude'] = action['latitude'];
          if (action['longitude'] != null) data['longitude'] = action['longitude'];
          if (action['remarks'] != null) data['remarks'] = action['remarks'];

          await _api.post(
            '${AppConfig.mobileVisitsPath}/$visitId/$type',
            data: data,
          );

          await OfflineCacheService.instance.deletePendingAction(id);
          synced++;
        } on DioException {
          await OfflineCacheService.instance.incrementRetry(id);
        }
      }
    } finally {
      _syncing = false;
    }
    return synced;
  }

  bool get isSyncing => _syncing;
}
