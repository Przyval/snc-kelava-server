import 'package:flutter/material.dart';
import '../../../core/config/app_config.dart';
import '../../../core/models/customer_model.dart';
import '../../../core/services/api_service.dart';

class CustomerProvider extends ChangeNotifier {
  final _api = ApiService();

  List<CustomerModel> _all = [];
  List<CustomerModel> _filtered = [];
  bool _loading = false;
  String? _error;
  String _query = '';

  List<CustomerModel> get customers => _filtered;
  bool get loading => _loading;
  String? get error => _error;

  Future<void> load() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      final res = await _api.get(AppConfig.mobileCustomersPath);
      _all = (res.data as List)
          .map((e) => CustomerModel.fromJson(e as Map<String, dynamic>))
          .toList();
      _applyFilter();
    } catch (e) {
      _error = 'Gagal memuat pelanggan';
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  void search(String query) {
    _query = query.toLowerCase();
    _applyFilter();
    notifyListeners();
  }

  void _applyFilter() {
    if (_query.isEmpty) {
      _filtered = List.from(_all);
    } else {
      _filtered = _all.where((c) {
        return c.name.toLowerCase().contains(_query) ||
            c.code.toLowerCase().contains(_query) ||
            (c.address?.toLowerCase().contains(_query) ?? false);
      }).toList();
    }
  }
}
