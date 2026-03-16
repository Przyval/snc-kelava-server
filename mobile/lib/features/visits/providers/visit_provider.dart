import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import '../../../core/config/app_config.dart';
import '../../../core/models/visit_model.dart';
import '../../../core/services/api_service.dart';

class VisitProvider extends ChangeNotifier {
  final _api = ApiService();

  List<VisitModel> _visits = [];
  bool _loading = false;
  String? _error;
  String? _actionSuccess;

  List<VisitModel> get visits => _visits;
  bool get loading => _loading;
  String? get error => _error;
  String? get actionSuccess => _actionSuccess;

  Future<void> loadToday() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final res = await _api.get('${AppConfig.mobileVisitsPath}/today');
      final list = (res.data as List)
          .map((e) => VisitModel.fromJson(e as Map<String, dynamic>))
          .toList();
      _visits = list;
    } catch (e) {
      _error = 'Gagal memuat jadwal';
    } finally {
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
      // 1. Check-in with GPS
      await _api.post(
        '${AppConfig.mobileVisitsPath}/$visitId/checkin',
        data: {'latitude': lat, 'longitude': lng},
      );

      // 2. Upload photos if any
      if (photos != null && photos.isNotEmpty) {
        await _uploadPhotos(visitId, photos, 'checkin');
      }

      _actionSuccess = 'Check-in berhasil!';
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
      // 1. Check-out with GPS + remarks
      await _api.post(
        '${AppConfig.mobileVisitsPath}/$visitId/checkout',
        data: {'remarks': remarks, 'latitude': lat, 'longitude': lng},
      );

      // 2. Upload photos if any
      if (photos != null && photos.isNotEmpty) {
        await _uploadPhotos(visitId, photos, 'checkout');
      }

      _actionSuccess = 'Check-out berhasil!';
      await loadToday();
      return true;
    } catch (e) {
      _error = 'Gagal check-out';
      notifyListeners();
      return false;
    }
  }

  /// Upload photos as multipart form-data.
  Future<void> _uploadPhotos(
    int visitId,
    List<XFile> photos,
    String stage,
  ) async {
    final formData = FormData();
    formData.fields.add(MapEntry('stage', stage));

    for (int i = 0; i < photos.length; i++) {
      final file = photos[i];
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
