import 'package:flutter/material.dart';
import '../../../core/config/app_config.dart';
import '../../../core/models/approval_model.dart';
import '../../../core/services/api_service.dart';

class ApprovalsProvider extends ChangeNotifier {
  final _api = ApiService();

  List<ApprovalModel> _approvals = [];
  bool _loading = false;
  String? _error;

  List<ApprovalModel> get approvals => _approvals;
  bool get loading => _loading;
  String? get error => _error;
  int get pendingCount => _approvals.length;

  Future<void> load() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final res = await _api.get(AppConfig.mobileApprovalsPath);
      _approvals = (res.data as List)
          .map((e) => ApprovalModel.fromJson(e as Map<String, dynamic>))
          .toList();
    } catch (e) {
      _error = 'Gagal memuat persetujuan';
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  Future<bool> approve(int id) async {
    try {
      await _api.post('${AppConfig.mobileApprovalsPath}/$id/approve');
      _approvals.removeWhere((a) => a.id == id);
      notifyListeners();
      return true;
    } catch (_) {
      return false;
    }
  }

  Future<bool> reject(int id, String reason) async {
    try {
      await _api.post(
        '${AppConfig.mobileApprovalsPath}/$id/reject',
        data: {'reason': reason},
      );
      _approvals.removeWhere((a) => a.id == id);
      notifyListeners();
      return true;
    } catch (_) {
      return false;
    }
  }
}
