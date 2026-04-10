import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import '../../../core/config/app_config.dart';
import '../../../core/services/api_service.dart';
import '../../../core/services/offline_cache_service.dart';

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

  Map<String, dynamic> toJson() => {
        'total_visits_today': totalVisitsToday,
        'checked_in_now': checkedInNow,
        'completed_today': completedToday,
        'pending_approvals': pendingApprovals,
        'total_customers': totalCustomers,
        'total_technicians': totalTechnicians,
      };
}

class DashboardProvider extends ChangeNotifier {
  final _api = ApiService();

  DashboardStats _stats = const DashboardStats();
  bool _loading = false;
  bool _isOffline = false;
  String? _error;

  DashboardStats get stats => _stats;
  bool get loading => _loading;
  bool get isOffline => _isOffline;
  String? get error => _error;

  Future<void> load() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final res = await _api.get(AppConfig.mobileDashboardPath);
      final json = res.data as Map<String, dynamic>;
      _stats = DashboardStats.fromJson(json);
      _isOffline = false;

      // Cache for offline
      await OfflineCacheService.instance.cacheDashboard(json);
    } on DioException {
      // Network error — serve from cache
      final cached = await OfflineCacheService.instance.getCachedDashboard();
      if (cached != null) {
        _stats = DashboardStats.fromJson(cached);
        _isOffline = true;
        _error = 'Offline — menampilkan data terakhir.';
      } else {
        _error = 'Tidak ada koneksi.';
      }
    } catch (e) {
      _error = 'Gagal memuat dashboard';
    } finally {
      _loading = false;
      notifyListeners();
    }
  }
}
