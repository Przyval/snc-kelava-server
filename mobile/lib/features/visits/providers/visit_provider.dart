import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import '../../../core/config/app_config.dart';
import '../../../core/models/visit_model.dart';
import '../../../core/services/api_service.dart';
import '../../../core/services/offline_cache_service.dart';
import '../../../core/services/sync_service.dart';

class VisitProvider extends ChangeNotifier {
  final _api = ApiService();

  List<VisitModel> _visits = [];
  bool _loading = false;
  bool _isOffline = false;
  int _pendingSync = 0;
  String? _error;
  String? _actionSuccess;

  List<VisitModel> get visits => _visits;
  bool get loading => _loading;
  bool get isOffline => _isOffline;
  int get pendingSync => _pendingSync;
  String? get error => _error;
  String? get actionSuccess => _actionSuccess;

  Future<void> loadToday() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final res = await _api.get('${AppConfig.mobileVisitsPath}/today');
      final rawList = res.data as List;
      final list = rawList
          .map((e) => VisitModel.fromJson(e as Map<String, dynamic>))
          .toList();
      _visits = list;
      _isOffline = false;

      // Cache for offline use
      await OfflineCacheService.instance.cacheVisits(
        rawList.cast<Map<String, dynamic>>(),
      );

      // Try to sync any queued offline actions
      final synced = await SyncService.instance.syncPendingActions();
      if (synced > 0) await loadToday(); // reload after sync
    } on DioException {
      // Network error — fall back to cache
      final cached = await OfflineCacheService.instance.getCachedVisits();
      if (cached.isNotEmpty) {
        _visits = cached.map(VisitModel.fromJson).toList();
        _isOffline = true;
        _error = 'Offline — menampilkan data terakhir.';
      } else {
        _error = 'Tidak ada koneksi dan belum ada data tersimpan.';
      }
    } catch (e) {
      _error = 'Gagal memuat jadwal';
    } finally {
      _pendingSync = await OfflineCacheService.instance.pendingCount();
      _loading = false;
      notifyListeners();
    }
  }

  Future<bool> checkIn(
    int visitId, {
    double? lat,
    double? lng,
    List<XFile>? photos,
  }) async {
    try {
      await _api.post(
        '${AppConfig.mobileVisitsPath}/$visitId/checkin',
        data: {'latitude': lat, 'longitude': lng},
      );

      if (photos != null && photos.isNotEmpty) {
        await _uploadPhotos(visitId, photos, 'checkin');
      }

      _actionSuccess = 'Check-in berhasil!';
      await loadToday();
      return true;
    } on DioException {
      // Offline — queue the action, update UI optimistically
      await OfflineCacheService.instance.queueAction(
        actionType: 'checkin',
        visitId: visitId,
        latitude: lat,
        longitude: lng,
      );
      await OfflineCacheService.instance.updateVisitLocally(
        visitId,
        checkIn: DateTime.now().toIso8601String(),
        status: 'Berjalan',
      );
      _pendingSync = await OfflineCacheService.instance.pendingCount();
      _actionSuccess = 'Check-in disimpan — akan sync saat online.';
      await loadToday();
      return true;
    } catch (e) {
      _error = 'Gagal check-in';
      notifyListeners();
      return false;
    }
  }

  Future<bool> checkOut(
    int visitId,
    String remarks, {
    double? lat,
    double? lng,
    List<XFile>? photos,
  }) async {
    try {
      await _api.post(
        '${AppConfig.mobileVisitsPath}/$visitId/checkout',
        data: {'remarks': remarks, 'latitude': lat, 'longitude': lng},
      );

      if (photos != null && photos.isNotEmpty) {
        await _uploadPhotos(visitId, photos, 'checkout');
      }

      _actionSuccess = 'Check-out berhasil!';
      await loadToday();
      return true;
    } on DioException {
      // Offline — queue + optimistic update
      await OfflineCacheService.instance.queueAction(
        actionType: 'checkout',
        visitId: visitId,
        latitude: lat,
        longitude: lng,
        remarks: remarks,
      );
      await OfflineCacheService.instance.updateVisitLocally(
        visitId,
        checkOut: DateTime.now().toIso8601String(),
        status: 'Selesai',
      );
      _pendingSync = await OfflineCacheService.instance.pendingCount();
      _actionSuccess = 'Check-out disimpan — akan sync saat online.';
      await loadToday();
      return true;
    } catch (e) {
      _error = 'Gagal check-out';
      notifyListeners();
      return false;
    }
  }

  Future<void> _uploadPhotos(
    int visitId,
    List<XFile> photos,
    String stage,
  ) async {
    final formData = FormData();
    formData.fields.add(MapEntry('stage', stage));
    for (final file in photos) {
      formData.files.add(MapEntry(
        'photos',
        await MultipartFile.fromFile(file.path, filename: file.name),
      ));
    }
    await _api.postMultipart(
      '${AppConfig.mobileVisitsPath}/$visitId/photos',
      formData,
    );
  }

  void clearMessages() {
    _error = null;
    _actionSuccess = null;
  }
}
