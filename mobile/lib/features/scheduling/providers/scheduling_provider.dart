import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import '../../../core/config/app_config.dart';
import '../../../core/models/road_plan_model.dart';
import '../../../core/services/api_service.dart';

class SchedulingProvider extends ChangeNotifier {
  final _api = ApiService();

  List<RoadPlanModel> _plans = [];
  bool _loading = false;
  bool _saving = false;
  String? _error;
  String? _success;

  List<RoadPlanModel> get plans => _plans;
  bool get loading => _loading;
  bool get saving => _saving;
  String? get error => _error;
  String? get success => _success;

  /// Load road plans for a date (merged Kelava + SNC)
  Future<void> loadForDate(String date, {int? pUserId}) async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final params = <String, dynamic>{'date': date};
      if (pUserId != null) params['p_user_id'] = pUserId;

      final res = await _api.get(AppConfig.roadPlansPath, queryParameters: params);
      final list = (res.data['road_plans'] as List)
          .map((e) => RoadPlanModel.fromJson(e as Map<String, dynamic>))
          .toList();
      _plans = list;
    } on DioException catch (e) {
      _error = e.response?.data?['error'] ?? 'Gagal memuat jadwal';
    } catch (e) {
      _error = 'Gagal memuat jadwal';
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  /// Koordinator: create new road plan
  Future<bool> createRoadPlan({
    required int pUserId,
    required int customerId,
    required DateTime visitDate,
    int? kontrakId,
    String? title,
    String? remarks,
  }) async {
    _saving = true;
    _error = null;
    _success = null;
    notifyListeners();

    try {
      await _api.post(AppConfig.roadPlansPath, data: {
        'p_user_id': pUserId,
        'customer_id': customerId,
        'visit_date': visitDate.toIso8601String(),
        if (kontrakId != null) 'kontrak_id': kontrakId,
        if (title != null && title.isNotEmpty) 'title': title,
        if (remarks != null && remarks.isNotEmpty) 'remarks': remarks,
      });
      _success = 'Jadwal berhasil dibuat!';
      return true;
    } on DioException catch (e) {
      _error = e.response?.data?['error'] ?? 'Gagal membuat jadwal';
      return false;
    } catch (e) {
      _error = 'Gagal membuat jadwal';
      return false;
    } finally {
      _saving = false;
      notifyListeners();
    }
  }

  /// Koordinator: cancel a SNC road plan
  Future<bool> cancelRoadPlan(int planId) async {
    try {
      await _api.post('${AppConfig.roadPlansPath}/$planId/cancel', data: {});
      _success = 'Jadwal dibatalkan';
      _plans.removeWhere((p) => p.id == planId && p.source == 'snc');
      notifyListeners();
      return true;
    } catch (_) {
      _error = 'Gagal membatalkan jadwal';
      notifyListeners();
      return false;
    }
  }

  void clearMessages() {
    _error = null;
    _success = null;
  }
}
