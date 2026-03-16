import 'package:flutter/material.dart';
import '../../../core/config/app_config.dart';
import '../../../core/services/api_service.dart';

class DashboardStats {
  final int totalVisitsToday;
  final int checkedInNow;
  final int completedToday;
  final int pendingApprovals;
  final int totalCustomers;
  final int totalTechnicians;

  const DashboardStats({
    this.totalVisitsToday = 0,
    this.checkedInNow = 0,
    this.completedToday = 0,
    this.pendingApprovals = 0,
    this.totalCustomers = 0,
    this.totalTechnicians = 0,
  });

  factory DashboardStats.fromJson(Map<String, dynamic> json) => DashboardStats(
        totalVisitsToday: json['total_visits_today'] as int? ?? 0,
        checkedInNow: json['checked_in_now'] as int? ?? 0,
        completedToday: json['completed_today'] as int? ?? 0,
        pendingApprovals: json['pending_approvals'] as int? ?? 0,
        totalCustomers: json['total_customers'] as int? ?? 0,
        totalTechnicians: json['total_technicians'] as int? ?? 0,
      );
}

class DashboardProvider extends ChangeNotifier {
  final _api = ApiService();

  DashboardStats _stats = const DashboardStats();
  bool _loading = false;
  String? _error;

  DashboardStats get stats => _stats;
  bool get loading => _loading;
  String? get error => _error;

  Future<void> load() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final res = await _api.get(AppConfig.mobileDashboardPath);
      _stats = DashboardStats.fromJson(res.data as Map<String, dynamic>);
    } catch (e) {
      _error = 'Gagal memuat dashboard';
    } finally {
      _loading = false;
      notifyListeners();
    }
  }
}
